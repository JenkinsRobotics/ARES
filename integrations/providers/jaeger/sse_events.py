"""Map Jaeger bridge frames onto restored Hermes WebUI SSE event names."""


def tool_sse_event(status: str, *, is_error: bool) -> tuple[str, str]:
    """Return ``(sse_event_name, event_type)`` for one Jaeger tool frame.

    Jaeger emits ``phase: start|done`` on NDJSON type ``tool``. The
    browser listens for SSE ``tool`` (start) and ``tool_complete`` (done).
    """
    done = is_error or status in ("done", "complete", "completed", "ok")
    if is_error:
        return "tool_complete", "tool.failed"
    if done:
        return "tool_complete", "tool.completed"
    return "tool", "tool.started"
