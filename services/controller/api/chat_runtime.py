"""Framework-neutral chat-run creation for HTTP and background callers.

This module owns the short transaction that prepares a session, registers its
established ARES stream channel, and starts the selected framework worker. It
does not own model generation: connected runtimes publish through
``api.config.StreamChannel`` and the run journal.
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
import uuid
from typing import Any

from api.config import (
    ACTIVE_RUNS,
    ACTIVE_RUNS_LOCK,
    PENDING_BG_TASK_COMPLETIONS,
    PENDING_GOAL_CONTINUATION,
    STREAMS,
    STREAMS_LOCK,
    STREAM_GOAL_RELATED,
    _get_session_agent_lock,
    create_stream_channel,
    get_config,
    get_effective_default_model,
    get_webui_session_save_mode,
    register_stream_owner,
    unregister_stream_owner,
)
from api.models import get_session, title_from
from api.session_events import publish_session_list_changed
from api.workspace import get_last_workspace, resolve_trusted_workspace, set_last_workspace


logger = logging.getLogger(__name__)


# Ordered fallback workers used when the session's selected runtime is missing
# from the registry. Jaeger is the primary assistant backend and is preferred
# over cloud workers so a local-first install stays local.
# Every entry must be a real key in ``integrations/workers/router.py``.
# The same typed-user-text value is passed under every spelling the stream
# targets have grown. `_filter_kwargs_for_callable` keeps whichever a given
# target declares and drops the rest without complaint.
USER_TEXT_ALIASES = frozenset({"user_text", "original_message", "user_message"})


FALLBACK_BACKEND_IDS = (
    "jaeger_local",
    "ollama_local",
    "claude_local",
    "codex_local",
)


def resolve_backend_execution_model(
    backend: Any,
    model: str,
    provider: str | None,
) -> tuple[str, str | None]:
    """Keep a model selection inside the selected framework's catalog.

    A session can retain an unrelated model when its framework changes. A
    CLI must never receive that unrelated identifier. Prefer the backend's
    active catalog entry; an empty catalog leaves the requested state alone.
    """
    inventory_fn = getattr(backend, "inventory", None)
    if not callable(inventory_fn):
        return model, provider
    try:
        inventory = inventory_fn()
    except Exception:
        logger.debug("Could not inspect model catalog for %s", getattr(backend, "name", "unknown"), exc_info=True)
        return model, provider
    if not isinstance(inventory, dict):
        return model, provider
    models = [item for item in inventory.get("models") or [] if isinstance(item, dict)]
    known = {str(item.get("id") or "").strip() for item in models}
    known.discard("")
    if not known or model in known:
        return model, provider
    selected = next((item for item in models if item.get("in_use")), models[0])
    selected_model = str(selected.get("id") or "").strip()
    selected_provider = str(selected.get("provider") or "").strip() or None
    logger.info(
        "Replaced incompatible model %s with %s for backend %s",
        model,
        selected_model,
        getattr(backend, "name", "unknown"),
    )
    return selected_model, selected_provider


def normalize_chat_attachments(raw_attachments) -> list[dict[str, Any]]:
    """Normalize legacy filenames and structured browser upload results."""

    if not isinstance(raw_attachments, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_attachments:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("filename") or "").strip()
            path = str(item.get("path") or "").strip()
            attachment: dict[str, Any] = {
                "name": name or path,
                "path": path,
                "mime": str(item.get("mime") or "").strip(),
            }
            if isinstance(item.get("size"), int):
                attachment["size"] = item["size"]
            if isinstance(item.get("is_image"), bool):
                attachment["is_image"] = item["is_image"]
            normalized.append(attachment)
        else:
            value = str(item).strip()
            if value:
                normalized.append({"name": value, "path": "", "mime": ""})
    return normalized


_normalize_chat_attachments = normalize_chat_attachments


def resolve_chat_workspace_with_recovery(session: Any, requested_workspace) -> str:
    """Repair a stale implicit workspace while preserving explicit errors."""
    explicit = requested_workspace not in (None, "")
    candidate = requested_workspace if explicit else getattr(session, "workspace", None)
    try:
        return str(resolve_trusted_workspace(candidate))
    except ValueError:
        if explicit:
            raise
    fallback = str(resolve_trusted_workspace(get_last_workspace()))
    session.workspace = fallback
    try:
        session.save()
    except Exception:
        pass
    return fallback


_resolve_chat_workspace_with_recovery = resolve_chat_workspace_with_recovery


def _active_run_for_session(session_id: str) -> str | None:
    """Return a currently registered worker for ``session_id``."""
    with ACTIVE_RUNS_LOCK:
        for key, value in list((ACTIVE_RUNS or {}).items()):
            record = value if isinstance(value, dict) else {}
            if str(record.get("session_id") or "") == session_id:
                return str(record.get("stream_id") or key or "") or None
    return None


def _stream_is_active(stream_id: str | None) -> bool:
    if not stream_id:
        return False
    with STREAMS_LOCK:
        if stream_id in STREAMS:
            return True
    with ACTIVE_RUNS_LOCK:
        return stream_id in (ACTIVE_RUNS or {})


# stream_id -> the worker thread running it. Registry membership answers "did
# something claim this stream"; the thread answers "is anything still running
# it". The difference matters on the double-send path: a worker that died
# without unregistering leaves the session pinned behind an id nothing owns.
_WORKER_THREADS: dict[str, threading.Thread] = {}
_WORKER_THREADS_LOCK = threading.Lock()


def _thread_has_exited(thread: Any) -> bool | None:
    """``True``/``False`` for a real thread, ``None`` when it cannot be asked.

    Tests (and any future non-``Thread`` runner) substitute objects with no
    ``is_alive``. Those are *unknown*, never dead — guessing "dead" here would
    reclaim sessions that are actually mid-turn.
    """
    probe = getattr(thread, "is_alive", None)
    if not callable(probe):
        return None
    try:
        return not probe()
    except Exception:
        return None


def _register_worker_thread(stream_id: str, thread: Any) -> None:
    with _WORKER_THREADS_LOCK:
        for known, known_thread in list(_WORKER_THREADS.items()):
            if _thread_has_exited(known_thread) is True:
                _WORKER_THREADS.pop(known, None)
        _WORKER_THREADS[stream_id] = thread


def _forget_worker_thread(stream_id: str) -> None:
    with _WORKER_THREADS_LOCK:
        _WORKER_THREADS.pop(stream_id, None)


def _busy_session_response(active_stream_id: str) -> dict[str, Any]:
    """409 for a conversation that is genuinely mid-turn.

    ``retry`` tells the client this is a wait-and-resend condition rather than a
    rejected message, so a double-tap does not look like the send was lost.
    """
    return {
        "error": "This conversation is already generating a reply.",
        "reason": "A turn started earlier on this session has not finished yet.",
        "fix": "Wait for the current reply to finish, or press Stop, then send again.",
        "active_stream_id": active_stream_id,
        "retry": True,
        "_status": 409,
    }


def _worker_thread_is_dead(stream_id: str | None) -> bool:
    """True only when a thread was recorded for ``stream_id`` and has exited.

    Deliberately not "no thread recorded": a stream this process did not start
    (after a restart, or from another worker path) is unknown, not dead, and
    must not be reclaimed on that basis.
    """
    if not stream_id:
        return False
    with _WORKER_THREADS_LOCK:
        thread = _WORKER_THREADS.get(stream_id)
    if thread is None:
        return False
    return _thread_has_exited(thread) is True


def _clear_stale_pending_locked(session: Any, stream_id: str) -> bool:
    """Clear a dead pending run while the canonical session lock is held."""
    if _stream_is_active(stream_id):
        return False
    pending_started_at = getattr(session, "pending_started_at", None)
    try:
        pending_age = time.time() - float(pending_started_at) if pending_started_at else None
    except (TypeError, ValueError):
        pending_age = None
    try:
        from api.models import _REPAIR_STALE_PENDING_GRACE_SECONDS

        grace = float(_REPAIR_STALE_PENDING_GRACE_SECONDS)
    except Exception:
        grace = 30.0
    # The grace window protects a worker that has started but not yet
    # registered. A thread we recorded and watched exit is not that case, so
    # confirmed death overrides the wait — otherwise a send that died instantly
    # locks the conversation for the full grace period.
    if (
        getattr(session, "pending_user_message", None)
        and pending_age is not None
        and pending_age < grace
        and not _worker_thread_is_dead(stream_id)
    ):
        return False

    try:
        from api.streaming import _materialize_pending_user_turn_before_error

        _materialize_pending_user_turn_before_error(session)
    except Exception:
        logger.exception("Could not materialize stale pending turn for %s", session.session_id)
        return False

    session.active_stream_id = None
    session.pending_user_message = None
    session.pending_attachments = []
    session.pending_started_at = None
    session.pending_user_source = None
    session.save(touch_updated_at=False)
    unregister_stream_owner(stream_id)
    return True


def _checkpoint_eager_user_message(
    session: Any,
    message: str,
    attachments: list[dict[str, Any]],
    started_at: float,
    source: str,
) -> None:
    existing = list(getattr(session, "messages", None) or [])
    if existing:
        latest = existing[-1]
        if isinstance(latest, dict) and latest.get("role") == "user":
            if " ".join(str(latest.get("content") or "").split()) == " ".join(message.split()):
                return
    row: dict[str, Any] = {
        "role": "user",
        "content": message,
        "timestamp": int(started_at),
    }
    if source != "webui":
        row["_source"] = source
    if attachments:
        row["attachments"] = list(attachments)
    session.messages.append(row)
    if getattr(session, "truncation_watermark", None):
        session.truncation_watermark = row["timestamp"] or time.time()


def checkpoint_user_message_for_eager_session_save(
    session: Any,
    msg: str,
    attachments,
    started_at: float | None,
    source: str = "webui",
) -> None:
    """Persist an eager user checkpoint without depending on HTTP transport."""
    if not msg:
        return
    existing = list(getattr(session, "messages", None) or [])
    if existing:
        latest = existing[-1]
        if isinstance(latest, dict) and latest.get("role") == "user":
            latest_text = " ".join(str(latest.get("content") or "").split())
            if latest_text == " ".join(str(msg).split()):
                return
    row: dict[str, Any] = {"role": "user", "content": msg}
    if source and source != "webui":
        row["_source"] = source
    if isinstance(started_at, (int, float)) and started_at > 0:
        row["timestamp"] = int(started_at)
    if attachments:
        row["attachments"] = list(attachments)
    session.messages.append(row)
    if getattr(session, "truncation_watermark", None):
        session.truncation_watermark = row.get("timestamp") or time.time()


_checkpoint_user_message_for_eager_session_save = checkpoint_user_message_for_eager_session_save


def prepare_chat_start_session_for_stream(
    session: Any,
    *,
    msg: str,
    attachments,
    workspace: str,
    model: str,
    model_provider,
    stream_id: str,
    started_at: float | None = None,
    source: str = "webui",
):
    """Persist pending chat state using the configured eager/deferred mode."""
    del started_at
    _prepare_session_locked(
        session,
        stream_id=stream_id,
        message=msg,
        attachments=list(attachments or []),
        workspace=workspace,
        model=model,
        provider=model_provider,
        source=source,
    )
    return session


_prepare_chat_start_session_for_stream = prepare_chat_start_session_for_stream


def _prepare_session_locked(
    session: Any,
    *,
    stream_id: str,
    message: str,
    attachments: list[dict[str, Any]],
    workspace: str,
    model: str,
    provider: str | None,
    source: str,
) -> tuple[bool, float]:
    was_hidden = (
        getattr(session, "title", "Untitled") == "Untitled"
        and not getattr(session, "messages", None)
        and not getattr(session, "active_stream_id", None)
        and not getattr(session, "pending_user_message", None)
    )
    started_at = time.time()
    session.workspace = workspace
    session.model = model
    session.model_provider = provider
    session.active_stream_id = stream_id
    session.post_compression_context_tokens_estimate = None
    session.pending_user_message = message
    session.pending_attachments = attachments
    session.pending_started_at = started_at
    session.pending_user_source = source
    if str(getattr(session, "title", "") or "").strip() in {"", "Untitled", "New Chat"}:
        session.title = title_from([{"role": "user", "content": message}], "Untitled")
    if get_webui_session_save_mode() == "eager":
        _checkpoint_eager_user_message(session, message, attachments, started_at, source)
    session.save()
    return was_hidden, started_at


def _backend_for_session(session: Any):
    from api.backend_selector import get_session_backend
    from api.backends.router import get_router

    selected = get_session_backend(session, get_config())
    router = get_router()
    backend = router.backends.get(selected)
    if backend:
        return backend
    # Try fallback chain: if the selected backend is unavailable, try
    # alternatives in order. This makes the system resilient to single
    # backend failures.
    #
    # Every id here MUST be a real key of ``integrations/workers/router.py``'s
    # registry. Ids that match nothing are silently skipped by ``.get()``, which
    # previously let a missing worker slide onto Ollama with no
    # signal to the user — a different brain answering behind the same UI.
    # ``tests/test_worker_invoke_contract.py`` pins the list against the registry.
    for name in FALLBACK_BACKEND_IDS:
        fb = router.backends.get(name)
        if fb is None:
            continue
        available = getattr(fb, "is_available", None)
        if callable(available):
            try:
                if not available():
                    continue
            except Exception:
                logger.debug("Availability probe failed for fallback %s", name, exc_info=True)
                continue
        logger.warning(
            "Runtime connection %s unavailable; falling back to %s for session %s",
            selected,
            name,
            session.session_id[:8],
        )
        return fb
    raise ValueError(f"Runtime connection unavailable: {selected} (and no fallbacks available)")


def _filter_kwargs_for_callable(target: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop keyword arguments ``target`` cannot accept.

    Stream targets are invoked by convention across four modules whose
    signatures drift independently. Passing an unknown keyword raises TypeError
    *inside* the worker thread, where ``Thread.start()`` has already returned
    success — the caller reports HTTP 200 with a live ``stream_id`` while the
    thread is already dead, so the UI waits on a stream that will never emit.
    Filtering at this seam keeps a signature change in one worker from silently
    killing turns on every other worker.
    """
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        # Builtins and C callables have no introspectable signature; the caller
        # is better served by attempting the call than by dropping everything.
        return dict(kwargs)

    parameters = signature.parameters.values()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
        return dict(kwargs)

    accepted = {
        p.name
        for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    allowed = {key: value for key, value in kwargs.items() if key in accepted}
    dropped = sorted(set(kwargs) - set(allowed))
    if dropped:
        # The user-text aliases are expected to be partially dropped on every
        # turn — each target declares only the spelling it uses — so they are
        # debug noise, not a signal. Anything else means real signature drift.
        unexpected = [key for key in dropped if key not in USER_TEXT_ALIASES]
        log = logger.warning if unexpected else logger.debug
        log(
            "Dropped %d kwarg(s) %s not accepted by worker target %s",
            len(dropped),
            dropped,
            getattr(target, "__qualname__", repr(target)),
        )
    return allowed


def _publish_worker_boot_error(stream_id: str, session_id: str, exc: BaseException) -> None:
    """Surface a worker that died before it could emit anything.

    Without this the stream stays open and empty forever: there is no stall
    watchdog, so a thread that dies during boot leaves the conversation
    wedged behind its own ``active_stream_id``.
    """
    message = f"The assistant runtime failed to start: {exc}"
    error_payload = {
        "type": "worker_boot_failed",
        "message": message,
        "reason": f"{type(exc).__name__}: {exc}",
        "fix": (
            "Send the message again. If it keeps failing, switch runtime on the "
            "Connections page, or check the controller log at ~/.ares/webui.log"
        ),
    }
    channel = None
    with STREAMS_LOCK:
        channel = STREAMS.get(stream_id)
    if channel is not None:
        for event, payload in (
            ("error", error_payload),
            ("stream_end", {"stream_id": stream_id}),
        ):
            try:
                channel.put_nowait((event, payload))
            except Exception:
                logger.debug("Failed to publish %s for stream %s", event, stream_id, exc_info=True)

    with STREAMS_LOCK:
        STREAMS.pop(stream_id, None)
    _forget_worker_thread(stream_id)
    try:
        from api.streaming import unregister_active_run

        unregister_active_run(stream_id)
    except Exception:
        logger.debug("Failed to unregister active run %s", stream_id, exc_info=True)
    unregister_stream_owner(stream_id)

    # Release the session so the next message is accepted instead of being
    # rejected with "session already has an active stream".
    try:
        with _get_session_agent_lock(session_id):
            session = get_session(session_id, metadata_only=False)
            if str(getattr(session, "active_stream_id", "") or "") == stream_id:
                session.active_stream_id = None
                session.pending_user_message = None
                session.pending_attachments = []
                session.pending_started_at = None
                session.pending_user_source = None
                session.save(touch_updated_at=False)
    except Exception:
        logger.debug("Failed to clear pending state for session %s", session_id, exc_info=True)


def start_session_turn(
    session_id: str,
    message: str,
    *,
    source: str = "process_wakeup",
    backend: Any | None = None,
    workspace: str | None = None,
    model: str | None = None,
    model_provider: str | None = None,
    explicit_model_pick: bool | None = None,
    attachments: list[dict[str, Any]] | None = None,
    _skip_wakeup_policy: bool = False,
) -> dict[str, Any]:
    """Start a runtime worker without importing the legacy HTTP dispatcher.

    FastAPI adapters execute this synchronous transaction with
    ``asyncio.to_thread`` so filesystem work and runtime checks do not block the
    event loop. Background wakeups can call it directly from their worker.
    """
    clean_message = str(message or "").strip()
    if not clean_message:
        return {"error": "message is required", "_status": 400}
    if source == "process_wakeup" and not _skip_wakeup_policy:
        from api.process_wakeup import start_session_turn as start_process_wakeup

        return start_process_wakeup(session_id, clean_message, source=source)
    try:
        session = get_session(str(session_id or "").strip(), metadata_only=False)
    except KeyError:
        return {"error": "Session not found", "_status": 404}

    cfg = get_config()
    model_cfg = cfg.get("model") if isinstance(cfg, dict) else {}
    model_cfg = model_cfg if isinstance(model_cfg, dict) else {}
    requested_model = str(
        model
        or getattr(session, "model", None)
        or get_effective_default_model(cfg)
        or ""
    ).strip()
    requested_provider = str(
        model_provider
        or getattr(session, "model_provider", None)
        or model_cfg.get("provider")
        or ""
    ).strip() or None
    from api.model_resolution import resolve_chat_model_state

    effective_model, effective_provider = resolve_chat_model_state(
        session,
        requested_model or None,
        requested_provider,
        # ``model`` is set on almost every webui send (it's the session's
        # current model, not just deliberate picks), so deriving explicitness
        # from bool(model) would treat every send as explicit. Callers that
        # know the operator's real intent (the webui request body) pass it;
        # everyone else keeps the bool(model) fallback used before this had a
        # dedicated signal.
        explicit_model_pick=bool(model) if explicit_model_pick is None else explicit_model_pick,
        prefer_cached_catalog=source != "webui",
    )
    try:
        effective_workspace = resolve_chat_workspace_with_recovery(session, workspace)
    except ValueError as exc:
        return {"error": str(exc), "_status": 400}

    try:
        selected_backend = backend or _backend_for_session(session)
    except ValueError as exc:
        return {"error": str(exc), "_status": 400}
    effective_model, effective_provider = resolve_backend_execution_model(
        selected_backend,
        effective_model,
        effective_provider,
    )

    session_lock = _get_session_agent_lock(session.session_id)
    with session_lock:
        try:
            session = get_session(session.session_id, metadata_only=False)
        except KeyError:
            return {"error": "Session not found", "_status": 404}
        current_stream_id = str(getattr(session, "active_stream_id", None) or "")
        cleared_stream_id: str | None = None
        if current_stream_id:
            if (
                _stream_is_active(current_stream_id)
                or not _clear_stale_pending_locked(session, current_stream_id)
            ):
                return _busy_session_response(current_stream_id)
            cleared_stream_id = current_stream_id
            _forget_worker_thread(current_stream_id)
        active_run = _active_run_for_session(session.session_id)
        if active_run:
            return _busy_session_response(active_run)
        stream_id = uuid.uuid4().hex
        was_hidden, started_at = _prepare_session_locked(
            session,
            stream_id=stream_id,
            message=clean_message,
            attachments=list(attachments or []),
            workspace=effective_workspace,
            model=effective_model,
            provider=effective_provider,
            source=str(source or "webui").strip() or "webui",
        )

    if was_hidden:
        publish_session_list_changed(
            "session_new",
            profile=getattr(session, "profile", None),
            session_id=session.session_id,
        )

    journal_event: dict[str, Any] = {}
    try:
        from api.turn_journal import append_turn_journal_event

        journal_event = append_turn_journal_event(
            session.session_id,
            {
                "event": "submitted",
                "stream_id": stream_id,
                "role": "user",
                "content": clean_message,
                "attachments": list(attachments or []),
                "workspace": effective_workspace,
                "model": effective_model,
                "model_provider": effective_provider,
                "worker": getattr(selected_backend, "name", "unknown"),
                "created_at": started_at,
            },
        )
    except Exception:
        logger.warning("Failed to append submitted turn journal event", exc_info=True)

    try:
        from core.modes import note_user_activity
        note_user_activity()
    except Exception:
        pass

    set_last_workspace(effective_workspace)
    channel = create_stream_channel()
    register_stream_owner(stream_id, session.session_id)
    with STREAMS_LOCK:
        STREAMS[stream_id] = channel

    goal_related = session.session_id in PENDING_GOAL_CONTINUATION
    PENDING_GOAL_CONTINUATION.discard(session.session_id)
    PENDING_BG_TASK_COMPLETIONS.discard(session.session_id)
    if goal_related:
        STREAM_GOAL_RELATED[stream_id] = True

    worker_target, is_gateway, _is_jaeger = selected_backend.get_worker_target()

    # Stateless workers need ARES to serialize prior turns. Gateway workers
    # (Jaeger: get_worker_target()[1] is True) receive a clean user turn and
    # keep native structured continuity on the live agent.
    from api.conversation_history import build_context_prompt

    existing_messages = list(getattr(session, "messages", None) or [])
    context_message = clean_message if is_gateway else build_context_prompt(
        clean_message,
        existing_messages,
        current_backend_id=getattr(selected_backend, "name", None),
        current_model=effective_model,
        current_model_provider=effective_provider,
    )

    # Standing user directives apply to every worker, so they are prepended here
    # rather than inside build_context_prompt: this is the one point both prompt
    # shapes pass through, and gateway workers never reach the builder. The
    # directives ride the execution prompt only — `clean_message` is what gets
    # persisted as the user's turn, so history stays free of injected text.
    from api.ares_directives import apply_directives

    context_message = apply_directives(context_message)

    # Workers receive an internal context prompt as their execution input but
    # must persist only the user's actual typed text in ARES history. The three
    # names below are the same value under the aliases individual targets have
    # grown; `_filter_kwargs_for_callable` drops whichever a given target does
    # not declare, so a signature change in one worker cannot kill the others.
    worker_kwargs = {
        "model_provider": effective_provider,
        "goal_related": goal_related,
        "user_text": clean_message,
        "original_message": clean_message,
        "user_message": clean_message,
    }
    worker_args = (
        session.session_id,
        context_message,
        effective_model,
        effective_workspace,
        stream_id,
        list(attachments or []),
    )
    bound_kwargs = _filter_kwargs_for_callable(worker_target, worker_kwargs)

    def _thread_main(*call_args: Any, **call_kwargs: Any) -> None:
        try:
            worker_target(*call_args, **call_kwargs)
        except Exception as exc:  # noqa: BLE001 - boot failures must reach the UI
            logger.exception("worker boot/run failed stream_id=%s", stream_id)
            _publish_worker_boot_error(stream_id, session.session_id, exc)

    # args/kwargs stay on the Thread (rather than captured in the closure) so
    # the call the worker actually receives remains inspectable.
    worker = threading.Thread(
        target=_thread_main,
        args=worker_args,
        kwargs=bound_kwargs,
        name=f"ares-run-{stream_id[:8]}",
        daemon=True,
    )
    _register_worker_thread(stream_id, worker)
    try:
        worker.start()
    except Exception as exc:
        with STREAMS_LOCK:
            STREAMS.pop(stream_id, None)
        unregister_stream_owner(stream_id)
        with session_lock:
            session.active_stream_id = None
            session.pending_user_message = None
            session.pending_attachments = []
            session.pending_started_at = None
            session.pending_user_source = None
            session.save(touch_updated_at=False)
        logger.exception("Could not start runtime worker for %s", session.session_id)
        return {"error": f"Could not start assistant runtime: {exc}", "_status": 500}

    response = {
        "stream_id": stream_id,
        "session_id": session.session_id,
        "pending_started_at": started_at,
        "turn_id": journal_event.get("turn_id"),
        "title": session.title,
        "effective_model": effective_model,
    }
    if effective_provider:
        response["effective_model_provider"] = effective_provider
    if cleared_stream_id:
        # Recovered from an abandoned turn rather than starting cleanly. Say so,
        # so a client that just saw a 409 can tell this apart from a normal send.
        response["cleared_stream_id"] = cleared_stream_id
        response["recovered_stale_stream"] = True

    try:
        from api.background_process import get_session_channel

        activity_channel = get_session_channel(session.session_id)
        if activity_channel is not None:
            activity_channel.emit(
                "server_turn_started",
                {
                    "session_id": session.session_id,
                    "stream_id": stream_id,
                    "pending_started_at": started_at,
                    "source": source,
                },
            )
    except Exception:
        logger.debug("server_turn_started fan-out failed", exc_info=True)
    return response


__all__ = ["resolve_chat_workspace_with_recovery", "start_session_turn"]
