"""JaegerAI gateway/bridge transport for browser-originated ARES chat turns.

This is the JaegerAI twin of ``api.gateway_chat`` (the ARES Gateway bridge)
and is deliberately shaped like it: /api/chat/start still creates a normal
local WebUI stream, /api/chat/stream still receives WebUI SSE event names,
and the final turn is persisted back into the same WebUI session model.
The only swapped piece is execution, which resolves in this order:

1. **Gateway (vestigial — see ADR-0008)** — POST the turn to a gateway
   server and relay its SSE reply. Current JaegerAI ships **no gateway
   server**: there is no ``jaeger gateway`` command, and
   ``jaeger_ai/core/models/llm_client.py`` *consumes* ``/v1/chat/completions``
   from an external llama-server rather than serving it. This branch is
   inherited from predecessor JROS and only runs when an operator has
   explicitly set ``ARES_JAEGER_GATEWAY_URL`` at something that speaks the
   dialect. Do not treat it as the primary path or plan around it.

2. **Local bridge** — when no gateway is configured and a local JaegerAI
   install is discoverable from ``ARES_JAEGER_HOME``,
   ``JAEGER_HOME``, the standard ``~/jaeger`` install path, or the legacy
   a validated development checkout, ARES spawns JaegerAI's
   ``jaeger bridge`` and speaks the documented v1 NDJSON client protocol
   over stdio. That keeps JROS inside its own venv/native dependency
   environment while preserving the local flip-the-toggle case. Bridge
   failures surface as actionable errors instead of crashes: an
   already-running JaegerAI (its exclusive instance lock) says close it or
   use a different instance name, and a missing instance says run
   ``jaeger setup``.

   This is the **real** ARES↔JaegerAI transport today (ADR-0008).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from api.config import (
    AGENT_INSTANCES,
    CANCEL_FLAGS,
    PENDING_GOAL_CONTINUATION,
    STREAM_GOAL_RELATED,
    STREAM_LAST_EVENT_ID,
    STREAM_LIVE_TOOL_CALLS,
    STREAM_PARTIAL_TEXT,
    STREAM_REASONING_TEXT,
    STREAMS,
    STREAMS_LOCK,
    _get_session_agent_lock,
    register_active_run,
    unregister_active_run,
    unregister_stream_owner,
    update_active_run,
)
from api.helpers import _redact_text, redact_session_data
from api.providers.jaeger.bridge_client import JrosClient, JrosError
from api.models import get_session, merge_session_messages_append_only
from api.run_journal import RunJournalWriter
from api.providers.jaeger.paths import jaeger_home, jros_instance_name

logger = logging.getLogger(__name__)

_JAEGER_GATEWAY_URL_ENV = "ARES_JAEGER_GATEWAY_URL"
_JAEGER_GATEWAY_KEY_ENV = "ARES_JAEGER_GATEWAY_KEY"
_LEGACY_GATEWAY_URL_ENV = "ARES_JROS_GATEWAY_URL"
_LEGACY_GATEWAY_KEY_ENV = "ARES_JROS_GATEWAY_KEY"
DEFAULT_JROS_GATEWAY_URL = ""

_START_GATEWAY_HINT = (
    "JaegerAI runs through the local bridge (`jaeger bridge`). "
    "Make sure JaegerAI is installed and an agent instance exists."
)


def jros_gateway_base_url(config_data=None, environ: dict[str, str] | None = None) -> str:
    """Resolve an explicitly configured JaegerAI endpoint without owning it."""
    source = os.environ if environ is None else environ
    cfg = config_data if isinstance(config_data, dict) else {}
    from api.provider_registry import provider_endpoint

    raw = str(
        provider_endpoint("jaeger_local", environ=source)
        or source.get(_JAEGER_GATEWAY_URL_ENV)
        or source.get(_LEGACY_GATEWAY_URL_ENV)
        or cfg.get("jaeger_gateway_url")
        or cfg.get("jros_gateway_url")
        or ""
    ).strip()
    return raw.rstrip("/")


def _jros_gateway_api_key(environ: dict[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return str(
        source.get(_JAEGER_GATEWAY_KEY_ENV)
        or source.get(_LEGACY_GATEWAY_KEY_ENV)
        or ""
    ).strip()


def _auth_headers() -> dict[str, str]:
    key = _jros_gateway_api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def jros_gateway_health(timeout: float = 1.0, config_data=None) -> dict | None:
    """GET /v1/health from the configured JROS gateway.

    Returns the health payload dict when a live gateway answers, or None
    when unreachable — the availability signal api.backend_selector uses
    to light up the JROS option in the UI."""
    base_url = jros_gateway_base_url(config_data)
    if not base_url:
        return None
    url = f"{base_url}/v1/health"
    req = urllib.request.Request(url, headers=_auth_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload if isinstance(payload, dict) and payload.get("ok") else None
    except Exception:
        return None


def reset_jros_boot() -> None:
    """Drop every cached JROS boot so the next turn re-boots from disk config.

    JROS has no live model hot-swap (its client's model is fixed at
    construction time), so provider/model changes written to JROS's
    config.yaml (see api.ares_provider_sync) only apply after a re-boot.
    Covers both execution paths: the bridge fallback's cached client is
    dropped here, and the gateway is asked to re-boot via POST /v1/reset.
    Best-effort: an unreachable gateway just means the next operator-run
    gateway boots fresh from disk anyway."""
    # The serving lane is fixed at boot, so a re-boot invalidates whatever we
    # cached about which model is answering.
    reset_serving_model_cache()
    _reset_local_bridge_clients()
    base_url = jros_gateway_base_url()
    if not base_url:
        return
    url = f"{base_url}/v1/reset"
    req = urllib.request.Request(
        url, data=b"{}",
        headers={"Content-Type": "application/json", **_auth_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        logger.debug("JROS gateway reset skipped (gateway unreachable)", exc_info=True)


# ── bridge fallback (no gateway, JROS on this machine) ──────────────────

_JAEGER_SOURCE_DIR_ENV = "ARES_JAEGER_SOURCE_DIR"
_JAEGER_INSTANCE_ENV = "ARES_JAEGER_INSTANCE"
_LEGACY_SOURCE_DIR_ENV = "ARES_JROS_DIR"
_LEGACY_INSTANCE_ENV = "ARES_JROS_INSTANCE"

_BOOT_LOCK = threading.RLock()
_BRIDGE_CLIENTS: dict[str, JrosClient] = {}
_BRIDGE_TURN_LOCKS: dict[str, threading.RLock] = {}


def local_jros_root() -> Path | None:
    """The local JaegerAI runtime/source root for bridge execution, or None.

    Resolution order keeps explicit source checkouts first, then the installed
    Jaeger/JaegerAI runtime path. This is what the installer detects as ``~/jaeger``
    on a normal user machine, and what ``ARES_JAEGER_HOME`` / ``JAEGER_HOME``
    override for nonstandard installs.
    """
    from api.providers.jaeger.paths import is_jaeger_ai_root

    raw = (
        os.environ.get(_JAEGER_SOURCE_DIR_ENV)
        or os.environ.get(_LEGACY_SOURCE_DIR_ENV)
        or ""
    ).strip()
    if raw:
        root = Path(raw).expanduser().resolve()
        # Explicit dependency selection is fail-closed. Never hide a stale or
        # legacy path by silently switching to a different checkout.
        return root if is_jaeger_ai_root(root) else None

    try:
        root = jaeger_home()
    except Exception:
        root = None
    return root if root is not None and is_jaeger_ai_root(root) else None


def _jros_instance_name() -> str | None:
    return str(
        os.environ.get(_JAEGER_INSTANCE_ENV)
        or os.environ.get(_LEGACY_INSTANCE_ENV)
        or ""
    ).strip() or jros_instance_name()


def _jros_ares_tools_enabled() -> bool:
    """Whether the Companion should boot with Ares's tools reachable over
    MCP — an opt-in addition on top of the jros backend, not a competing
    backend mode. See api.jros_ares_mcp for the config-sync side."""
    try:
        from api.config import get_config

        return bool(get_config().get("jros_ares_tools_enabled"))
    except Exception:
        return False


def _bridge_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    lower = message.lower()
    if "lock" in lower:
        return (
            "JaegerAI is already running on this machine, so ARES can't start a "
            "second copy (JaegerAI allows one process per instance). Close the "
            "running JaegerAI app/TUI, or use a different instance name so "
            f"ARES can start its own bridge. (Original error: {message})"
        )
    if _is_dead_bridge_error(exc):
        return (
            "JaegerAI's local bridge died mid-turn — usually because the "
            "JaegerOS app or another Jaeger process took the exclusive instance "
            "lock. Close JaegerOS / the other Jaeger window and send again so "
            f"ARES can start its own bridge. (Original error: {message})"
        )
    if "no instance" in lower or "instance" in lower and ("not found" in lower or "does not exist" in lower):
        return f"{message} — run `jaeger setup` on the machine where JaegerAI is installed first."
    return message


def _is_dead_bridge_error(exc: Exception) -> bool:
    """True when the cached ``jaeger bridge`` child is gone and a retry may help."""
    if isinstance(exc, BrokenPipeError):
        return True
    errno = getattr(exc, "errno", None)
    if errno == 32:
        return True
    lower = str(exc).lower()
    return (
        "broken pipe" in lower
        or "bridge exited" in lower
        or "not started" in lower
    )


def _evict_bridge_client(key: str, client: JrosClient | None) -> None:
    """Drop a cached client so the next call starts a fresh bridge."""
    if client is None:
        return
    with _BOOT_LOCK:
        if _BRIDGE_CLIENTS.get(key) is client:
            _BRIDGE_CLIENTS.pop(key, None)
            _BRIDGE_TURN_LOCKS.pop(key, None)
    try:
        client.close()
    except Exception:
        logger.debug("Failed to close errored JROS bridge", exc_info=True)


def _client_is_alive(client: JrosClient) -> bool:
    check = getattr(client, "is_alive", None)
    if check is None:
        return True
    try:
        return bool(check())
    except Exception:
        return False


def _get_or_start_bridge_client(instance: str | None = None) -> JrosClient:
    """Start and cache one ``jaeger bridge`` client per JROS instance.

    The bridge launcher uses JROS's own venv interpreter, so ARES never imports
    native JROS ML packages into the WebUI venv.
    """
    key = instance or "__default__"
    with _BOOT_LOCK:
        existing = _BRIDGE_CLIENTS.get(key)
        if existing is not None:
            if _client_is_alive(existing):
                return existing
            _BRIDGE_CLIENTS.pop(key, None)
            _BRIDGE_TURN_LOCKS.pop(key, None)
            try:
                existing.close()
            except Exception:
                logger.debug("Failed to close dead JROS bridge", exc_info=True)
        root = local_jros_root()
        if root is None:
            raise JrosError(
                "No local JaegerAI runtime was found. Install JaegerAI, set "
                "ARES_JAEGER_HOME/JAEGER_HOME to that installation, or set the "
                "legacy ARES_JROS_DIR override to a validated JaegerAI source "
                "checkout."
            )
        env = os.environ.copy()
        try:
            from api.config import SESSION_DIR, PORT, ARES_HOME
            env["ARES_SESSION_DIR"] = str(SESSION_DIR)
            env["ARES_HOME"] = str(ARES_HOME)
            env["ARES_CONTROLLER_PORT"] = str(PORT)
        except Exception:
            pass
        client = JrosClient(jaeger_home=str(root), instance=instance, env=env)
        try:
            client.start()
        except Exception as exc:
            client.close()
            if isinstance(exc, JrosError):
                raise JrosError(_bridge_error_message(exc)) from exc
            raise JrosError(_bridge_error_message(exc)) from exc
        _BRIDGE_CLIENTS[key] = client
        _BRIDGE_TURN_LOCKS.setdefault(key, threading.RLock())
        return client


def _reset_local_bridge_clients() -> None:
    """Drop cached bridge clients, releasing JaegerAI's instance lock."""
    with _BOOT_LOCK:
        clients = list(_BRIDGE_CLIENTS.values())
        _BRIDGE_CLIENTS.clear()
        _BRIDGE_TURN_LOCKS.clear()
    for client in clients:
        try:
            client.close()
        except Exception:
            logger.debug("Local JaegerAI bridge cleanup failed", exc_info=True)


_SERVING_MODEL_CACHE: dict[str, Any] = {"at": 0.0, "value": None}
_SERVING_MODEL_TTL = 30.0


def _serving_model_truth() -> dict[str, Any] | None:
    """What JaegerAI says is actually answering, or ``None`` if it won't say.

    Asked over the bridge's ``serving_model`` query rather than inferred from
    ARES's own selection, because the two can disagree: JaegerAI picks its
    serving lane at boot, and a cloud lane that failed to start leaves the
    request in its config while a local model answers. ARES showing the
    requested model there would be a lie of exactly the kind the operator
    cannot see through.

    Cached briefly — the serving lane changes on model switch or restart, not
    within a turn — and never raises, because a display value must not be
    able to fail a turn.
    """
    now = time.time()
    if (
        _SERVING_MODEL_CACHE["value"] is not None
        and now - float(_SERVING_MODEL_CACHE["at"]) < _SERVING_MODEL_TTL
    ):
        return _SERVING_MODEL_CACHE["value"]
    try:
        payload = query_local_companion("serving_model")
    except Exception:
        logger.debug("serving_model query failed", exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    serving = payload.get("serving")
    if not isinstance(serving, dict):
        # Pre-boot: JaegerAI reports its configured intent but nothing is
        # serving yet. Don't cache that as truth.
        return None
    _SERVING_MODEL_CACHE["at"] = now
    _SERVING_MODEL_CACHE["value"] = serving
    return serving


def reset_serving_model_cache() -> None:
    """Drop the cached serving lane — call after a model switch or restart."""
    _SERVING_MODEL_CACHE["at"] = 0.0
    _SERVING_MODEL_CACHE["value"] = None


def query_local_companion(what: str, args: dict[str, Any] | None = None) -> Any:
    """Read the selected Companion through JaegerAI's public bridge protocol."""
    instance = _jros_instance_name()
    client = _get_or_start_bridge_client(instance)
    return client.query(what, args or {})


def local_integration_contract() -> dict[str, Any]:
    """Negotiate and validate the selected Jaeger runtime's feature contract."""
    instance = _jros_instance_name()
    client = _get_or_start_bridge_client(instance)
    return client.integration_contract()


def command_local_companion(cmd: str, args: dict[str, Any] | None = None) -> Any:
    """Ask JaegerAI to mutate its selected Companion through its bridge."""
    instance = _jros_instance_name()
    client = _get_or_start_bridge_client(instance)
    return client.command(cmd, args or {})


def _translate_bridge_frame(frame: dict[str, Any], put_jros_event, stream_id: str) -> None:
    kind = str(frame.get("type") or "").strip().lower()
    if kind == "tool":
        name = str(frame.get("name") or frame.get("tool") or "jros").strip() or "jros"
        status = str(frame.get("status") or frame.get("event") or frame.get("state") or "").strip().lower()
        event_type = "tool.completed" if status in ("done", "complete", "completed", "ok") else "tool.running"
        preview = str(
            frame.get("preview")
            or frame.get("message")
            or frame.get("label")
            or frame.get("text")
            or name
        ).strip()
        is_error = bool(frame.get("is_error") or frame.get("error") or status in ("error", "failed", "fail"))
        payload = {
            "event_type": "tool.failed" if is_error else event_type,
            "name": name,
            "preview": preview,
            "is_error": is_error,
        }
        if isinstance(frame.get("args"), dict):
            payload["args"] = frame["args"]
        if stream_id in STREAM_LIVE_TOOL_CALLS:
            STREAM_LIVE_TOOL_CALLS[stream_id].append({
                "name": name,
                "args": payload.get("args") or {"preview": preview},
                "done": payload["event_type"] != "tool.running",
            })
        put_jros_event("tool", payload)
        return
    if kind == "state":
        message = str(frame.get("message") or frame.get("text") or frame.get("state") or "").strip()
        if message:
            put_jros_event("reasoning", {"text": message})


class _JaegerBridgeTurnControl:
    """Expose Jaeger's live bridge controls through ARES's existing registry."""

    def __init__(self, client: JrosClient, session_id: str) -> None:
        self._client = client
        self.session_id = session_id
        self._bridge_session = f"webui:{session_id}"

    def interrupt(self, _reason: str = "") -> None:
        self._client.cancel(self._bridge_session)

    def steer(self, text: str) -> bool:
        if not str(text or "").strip() or not self._client.is_alive():
            return False
        self._client.steer(text, self._bridge_session)
        return True


def _run_local_jros_turn(
    msg_text: str,
    session_id: str,
    cancel_event: threading.Event,
    put_jros_event=None,
    stream_id: str = "",
) -> tuple[str, str, list[str]]:
    """One local JROS bridge turn. Returns (text, error, tool_activity)."""
    instance = _jros_instance_name()
    key = instance or "__default__"
    last_exc: Exception | None = None
    for attempt in (1, 2):
        client: JrosClient | None = None
        try:
            client = _get_or_start_bridge_client(instance)
            if cancel_event.is_set():
                return "", "", []
            control = _JaegerBridgeTurnControl(client, session_id)
            if stream_id:
                with STREAMS_LOCK:
                    AGENT_INSTANCES[stream_id] = control
            lock = _BRIDGE_TURN_LOCKS.setdefault(key, threading.RLock())
            tool_activity: list[str] = []

            def on_event(frame: dict[str, Any]) -> None:
                if cancel_event.is_set():
                    return
                if isinstance(frame, dict):
                    preview = str(
                        frame.get("preview")
                        or frame.get("message")
                        or frame.get("label")
                        or frame.get("text")
                        or frame.get("name")
                        or frame.get("tool")
                        or ""
                    ).strip()
                    if preview:
                        tool_activity.append(preview)
                    if put_jros_event is not None:
                        _translate_bridge_frame(frame, put_jros_event, stream_id)

            def _on_request(frame: dict[str, Any]) -> str:
                """Route Jaeger's blocking request through ARES's UI controls."""
                kind = str(frame.get("kind") or "").strip().lower()
                request_id = str(frame.get("id") or "").strip()
                if kind == "approval":
                    from api.route_approvals import wait_for_external_approval

                    choice = wait_for_external_approval(
                        session_id,
                        {
                            "approval_id": request_id,
                            "tool": str(frame.get("tool") or "jaeger"),
                            "description": str(frame.get("prompt") or frame.get("message") or "Jaeger requests permission."),
                            "pattern_key": str(frame.get("tool") or request_id or "jaeger"),
                            "pattern_keys": [str(frame.get("tool") or request_id or "jaeger")],
                            "choices": list(frame.get("options") or []),
                            "source": "jaeger_bridge",
                        },
                    )
                    return "once" if choice == "session" else choice
                if kind in {"clarify", "secret"}:
                    from api.clarify import clear_pending, submit_pending

                    entry = submit_pending(session_id, {
                        "clarify_id": request_id,
                        "question": str(frame.get("prompt") or frame.get("message") or "Jaeger needs input."),
                        "choices_offered": list(frame.get("options") or []),
                        "kind": kind,
                        "session_id": session_id,
                    })
                    if entry.event.wait(120.0):
                        return str(entry.result or "deny")
                    clear_pending(session_id)
                return "deny"

            with lock:
                result = client.turn(
                    str(msg_text or ""),
                    session=f"webui:{session_id}",
                    on_event=on_event,
                    on_request=_on_request,
                )
            payload = dict(result or {}) if isinstance(result, dict) else {}
            error = str(payload.get("error") or "").strip()
            text = str(payload.get("text") or "").strip()
            return text, error, [] if put_jros_event is not None else tool_activity
        except Exception as exc:
            last_exc = exc
            _evict_bridge_client(key, client)
            if attempt == 1 and _is_dead_bridge_error(exc):
                logger.warning(
                    "Local JaegerAI bridge died; retrying with a fresh process: %s",
                    exc,
                )
                continue
            logger.warning("Local JaegerAI bridge turn failed: %s", exc, exc_info=True)
            return "", _bridge_error_message(exc), []
    return "", _bridge_error_message(last_exc or JrosError("bridge failed")), []


def _stream_writeback_is_current(session: Any, stream_id: str) -> bool:
    return bool(stream_id and getattr(session, "active_stream_id", None) == stream_id)


def _clear_jros_pending_state(session: Any, stream_id: str) -> None:
    if not _stream_writeback_is_current(session, stream_id):
        return
    session.active_stream_id = None
    session.pending_user_message = None
    session.pending_attachments = None
    session.pending_started_at = None
    session.pending_user_source = None
    session.save()


def _persist_jros_failed_user_turn(
    *,
    session_id: str,
    stream_id: str,
    user_text: str,
    attachments: list | None,
) -> None:
    """Keep the typed user row when a turn errors, so refresh isn't an empty chat."""
    visible = str(user_text or "").strip()
    if not visible:
        return
    with _get_session_agent_lock(session_id):
        session = get_session(session_id)
        if not _stream_writeback_is_current(session, stream_id):
            return
        user_msg = {"role": "user", "content": visible, "timestamp": time.time()}
        pending_source = getattr(session, "pending_user_source", None) or "webui"
        if pending_source != "webui":
            user_msg["_source"] = pending_source
        if attachments:
            user_msg["attachments"] = list(attachments)
        messages = list(getattr(session, "messages", None) or [])
        last = messages[-1] if messages else None
        already = (
            isinstance(last, dict)
            and last.get("role") == "user"
            and " ".join(str(last.get("content") or "").split()) == " ".join(visible.split())
        )
        if not already:
            session.messages = messages + [user_msg]
            context = list(getattr(session, "context_messages", None) or [])
            session.context_messages = context + [user_msg]
        session.save()


def _merge_and_save_jros_turn(
    *,
    session_id: str,
    stream_id: str,
    msg_text: str,
    assistant_text: str,
    workspace: str,
    model: str,
    model_provider: str | None,
    attachments: list | None,
    usage: dict | None = None,
    user_text: str | None = None,
) -> Any:
    # ``msg_text`` is the execution prompt and may be context-wrapped. Only the
    # text the user actually typed may become a visible ``role=user`` message.
    visible_user_text = str(user_text if user_text is not None else msg_text or "")
    with _get_session_agent_lock(session_id):
        s = get_session(session_id)
        if not _stream_writeback_is_current(s, stream_id):
            return None
        now = time.time()
        assistant_ts = now + 0.000001
        user_msg = {"role": "user", "content": visible_user_text, "timestamp": now}
        pending_source = getattr(s, "pending_user_source", None) or "webui"
        if pending_source != "webui":
            user_msg["_source"] = pending_source
        if attachments:
            user_msg["attachments"] = list(attachments)
        selected_model_provider = str(model_provider or "").strip() or None
        assistant_msg = {
            "role": "assistant",
            "content": assistant_text,
            "timestamp": assistant_ts,
            "backend": "jros",
        }
        if selected_model_provider:
            assistant_msg["model_provider"] = selected_model_provider
        saved_reasoning = STREAM_REASONING_TEXT.get(stream_id, "")
        if saved_reasoning:
            assistant_msg["reasoning"] = saved_reasoning
        previous_context = list(getattr(s, "context_messages", None) or getattr(s, "messages", None) or [])
        s.context_messages = previous_context + [user_msg, assistant_msg]
        try:
            from api.streaming import _is_context_compression_marker

            display_context = [
                msg
                for msg in previous_context
                if not _is_context_compression_marker(msg)
            ]
        except Exception:
            logger.debug("Failed to filter JROS display context markers", exc_info=True)
            display_context = previous_context
        display = merge_session_messages_append_only(
            list(getattr(s, "messages", None) or []),
            display_context,
        )
        try:
            from api.streaming import _merge_display_messages_after_agent_result

            s.messages = _merge_display_messages_after_agent_result(
                display,
                previous_context,
                s.context_messages,
                visible_user_text,
                source=pending_source,
            )
            # Ensure the persisted assistant row carries the backend marker.
            for msg in reversed(s.messages):
                if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("content") == assistant_text:
                    msg["backend"] = "jros"
                    if selected_model_provider:
                        msg["model_provider"] = selected_model_provider
                    break
        except Exception:
            logger.debug("Failed to merge JROS display transcript", exc_info=True)
            if display:
                latest = display[-1]
                if isinstance(latest, dict) and latest.get("role") == "user":
                    latest_text = " ".join(str(latest.get("content") or "").split())
                    msg_norm = " ".join(str(msg_text or "").split())
                    if latest_text == msg_norm:
                        display = display[:-1]
            s.messages = display + [user_msg, assistant_msg]
        s.active_stream_id = None
        s.pending_user_message = None
        s.pending_attachments = None
        s.pending_started_at = None
        s.pending_user_source = None
        s.workspace = str(workspace)
        s.model = model or getattr(s, "model", "") or ""
        s.model_provider = selected_model_provider
        # Record what ACTUALLY served the turn, not what we asked for.
        # JaegerAI decides the serving lane at boot and can end up on a
        # different model than the config requests (a cloud lane that failed
        # to start leaves ``external_model.enabled: true`` in the file while a
        # local model answers). Reporting the requested model in that case
        # tells the operator they are on a cloud brain when they are not, so
        # ask the bridge and record the answer through ARES's existing
        # requested-vs-used contract, which the WebUI already renders.
        _served = _serving_model_truth()
        if _served:
            used_model = str(_served.get("name") or "").strip()
            used_provider = str(_served.get("provider") or "").strip()
            if used_model:
                s.model = used_model
            if used_provider:
                s.model_provider = used_provider
            try:
                from api.streaming import _normalize_gateway_routing_metadata

                routing = _normalize_gateway_routing_metadata(
                    {
                        "used_model": used_model,
                        "used_provider": used_provider,
                        "requested_model": model or used_model,
                        "requested_provider": selected_model_provider or used_provider,
                    },
                    requested_model=model or used_model,
                    requested_provider=selected_model_provider or used_provider,
                )
                if routing:
                    routing["serving_fallback"] = bool(_served.get("fallback_active"))
                    routing["serving_detail"] = str(_served.get("status") or "")
                    s.gateway_routing = routing
                    history = getattr(s, "gateway_routing_history", None)
                    if isinstance(history, list):
                        history.append(routing)
                    else:
                        s.gateway_routing_history = [routing]
            except Exception:
                logger.debug("Could not record jros serving-model routing", exc_info=True)

        # Persist the serving model's real context window so the WebUI ring
        # has something true to draw. Without this the jros path never wrote
        # ``context_length`` at all and ui.js fell through to its hardcoded
        # ``DEFAULT_CTX = 128*1024`` — the ring read 131072 for every model,
        # which is why a 1M-window cloud model looked stuck at 128K no matter
        # what the catalogue or the config said. The window the serving lane
        # reports wins; the resolver is the fallback. Never fails a turn over
        # a display value.
        try:
            from api.model_context import (
                resolve_context_length_for_session_model,
                should_accept_context_length_refresh,
            )

            resolved_ctx = 0
            if _served:
                try:
                    resolved_ctx = int(_served.get("context_length") or 0)
                except (TypeError, ValueError):
                    resolved_ctx = 0
            if resolved_ctx <= 0:
                resolved_ctx = resolve_context_length_for_session_model(
                    s.model, getattr(s, "model_provider", None) or selected_model_provider,
                )
            persisted_ctx = int(getattr(s, "context_length", 0) or 0)
            if should_accept_context_length_refresh(
                persisted_ctx,
                resolved_ctx,
                model_changed=persisted_ctx > 0 and resolved_ctx != persisted_ctx,
            ):
                s.context_length = resolved_ctx
        except Exception:
            logger.debug(
                "Could not resolve a context window for jros session %s",
                session_id,
                exc_info=True,
            )
        if usage:
            # JaegerAI's usage dict is per-turn (an OpenAI-style chunk's
            # prompt/completion_tokens, or a fresh word-count estimate), unlike
            # the "ares" backend's Agent SDK counters which are already
            # session-cumulative — so accumulate here instead of overwriting,
            # or multi-turn sessions would report only their last turn's usage.
            turn_input = int(usage.get("input_tokens") or 0)
            turn_output = int(usage.get("output_tokens") or 0)
            turn_cost = usage.get("estimated_cost")
            turn_cache_read = int(usage.get("cache_read_tokens") or 0)
            turn_cache_write = int(usage.get("cache_write_tokens") or 0)
            if turn_input > 0:
                s.input_tokens = int(getattr(s, "input_tokens", 0) or 0) + turn_input
            if turn_output > 0:
                s.output_tokens = int(getattr(s, "output_tokens", 0) or 0) + turn_output
            if turn_cache_read > 0:
                s.cache_read_tokens = int(getattr(s, "cache_read_tokens", 0) or 0) + turn_cache_read
            if turn_cache_write > 0:
                s.cache_write_tokens = int(getattr(s, "cache_write_tokens", 0) or 0) + turn_cache_write
            if turn_cost:
                try:
                    s.estimated_cost = float(getattr(s, "estimated_cost", 0) or 0) + float(turn_cost)
                except (TypeError, ValueError):
                    pass
        s.save()
        return s


def _run_jros_goal_hook(*, session_id: str, stream_id: str, goal_related: bool, assistant_text: str, put_jros_event) -> None:
    try:
        from api.goals import evaluate_goal_after_turn, has_active_goal
        from api.profiles import get_ares_home_for_profile

        s = get_session(session_id)
        profile_home = get_ares_home_for_profile(str(getattr(s, "profile", None) or "default"))
        if goal_related and has_active_goal(session_id, profile_home=profile_home):
            put_jros_event("goal", {
                "session_id": session_id,
                "state": "evaluating",
                "message": "Evaluating goal progress…",
                "message_key": "goal_evaluating_progress",
            })
            decision = evaluate_goal_after_turn(
                session_id,
                assistant_text,
                user_initiated=True,
                profile_home=profile_home,
            ) or {}
            goal_message = str(decision.get("message") or "").strip()
            if goal_message:
                put_jros_event("goal", {
                    "session_id": session_id,
                    "state": "continuing" if decision.get("should_continue") else "idle",
                    "message": goal_message,
                    "message_key": decision.get("message_key") or ("goal_continuing" if goal_message else ""),
                    "message_args": decision.get("message_args") or [],
                    "decision": decision,
                })
            if decision.get("should_continue"):
                continuation_prompt = str(decision.get("continuation_prompt") or "").strip()
                if continuation_prompt:
                    PENDING_GOAL_CONTINUATION.add(session_id)
                    put_jros_event("goal_continue", {
                        "session_id": session_id,
                        "continuation_prompt": continuation_prompt,
                        "text": continuation_prompt,
                        "message": goal_message,
                        "message_key": decision.get("message_key") or "goal_continuing",
                        "message_args": decision.get("message_args") or [],
                        "decision": decision,
                    })
    except Exception as goal_exc:
        logger.debug("JaegerAI goal continuation hook failed for session %s: %s", session_id, goal_exc)


def _jros_http_error_event(exc: urllib.error.HTTPError, err_body: str) -> dict:
    safe = _redact_text(err_body or str(exc))[:500]
    if exc.code == 401:
        key_configured = bool(_jros_gateway_api_key())
        return {
            "label": "Jaeger AI gateway authentication failed",
            "type": "jaeger_auth_error",
            "message": "Jaeger AI gateway rejected the request (HTTP 401).",
            "hint": (
                "Set ARES_JAEGER_GATEWAY_KEY to the same value as the gateway's "
                "JAEGER_GATEWAY_KEY."
                if not key_configured
                else "Check that ARES_JAEGER_GATEWAY_KEY matches the gateway's JAEGER_GATEWAY_KEY."
            ),
        }
    return {
        "label": "Jaeger AI gateway request failed",
        "type": "jaeger_http_error",
        "message": f"Jaeger AI gateway returned HTTP {exc.code}.",
        "hint": safe or _START_GATEWAY_HINT,
    }


def _run_jros_chat_streaming(
    session_id,
    msg_text,
    model,
    workspace,
    stream_id,
    attachments=None,
    *,
    model_provider=None,
    goal_related=False,
    user_text=None,
    original_message=None,
):
    """Bridge a WebUI chat turn through JaegerAI using the Ares
    worker contract (same signature routes._select_chat_worker_target
    dispatches to).

    ``msg_text`` is the execution prompt (context-wrapped for stateless
    workers). ``user_text`` is what the user actually typed and is the only
    value that may be persisted as a ``role=user`` message.
    """
    # The typed text, under whichever alias the caller supplied. Falls back to
    # the execution prompt only when no alias was passed at all.
    _effective_user_text = next(
        (str(value) for value in (user_text, original_message) if value is not None),
        str(msg_text or ""),
    )
    q = STREAMS.get(stream_id)
    if q is None:
        unregister_stream_owner(stream_id)
        return
    register_active_run(
        stream_id,
        session_id=session_id,
        started_at=time.time(),
        phase="jros-starting",
        workspace=str(workspace),
        model=model or "",
        provider=model_provider or None,
        backend="jros",
    )
    try:
        run_journal = RunJournalWriter(session_id, stream_id)
    except Exception:
        run_journal = None
        logger.debug("Failed to initialize JROS run journal for stream %s", stream_id, exc_info=True)
    cancel_event = threading.Event()
    with STREAMS_LOCK:
        CANCEL_FLAGS[stream_id] = cancel_event
        STREAM_PARTIAL_TEXT[stream_id] = ""
        STREAM_REASONING_TEXT[stream_id] = ""
        STREAM_LIVE_TOOL_CALLS[stream_id] = []

    def put_jros_event(event, data):
        if cancel_event.is_set() and event not in ("cancel", "error", "apperror"):
            return
        event_id = None
        if run_journal is not None:
            try:
                journaled = run_journal.append_sse_event(event, data)
                event_id = (journaled or {}).get("event_id") if isinstance(journaled, dict) else None
                if event_id:
                    STREAM_LAST_EVENT_ID[stream_id] = event_id
            except Exception:
                logger.debug("Failed to append JROS event %s for stream %s", event, stream_id, exc_info=True)
        if event_id and hasattr(q, "note_last_event_id"):
            try:
                q.note_last_event_id(event_id)
            except Exception:
                logger.debug("Failed to note JROS event_id %s for stream %s", event_id, stream_id, exc_info=True)
        try:
            queue_item = (event, data, event_id) if event_id and hasattr(q, "subscribe_with_snapshot") else (event, data)
            q.put_nowait(queue_item)
        except Exception:
            logger.debug("Failed to put JROS event to queue", exc_info=True)

    s = None
    usage = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}
    try:
        try:
            from api.config import get_config

            cfg = get_config()
        except Exception:
            cfg = {}
        base_url = jros_gateway_base_url(cfg)
        s = get_session(session_id)
        put_jros_event("context_status", {
            "session_id": session_id,
            "prefill": {"status": "jros", "source": "jros", "label": "JaegerAI", "message_count": 0},
        })
        update_active_run(stream_id, phase="jros-request")

        url = f"{base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **_auth_headers(),
        }
        # JaegerAI has no HTTP gateway — default to local bridge. Only try the
        # legacy HTTP gateway path when the operator has explicitly configured one.
        # Computed here (rather than just below, where the branch it guards
        # actually lives) so the Context Store retrieval right after it can
        # skip work entirely on turns that won't use `body`/`req` at all.
        explicit_gateway = bool(
            os.environ.get(_JAEGER_GATEWAY_URL_ENV)
            or os.environ.get(_LEGACY_GATEWAY_URL_ENV)
            or cfg.get("jaeger_gateway_url")
            or cfg.get("jros_gateway_url")
        )
        # ARES-owned project context (Local Profile notes, project-context
        # files) the JaegerAI gateway has no other visibility into -- NOT a
        # replacement for the gateway's own per-session context, which it
        # already keeps server-side. Only reachable on the HTTP-gateway path
        # today (the local-bridge path below has no context parameter); skip
        # the retrieval call entirely rather than doing wasted work when the
        # local-bridge branch is what's actually going to run. Degrades to an
        # empty list on any failure (disabled, sqlite-vec absent, embeddings
        # unreachable), so this can never block or fail a turn.
        context_messages: list[dict] = []
        if explicit_gateway or local_jros_root() is None:
            try:
                from api.context_store import build_context_block, retrieve as retrieve_context

                context_chunks = retrieve_context(str(msg_text or ""), config_data=cfg)
                if context_chunks:
                    context_messages = [{"role": "system", "content": build_context_block(context_chunks)}]
            except Exception:
                logger.debug("Context Store retrieval failed for jros turn %s", stream_id, exc_info=True)
        body = {
            "model": model or "jros",
            "stream": True,
            # The gateway keeps per-session context server-side; ``user`` is
            # the session key, so each WebUI conversation stays its own JROS
            # conversation.
            "user": f"webui:{session_id}",
            "messages": [*context_messages, {"role": "user", "content": str(msg_text or "")}],
        }
        # Reuse the Ares gateway SSE translators — the JROS gateway
        # deliberately speaks the same dialect.
        from api.gateway_chat import (
            _gateway_sse_delta,
            _gateway_stream_usage,
            _gateway_tool_progress_event,
        )

        final_text = ""
        turn_error = ""
        ran_locally = False
        sse_event = "message"
        resp_ctx = None

        if not explicit_gateway and local_jros_root() is not None:
            if model:
                try:
                    from api.model_catalog import sync_main_model_to_jros

                    sync_main_model_to_jros({"model": model, "provider": model_provider or "auto"})
                except Exception:
                    logger.debug("Failed to pre-sync model for local JROS turn", exc_info=True)
            ran_locally = True
            update_active_run(stream_id, phase="jros-local")
            final_text, turn_error, tool_activity = _run_local_jros_turn(
                msg_text, session_id, cancel_event, put_jros_event, stream_id
            )
            if cancel_event.is_set():
                put_jros_event("cancel", {"message": "Cancelled by user"})
                return
            for activity in tool_activity:
                if stream_id in STREAM_LIVE_TOOL_CALLS:
                    STREAM_LIVE_TOOL_CALLS[stream_id].append(
                        {"name": "jros", "args": {"activity": activity}, "done": True}
                    )
                put_jros_event("tool", {
                    "event_type": "tool.completed",
                    "name": "jros",
                    "preview": activity,
                    "is_error": False,
                })
            if final_text:
                STREAM_PARTIAL_TEXT[stream_id] = final_text
                usage["output_tokens"] = max(1, len(final_text.split()))
                put_jros_event("token", {"text": final_text})
        else:
            # Constructing Request with an empty gateway URL raises before the
            # local bridge branch can run, so HTTP objects live only here.
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                resp_ctx = urllib.request.urlopen(req, timeout=600)
            except urllib.error.URLError as exc:
                # HTTPError means the gateway IS reachable and answered with an
                # error — no fallback, let the outer handler explain it.
                if isinstance(exc, urllib.error.HTTPError):
                    raise
                if local_jros_root() is None:
                    raise
                # Gateway unreachable, but JaegerAI lives on this machine:
                # fall back to the local bridge.
                ran_locally = True
                update_active_run(stream_id, phase="jros-local")
                final_text, turn_error, tool_activity = _run_local_jros_turn(
                    msg_text, session_id, cancel_event, put_jros_event, stream_id
                )
                if cancel_event.is_set():
                    put_jros_event("cancel", {"message": "Cancelled by user"})
                    return
                for activity in tool_activity:
                    if stream_id in STREAM_LIVE_TOOL_CALLS:
                        STREAM_LIVE_TOOL_CALLS[stream_id].append(
                            {"name": "jros", "args": {"activity": activity}, "done": True}
                        )
                    put_jros_event("tool", {
                        "event_type": "tool.completed",
                        "name": "jros",
                        "preview": activity,
                        "is_error": False,
                    })
                if final_text:
                    STREAM_PARTIAL_TEXT[stream_id] = final_text
                    usage["output_tokens"] = max(1, len(final_text.split()))
                    put_jros_event("token", {"text": final_text})
                resp_ctx = None
        if resp_ctx is not None:
            with resp_ctx as resp:
                for raw_line in resp:
                    if cancel_event.is_set():
                        put_jros_event("cancel", {"message": "Cancelled by user"})
                        return
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        sse_event = "message"
                        continue
                    if line.startswith("event:"):
                        sse_event = line[6:].strip() or "message"
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if sse_event == "jros.status":
                        update_active_run(stream_id, phase="jros-running")
                        sse_event = "message"
                        continue
                    if sse_event == "jros.error":
                        turn_error = str(payload.get("message") or "JROS turn failed")
                        sse_event = "message"
                        continue
                    if sse_event == "ares.tool.progress":
                        translated = _gateway_tool_progress_event(payload)
                        if translated:
                            event_name, event_payload = translated
                            if event_name != "reasoning" and stream_id in STREAM_LIVE_TOOL_CALLS:
                                STREAM_LIVE_TOOL_CALLS[stream_id].append({
                                    "name": event_payload.get("name"),
                                    "args": event_payload.get("args") or {},
                                    "done": event_payload.get("event_type") == "tool.completed",
                                })
                            # The WebUI stream contract uses "tool" for progress rows.
                            put_jros_event("tool" if event_name in ("tool", "tool_complete") else event_name, event_payload)
                            update_active_run(stream_id, phase="jros-tool", latest_tool=event_payload.get("name"))
                        sse_event = "message"
                        continue
                    delta = _gateway_sse_delta(payload)
                    if delta:
                        final_text += delta
                        if stream_id in STREAM_PARTIAL_TEXT:
                            STREAM_PARTIAL_TEXT[stream_id] += delta
                        put_jros_event("token", {"text": delta})
                    usage.update({k: v for k, v in _gateway_stream_usage(payload).items() if v})

        if cancel_event.is_set():
            put_jros_event("cancel", {"message": "Cancelled by user"})
            return
        assistant_text = final_text.strip()
        if turn_error and not assistant_text:
            _persist_jros_failed_user_turn(
                session_id=session_id,
                stream_id=stream_id,
                user_text=_effective_user_text,
                attachments=attachments,
            )
            put_jros_event("apperror", {
                "label": "JaegerAI request failed",
                "type": "jaeger_local_error" if ran_locally else "jaeger_error",
                "message": _redact_text(turn_error)[:500],
                "hint": (
                    "ARES ran JaegerAI through the local bridge on this machine."
                    if ran_locally
                    else "ARES reached the JaegerAI gateway. Check provider config/quota if the model call failed."
                ),
            })
            return
        if not assistant_text:
            _persist_jros_failed_user_turn(
                session_id=session_id,
                stream_id=stream_id,
                user_text=_effective_user_text,
                attachments=attachments,
            )
            put_jros_event("apperror", {
                "label": "JaegerAI returned no response",
                "type": "jros_empty_response",
                "message": "JaegerAI returned no assistant message for this turn.",
                "hint": (
                    "JaegerAI ran on this machine through the local bridge but produced no reply. Check its model provider."
                    if ran_locally
                    else f"Check the JaegerAI gateway at {base_url} and its model provider."
                ),
            })
            return
        saved_session = _merge_and_save_jros_turn(
            session_id=session_id,
            stream_id=stream_id,
            msg_text=str(msg_text or ""),
            assistant_text=assistant_text,
            workspace=str(workspace),
            model=model or "",
            model_provider=model_provider,
            attachments=attachments,
            usage=usage,
            user_text=_effective_user_text,
        )
        if saved_session is None:
            return
        _run_jros_goal_hook(
            session_id=session_id,
            stream_id=stream_id,
            goal_related=goal_related,
            assistant_text=assistant_text,
            put_jros_event=put_jros_event,
        )
        from api.streaming import _session_payload_with_full_messages

        payload = _session_payload_with_full_messages(saved_session, tool_calls=[])
        put_jros_event("done", {"session": redact_session_data(payload), "usage": usage})
        put_jros_event("stream_end", {"session_id": session_id})
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        put_jros_event("apperror", _jros_http_error_event(exc, err_body))
    except urllib.error.URLError as exc:
        put_jros_event("apperror", {
            "label": "JaegerAI gateway unreachable",
            "type": "jros_gateway_offline",
            "message": _redact_text(str(exc.reason if hasattr(exc, "reason") else exc))[:500],
            "hint": _START_GATEWAY_HINT,
        })
    except Exception as exc:
        safe = _redact_text(str(exc))[:500]
        put_jros_event("apperror", {
            "label": "JaegerAI request failed",
            "type": "jros_gateway_error",
            "message": safe or "JaegerAI request failed.",
            "hint": _START_GATEWAY_HINT,
        })
    finally:
        if s is not None:
            try:
                with _get_session_agent_lock(session_id):
                    _clear_jros_pending_state(get_session(session_id), stream_id)
            except Exception:
                logger.debug("Failed to clear JROS stream state", exc_info=True)
        with STREAMS_LOCK:
            CANCEL_FLAGS.pop(stream_id, None)
            AGENT_INSTANCES.pop(stream_id, None)
            STREAM_GOAL_RELATED.pop(stream_id, None)
            STREAM_PARTIAL_TEXT.pop(stream_id, None)
            STREAM_REASONING_TEXT.pop(stream_id, None)
            STREAM_LIVE_TOOL_CALLS.pop(stream_id, None)
            STREAM_LAST_EVENT_ID.pop(stream_id, None)
            STREAMS.pop(stream_id, None)
        unregister_active_run(stream_id)


# The worker name routes.py dispatches to (kept from the old bridge).
run_jros_streaming = _run_jros_chat_streaming
