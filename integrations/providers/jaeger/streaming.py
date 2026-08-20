"""JaegerAI stdio-bridge transport for browser-originated ARES turns.

Jaeger owns execution and transcripts. ARES owns the browser stream and UI
projection. Current JaegerAI exposes the versioned NDJSON bridge; ARES does
not maintain a speculative HTTP gateway client.
"""
from __future__ import annotations

import copy
import logging
import os
import subprocess
import threading
import time
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
from api.helpers import _redact_text, _redact_value, redact_session_data
from api.models import get_session, merge_session_messages_append_only
from api.providers.jaeger.bridge_client import (
    JaegerClient,
    JaegerError,
    minimal_bridge_environment,
)
from api.providers.jaeger.paths import jaeger_home, jaeger_instance_name
from api.run_journal import RunJournalWriter

logger = logging.getLogger(__name__)


def reset_jaeger_runtime() -> None:
    """Drop cached bridge clients so the next operation boots fresh state."""
    reset_serving_model_cache()
    _reset_local_bridge_clients()


# ── bridge fallback (no gateway, JaegerAI on this machine) ──────────────────

_JAEGER_SOURCE_DIR_ENV = "ARES_JAEGER_SOURCE_DIR"
_JAEGER_INSTANCE_ENV = "ARES_JAEGER_INSTANCE"

_BOOT_LOCK = threading.RLock()
_BRIDGE_CLIENTS: dict[str, JaegerClient] = {}
_BRIDGE_TURN_LOCKS: dict[str, threading.RLock] = {}


def local_jaeger_root() -> Path | None:
    """The local JaegerAI runtime/source root for bridge execution, or None.

    Resolution order keeps explicit source checkouts first, then the installed
    Jaeger/JaegerAI runtime path. This is what the installer detects as ``~/jaeger``
    on a normal user machine, and what ``ARES_JAEGER_HOME`` / ``JAEGER_HOME``
    override for nonstandard installs.
    """
    from api.providers.jaeger.paths import is_jaeger_ai_root

    raw = str(os.environ.get(_JAEGER_SOURCE_DIR_ENV) or "").strip()
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


def _jaeger_instance_name() -> str | None:
    return str(os.environ.get(_JAEGER_INSTANCE_ENV) or "").strip() or jaeger_instance_name()


def _bridge_error_message(exc: Exception, *, auto_recovery_attempted: bool = False) -> str:
    message = _redact_text(str(exc).strip(), _enabled=True)
    lower = message.lower()
    if "lock" in lower:
        if auto_recovery_attempted:
            return (
                "JaegerAI's instance lock is held by another process, and ARES's "
                "automatic recovery (`jaeger kill`) could not clear it — a "
                "JaegerAI app/TUI is likely genuinely running elsewhere. Close it, "
                f"or use a different instance name. (Original error: {message})"
            )
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


def _is_lock_error(exc: Exception) -> bool:
    return "lock" in str(exc).lower()


def _force_clear_stale_instance_lock(instance: str | None) -> bool:
    """Best-effort ``jaeger kill --instance <name>`` to clear an orphaned lock.

    JaegerAI's own stale-lock detection correctly refuses to break a lock
    held by a genuinely-alive process — by design, since a live JaegerAI
    process could be doing real work. But ARES can leave its *own* grandchild
    bridge subprocess orphaned (e.g. a controller restart that outraced the
    bridge's graceful shutdown), and then has no way back in except a human
    running ``jaeger kill`` by hand. This scopes that exact recovery to the
    one instance ARES is trying to reach — never the no-arg/all-instances
    form, so it can't touch a JaegerAI the operator is genuinely running
    under a different instance name.

    Never raises: this is a best-effort recovery step, not the primary path.
    A failure here just means the caller's retry will fail with the original
    error, which is the same outcome as not attempting recovery at all.
    """
    if not instance:
        return False
    root = local_jaeger_root()
    if root is None:
        return False
    launcher = root / "jaeger"
    if not launcher.exists():
        return False
    try:
        result = subprocess.run(
            [str(launcher), "kill", "--instance", instance],
            env=minimal_bridge_environment(),
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception:
        logger.warning("jaeger kill --instance %s failed to run", instance, exc_info=True)
        return False
    if result.returncode != 0:
        logger.warning(
            "jaeger kill --instance %s exited %s: %s",
            instance, result.returncode, result.stderr.decode("utf-8", "replace")[:500],
        )
        return False
    return True


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


def _evict_bridge_client(key: str, client: JaegerClient | None) -> None:
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
        logger.debug("Failed to close errored JaegerAI bridge", exc_info=True)


def _client_is_alive(client: JaegerClient) -> bool:
    check = getattr(client, "is_alive", None)
    if check is None:
        return True
    try:
        return bool(check())
    except Exception:
        return False


def _get_or_start_bridge_client(instance: str | None = None) -> JaegerClient:
    """Start and cache one ``jaeger bridge`` client per JaegerAI instance.

    The bridge launcher uses JaegerAI's own venv interpreter, so ARES never imports
    native JaegerAI ML packages into the WebUI venv.
    """
    resolved_instance = instance or _jaeger_instance_name() or None
    key = resolved_instance or "__default__"
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
                logger.debug("Failed to close dead JaegerAI bridge", exc_info=True)
        root = local_jaeger_root()
        if root is None:
            raise JaegerError(
                "No local JaegerAI runtime was found. Install JaegerAI, set "
                "ARES_JAEGER_HOME/JAEGER_HOME to that installation, or set the "
                "legacy ARES_JaegerAI_DIR override to a validated JaegerAI source "
                "checkout."
            )
        client = JaegerClient(jaeger_home=str(root), instance=resolved_instance)
        try:
            client.start()
        except Exception as exc:
            client.close()
            if _is_lock_error(exc) and _force_clear_stale_instance_lock(resolved_instance):
                # The lock was held by a dead/orphaned process (jaeger kill
                # exited 0 — it either killed something or found nothing to
                # kill, and either way swept the stale lock file). Retry once
                # against a fresh client rather than surfacing an error a
                # human would otherwise have to clear by hand.
                retry_client = JaegerClient(jaeger_home=str(root), instance=resolved_instance)
                try:
                    retry_client.start()
                except Exception as retry_exc:
                    retry_client.close()
                    raise JaegerError(
                        _bridge_error_message(retry_exc, auto_recovery_attempted=True)
                    ) from retry_exc
                _BRIDGE_CLIENTS[key] = retry_client
                _BRIDGE_TURN_LOCKS.setdefault(key, threading.RLock())
                return retry_client
            raise JaegerError(_bridge_error_message(exc)) from exc
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
    instance = _jaeger_instance_name()
    client = _get_or_start_bridge_client(instance)
    return client.query(what, args or {})


def local_integration_contract() -> dict[str, Any]:
    """Negotiate and validate the selected Jaeger runtime's feature contract."""
    instance = _jaeger_instance_name()
    client = _get_or_start_bridge_client(instance)
    return client.integration_contract()


def command_local_companion(cmd: str, args: dict[str, Any] | None = None) -> Any:
    """Ask JaegerAI to mutate its selected Companion through its bridge."""
    instance = _jaeger_instance_name()
    client = _get_or_start_bridge_client(instance)
    return client.command(cmd, args or {})


# Text already delivered to the client as ``delta`` frames, per stream.
# The final ``reply`` is still the authoritative answer — this only says
# how much of it the user has already seen, so the end of the turn can
# send the remainder instead of the whole thing again.
STREAM_DELTA_TEXT: dict[str, str] = {}


def _delta_remainder(stream_id: str, final_text: str) -> str:
    """What still needs sending once the authoritative reply arrives.

    Three cases, and only the first is the happy path:

      * the final text CONTINUES what was streamed → send the tail;
      * nothing was streamed (older runtime, or a turn that produced no
        deltas) → send everything, exactly as before this existed;
      * the final text DIVERGES from the stream → send nothing. The
        persona output filter re-voices the finished answer, and the
        agent loop streams intermediate narration between tool calls, so
        divergence is normal rather than exceptional. Appending the final
        text on top of a diverged stream would show the answer twice;
        the ``done`` event settles the transcript from the saved session
        moments later, which is the correct text either way.
    """
    streamed = STREAM_DELTA_TEXT.get(stream_id, "")
    if not streamed:
        return final_text
    if final_text.startswith(streamed):
        return final_text[len(streamed):]
    return ""


def _translate_bridge_frame(frame: dict[str, Any], put_jaeger_event, stream_id: str) -> None:
    frame = _redact_value(frame, _enabled=True)
    kind = str(frame.get("type") or "").strip().lower()
    if kind == "tool":
        name = str(frame.get("name") or frame.get("tool") or "jaeger").strip() or "jaeger"
        status = str(
            frame.get("status")
            or frame.get("phase")
            or frame.get("event")
            or frame.get("state")
            or ""
        ).strip().lower()
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
            calls = STREAM_LIVE_TOOL_CALLS[stream_id]
            done = payload["event_type"] != "tool.running"
            # Jaeger emits start/done as separate frames. Fold the terminal
            # frame into the most recent matching call so structured path args
            # from the start frame survive in the persisted session artifact.
            pending = next(
                (
                    call
                    for call in reversed(calls)
                    if call.get("name") == name and not call.get("done")
                ),
                None,
            )
            if done and pending is not None:
                pending["done"] = True
                if isinstance(payload.get("args"), dict):
                    pending["args"] = payload["args"]
            else:
                calls.append({
                    "name": name,
                    "args": payload.get("args") or {"preview": preview},
                    "done": done,
                })
        put_jaeger_event("tool", payload)
        return
    if kind == "delta":
        # The turn's text, live. The WebUI's ``token`` handler APPENDS
        # (``assistantText += d.text``), which is exactly the shape a
        # delta has — so the frame maps straight onto the event the
        # front-end has always understood. What is streamed is tracked so
        # the final reply can be reconciled against it instead of
        # rendering the same prose twice.
        piece = str(frame.get("text") or "")
        if piece:
            STREAM_DELTA_TEXT[stream_id] = STREAM_DELTA_TEXT.get(stream_id, "") + piece
            put_jaeger_event("token", {"text": piece})
        return
    if kind == "state":
        # Busy/idle/thinking are transport lifecycle, not model reasoning.
        # Mapping them onto runtime `reasoning` events made the original
        # chat thinking-card flicker every turn. Drop them; the WebUI
        # already has busy/stream state from send() / SSE.
        return


class _JaegerBridgeTurnControl:
    """Expose Jaeger's live bridge controls through ARES's existing registry."""

    def __init__(self, client: JaegerClient, session_id: str) -> None:
        self._client = client
        self.session_id = session_id
        from api.session_contract import shared_session_id

        self._bridge_session = shared_session_id(session_id)

    def interrupt(self, _reason: str = "") -> None:
        self._client.cancel(self._bridge_session)

    def steer(self, text: str) -> bool:
        if not str(text or "").strip() or not self._client.is_alive():
            return False
        self._client.steer(text, self._bridge_session)
        return True


def _run_local_jaeger_turn(
    msg_text: str,
    session_id: str,
    workspace: str,
    cancel_event: threading.Event,
    put_jaeger_event=None,
    stream_id: str = "",
    display_text: str = "",
) -> tuple[str, str, list[str]]:
    """One local JaegerAI bridge turn. Returns (text, error, tool_activity)."""
    instance = _jaeger_instance_name()
    key = instance or "__default__"
    last_exc: Exception | None = None
    for attempt in (1, 2):
        client: JaegerClient | None = None
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

            def on_event(
                frame: dict[str, Any],
                activity: list[str] = tool_activity,
            ) -> None:
                if cancel_event.is_set():
                    return
                if isinstance(frame, dict):
                    frame = _redact_value(frame, _enabled=True)
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
                        activity.append(preview)
                    if put_jaeger_event is not None:
                        _translate_bridge_frame(frame, put_jaeger_event, stream_id)

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
                from api.session_contract import shared_session_id

                turn_kwargs = {
                    "session": shared_session_id(session_id),
                    "workspace": str(workspace or ""),
                    "on_event": on_event,
                    "on_request": _on_request,
                }
                if display_text and display_text != str(msg_text or ""):
                    turn_kwargs["display_text"] = display_text
                result = client.turn(str(msg_text or ""), **turn_kwargs)
            payload = dict(result or {}) if isinstance(result, dict) else {}
            error = _redact_text(str(payload.get("error") or "").strip(), _enabled=True)
            text = str(payload.get("text") or "").strip()
            return text, error, [] if put_jaeger_event is not None else tool_activity
        except Exception as exc:
            last_exc = exc
            _evict_bridge_client(key, client)
            if attempt == 1 and _is_dead_bridge_error(exc):
                logger.warning(
                    "Local JaegerAI bridge died; retrying with a fresh process: %s",
                    exc,
                )
                continue
            logger.warning("Local JaegerAI bridge turn failed: %s", _bridge_error_message(exc))
            return "", _bridge_error_message(exc), []
    return "", _bridge_error_message(last_exc or JaegerError("bridge failed")), []


def _stream_writeback_is_current(session: Any, stream_id: str) -> bool:
    return bool(stream_id and getattr(session, "active_stream_id", None) == stream_id)


def _clear_jaeger_pending_state(session: Any, stream_id: str) -> None:
    if not _stream_writeback_is_current(session, stream_id):
        return
    session.active_stream_id = None
    session.pending_user_message = None
    session.pending_attachments = None
    session.pending_started_at = None
    session.pending_user_source = None
    session.save()


def _persist_jaeger_failed_user_turn(
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


def _merge_and_save_jaeger_turn(
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
            "backend": "jaeger",
        }
        live_tool_calls = list(STREAM_LIVE_TOOL_CALLS.get(stream_id, []) or [])
        if live_tool_calls:
            # Preserve Jaeger's structured, path-only mutation metadata so the
            # ARES Artifacts tab can render files created during this turn.
            assistant_msg["tool_calls"] = live_tool_calls
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
            logger.debug("Failed to filter JaegerAI display context markers", exc_info=True)
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
                    msg["backend"] = "jaeger"
                    if selected_model_provider:
                        msg["model_provider"] = selected_model_provider
                    break
        except Exception:
            logger.debug("Failed to merge JaegerAI display transcript", exc_info=True)
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
                logger.debug("Could not record jaeger serving-model routing", exc_info=True)

        # Persist the serving model's real context window so the WebUI ring
        # has something true to draw. Without this the jaeger path never wrote
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
                "Could not resolve a context window for jaeger session %s",
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
        # Phase 2 ownership boundary: return a live display projection to the
        # current SSE request, but persist only ARES-owned UI metadata. Jaeger
        # already committed the authoritative transcript synchronously before
        # the bridge reply returned.
        display_session = copy.copy(s)
        display_session.messages = list(s.messages or [])
        display_session.context_messages = list(s.context_messages or [])
        display_session.tool_calls = list(s.tool_calls or [])
        s.transcript_owner = "jaeger"
        s.runtime_message_count = len(display_session.messages)
        s.messages = []
        s.context_messages = []
        s.tool_calls = []
        s.save()
        try:
            s.path.with_suffix(".json.bak").unlink(missing_ok=True)
        except Exception:
            logger.debug("Could not prune legacy transcript backup for %s", session_id)
        try:
            from api.models import delete_cli_session

            delete_cli_session(session_id)
        except Exception:
            logger.debug("Could not prune legacy state transcript for %s", session_id)
        return display_session


def _run_jaeger_goal_hook(*, session_id: str, stream_id: str, goal_related: bool, assistant_text: str, put_jaeger_event) -> None:
    try:
        from api.goals import evaluate_goal_after_turn, has_active_goal
        from api.profiles import get_ares_home_for_profile

        s = get_session(session_id)
        profile_home = get_ares_home_for_profile(str(getattr(s, "profile", None) or "default"))
        if goal_related and has_active_goal(session_id, profile_home=profile_home):
            put_jaeger_event("goal", {
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
                put_jaeger_event("goal", {
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
                    put_jaeger_event("goal_continue", {
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


def run_jaeger_streaming(
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
    """Run one browser turn through Jaeger's versioned local bridge."""
    visible_user_text = next(
        (str(value) for value in (user_text, original_message) if value is not None),
        str(msg_text or ""),
    )
    queue = STREAMS.get(stream_id)
    if queue is None:
        unregister_stream_owner(stream_id)
        return

    register_active_run(
        stream_id,
        session_id=session_id,
        started_at=time.time(),
        phase="jaeger-starting",
        workspace=str(workspace),
        model=model or "",
        provider=model_provider or None,
        backend="jaeger",
    )
    try:
        run_journal = RunJournalWriter(session_id, stream_id)
    except Exception:
        run_journal = None
        logger.debug("Failed to initialize Jaeger run journal for %s", stream_id, exc_info=True)

    cancel_event = threading.Event()
    with STREAMS_LOCK:
        CANCEL_FLAGS[stream_id] = cancel_event
        STREAM_PARTIAL_TEXT[stream_id] = ""
        STREAM_REASONING_TEXT[stream_id] = ""
        STREAM_LIVE_TOOL_CALLS[stream_id] = []

    def put_event(event: str, data: Any) -> None:
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
                logger.debug("Failed to journal Jaeger event %s", event, exc_info=True)
        if event_id and hasattr(queue, "note_last_event_id"):
            queue.note_last_event_id(event_id)
        item = (event, data, event_id) if event_id and hasattr(queue, "subscribe_with_snapshot") else (event, data)
        queue.put_nowait(item)

    session = None
    usage = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}
    try:
        session = get_session(session_id)
        put_event("context_status", {
            "session_id": session_id,
            "prefill": {"status": "jaeger", "source": "jaeger", "label": "JaegerAI", "message_count": 0},
        })
        update_active_run(stream_id, phase="jaeger-local")
        text, error, tool_activity = _run_local_jaeger_turn(
            msg_text,
            session_id,
            str(workspace),
            cancel_event,
            put_event,
            stream_id,
            display_text=visible_user_text,
        )
        if cancel_event.is_set():
            put_event("cancel", {"message": "Cancelled by user"})
            return
        for activity in tool_activity:
            STREAM_LIVE_TOOL_CALLS[stream_id].append(
                {"name": "jaeger", "args": {"activity": activity}, "done": True}
            )
            put_event("tool", {
                "event_type": "tool.completed", "name": "jaeger",
                "preview": activity, "is_error": False,
            })
        assistant_text = text.strip()
        if error and not assistant_text:
            _persist_jaeger_failed_user_turn(
                session_id=session_id, stream_id=stream_id,
                user_text=visible_user_text, attachments=attachments,
            )
            put_event("apperror", {
                "label": "JaegerAI request failed",
                "type": "jaeger_local_error",
                "message": _redact_text(error)[:500],
                "hint": "ARES reached JaegerAI through its local bridge.",
            })
            return
        if not assistant_text:
            _persist_jaeger_failed_user_turn(
                session_id=session_id, stream_id=stream_id,
                user_text=visible_user_text, attachments=attachments,
            )
            put_event("apperror", {
                "label": "JaegerAI returned no response",
                "type": "jaeger_empty_response",
                "message": "JaegerAI returned no assistant message for this turn.",
                "hint": "Check the selected JaegerAI model provider.",
            })
            return
        STREAM_PARTIAL_TEXT[stream_id] = assistant_text
        usage["output_tokens"] = max(1, len(assistant_text.split()))
        remainder = _delta_remainder(stream_id, assistant_text)
        if remainder:
            put_event("token", {"text": remainder})
        saved_session = _merge_and_save_jaeger_turn(
            session_id=session_id, stream_id=stream_id, msg_text=str(msg_text or ""),
            assistant_text=assistant_text, workspace=str(workspace), model=model or "",
            model_provider=model_provider, attachments=attachments, usage=usage,
            user_text=visible_user_text,
        )
        if saved_session is None:
            return
        _run_jaeger_goal_hook(
            session_id=session_id, stream_id=stream_id, goal_related=goal_related,
            assistant_text=assistant_text, put_jaeger_event=put_event,
        )
        from api.streaming import _session_payload_with_full_messages

        payload = _session_payload_with_full_messages(saved_session, tool_calls=[])
        put_event("done", {"session": redact_session_data(payload), "usage": usage})
        put_event("stream_end", {"session_id": session_id})
    except Exception as exc:
        put_event("apperror", {
            "label": "JaegerAI request failed",
            "type": "jaeger_bridge_error",
            "message": _redact_text(str(exc))[:500] or "JaegerAI request failed.",
            "hint": "Check the JaegerAI bridge and selected instance.",
        })
    finally:
        if session is not None:
            try:
                with _get_session_agent_lock(session_id):
                    _clear_jaeger_pending_state(get_session(session_id), stream_id)
            except Exception:
                logger.debug("Failed to clear Jaeger stream state", exc_info=True)
        with STREAMS_LOCK:
            CANCEL_FLAGS.pop(stream_id, None)
            AGENT_INSTANCES.pop(stream_id, None)
            STREAM_GOAL_RELATED.pop(stream_id, None)
            STREAM_PARTIAL_TEXT.pop(stream_id, None)
            STREAM_DELTA_TEXT.pop(stream_id, None)
            STREAM_REASONING_TEXT.pop(stream_id, None)
            STREAM_LIVE_TOOL_CALLS.pop(stream_id, None)
            STREAM_LAST_EVENT_ID.pop(stream_id, None)
            STREAMS.pop(stream_id, None)
        unregister_active_run(stream_id)
