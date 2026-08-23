"""Model deliberation reaches the browser instead of being discarded.

The last gap in the JaegerAI backend's parity with the donated WebUI. The
frontend has always had a Thinking card and a ``reasoning`` handler; the Jaeger
lane could never fill it, because JaegerOS's NDJSON protocol had no frame
carrying model deliberation and the adapters stripped ``<think>`` blocks out of
the answer and threw the text away.

Chain under test:

    adapter strips <think> -> message["reasoning"]
      -> agent loop fires callbacks.on_reasoning
        -> JaegerAI's reasoning sink emits protocol.reasoning_frame
          -> ARES translates it to the ``reasoning`` SSE event
"""

from __future__ import annotations

import pytest


def _events():
    seen: list[tuple[str, dict]] = []
    return seen, lambda event, payload: seen.append((event, payload))


def test_reasoning_frame_becomes_a_reasoning_sse_event():
    from api.providers.jaeger import streaming

    seen, put = _events()
    streaming._translate_bridge_frame(
        {"type": "reasoning", "text": "weigh the options", "session": "s1"},
        put,
        "stream-1",
    )

    assert seen == [("reasoning", {"text": "weigh the options"})]


def test_reasoning_never_reaches_the_token_handler():
    """The bug this frame type exists to prevent.

    The browser's ``token`` handler APPENDS to the visible assistant text. If
    deliberation were folded into the delta stream, the model's internal
    monologue would render as the reply.
    """
    from api.providers.jaeger import streaming

    seen, put = _events()
    streaming._translate_bridge_frame(
        {"type": "reasoning", "text": "internal monologue"}, put, "stream-2"
    )
    streaming._translate_bridge_frame(
        {"type": "delta", "text": "the answer"}, put, "stream-2"
    )

    assert [event for event, _ in seen] == ["reasoning", "token"]
    reasoning_payload = dict(seen[0][1])
    token_payload = dict(seen[1][1])
    assert "internal monologue" not in token_payload.get("text", "")
    assert reasoning_payload["text"] == "internal monologue"


def test_reasoning_accumulates_for_persistence():
    """Chunks accumulate so the finished turn can persist the full text."""
    from api.config import STREAM_REASONING_TEXT
    from api.providers.jaeger import streaming

    stream_id = "stream-accumulate"
    STREAM_REASONING_TEXT.pop(stream_id, None)
    _seen, put = _events()
    try:
        streaming._translate_bridge_frame({"type": "reasoning", "text": "first "}, put, stream_id)
        streaming._translate_bridge_frame({"type": "reasoning", "text": "second"}, put, stream_id)
        assert STREAM_REASONING_TEXT[stream_id] == "first second"
    finally:
        STREAM_REASONING_TEXT.pop(stream_id, None)


def test_empty_reasoning_emits_nothing():
    from api.providers.jaeger import streaming

    seen, put = _events()
    streaming._translate_bridge_frame({"type": "reasoning", "text": ""}, put, "stream-3")
    assert seen == []


# ── the producing half, in the absorbed packages ───────────────────────────

# jaeger-agent and jaeger-os are installed from the JaegerAI monorepo, not by
# ARES, so these run only where that environment is present. Guarded per-test
# rather than at module scope — a module-level importorskip would also skip the
# ARES-side translation tests above, which need no such dependency.
_needs_jaeger_packages = pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("jaeger_agent") is None,
    reason="jaeger-agent not installed in this environment (JaegerAI monorepo only)",
)


@_needs_jaeger_packages
@pytest.mark.parametrize(
    "raw,visible,deliberation",
    [
        ("<think>weigh options</think>Answer.", "Answer.", "weigh options"),
        ("no thinking at all", "no thinking at all", ""),
        # Model ran out of budget mid-thought: everything after the open tag
        # is deliberation and the visible answer is empty.
        ("<think>cut off mid", "", "cut off mid"),
        ("a<think>one</think>b<think>two</think>c", "abc", "one\ntwo"),
    ],
)
def test_extract_think_blocks_returns_both_halves(raw, visible, deliberation):
    from jaeger_agent.dialects import extract_think_blocks

    assert extract_think_blocks(raw) == (visible, deliberation)


@_needs_jaeger_packages
def test_strip_think_blocks_keeps_its_old_shape():
    """Existing callers and tests depend on the string-returning wrapper."""
    from jaeger_agent.dialects import strip_think_blocks

    assert strip_think_blocks("<think>x</think>Answer.") == "Answer."


@_needs_jaeger_packages
def test_reasoning_callback_is_optional_and_cannot_break_a_turn():
    from jaeger_agent.loop.callbacks import AgentCallbacks

    assert AgentCallbacks().on_reasoning("x") is None

    def explode(_text):
        raise RuntimeError("listener blew up")

    assert AgentCallbacks(reasoning=explode).on_reasoning("x") is None


@_needs_jaeger_packages
def test_protocol_declares_the_frame_and_the_capability():
    from jaeger_os.contract import protocol

    assert protocol.reasoning_frame("t", "s1") == {
        "type": "reasoning",
        "text": "t",
        "session": "s1",
    }
    # Session is omitted when unknown, like every other additive field.
    assert protocol.reasoning_frame("t") == {"type": "reasoning", "text": "t"}
    assert "streaming" in protocol.CAPABILITIES
