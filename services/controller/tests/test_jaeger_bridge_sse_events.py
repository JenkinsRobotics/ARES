"""Jaeger bridge frames must use the restored WebUI SSE event names."""

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "jaeger_sse_events",
    _ROOT / "integrations" / "providers" / "jaeger" / "sse_events.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
_tool_sse_event = _MOD.tool_sse_event


def test_tool_start_is_sse_tool_not_complete():
    event, event_type = _tool_sse_event("start", is_error=False)
    assert event == "tool"
    assert event_type == "tool.started"


def test_tool_done_is_sse_tool_complete():
    event, event_type = _tool_sse_event("done", is_error=False)
    assert event == "tool_complete"
    assert event_type == "tool.completed"


def test_tool_error_is_sse_tool_complete():
    event, event_type = _tool_sse_event("start", is_error=True)
    assert event == "tool_complete"
    assert event_type == "tool.failed"
