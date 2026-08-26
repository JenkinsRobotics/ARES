"""Text deltas: the turn's answer arrives while it is generated.

Before this, a JaegerAI turn reached the browser as one `token` event
after the whole turn finished — the bridge's only text frame was the
final `reply`. JaegerAI now emits `delta` frames as the model produces
text, and these pin the ARES half: deltas become incremental `token`
events, and the final reply sends only what the user has not already
seen.

Bridge-level fakes throughout — no JaegerAI install, no subprocess.
"""

import pytest

from api.providers.jaeger import streaming


@pytest.fixture(autouse=True)
def _clean_ledger():
    streaming.STREAM_DELTA_TEXT.clear()
    streaming.STREAM_REASONING_TEXT.clear()
    yield
    streaming.STREAM_DELTA_TEXT.clear()
    streaming.STREAM_REASONING_TEXT.clear()


def _events():
    seen = []
    return seen, lambda event, data: seen.append((event, data))


def test_a_delta_becomes_an_incremental_token_event():
    """The WebUI's token handler appends, so a delta maps straight onto
    the event the front-end already understands."""
    seen, put = _events()

    streaming._translate_bridge_frame({"type": "delta", "text": "Hel"}, put, "s1")
    streaming._translate_bridge_frame({"type": "delta", "text": "lo"}, put, "s1")

    assert seen == [("token", {"text": "Hel"}), ("token", {"text": "lo"})]
    assert streaming.STREAM_DELTA_TEXT["s1"] == "Hello"


def test_empty_deltas_are_dropped():
    seen, put = _events()
    streaming._translate_bridge_frame({"type": "delta", "text": ""}, put, "s1")
    streaming._translate_bridge_frame({"type": "delta"}, put, "s1")
    assert seen == []
    assert "s1" not in streaming.STREAM_DELTA_TEXT


def test_deltas_are_tracked_per_stream():
    seen, put = _events()
    streaming._translate_bridge_frame({"type": "delta", "text": "a"}, put, "s1")
    streaming._translate_bridge_frame({"type": "delta", "text": "b"}, put, "s2")
    assert streaming.STREAM_DELTA_TEXT == {"s1": "a", "s2": "b"}


def test_lifecycle_state_frames_are_not_reasoning():
    """Jaeger busy/idle must not become Hermes thinking-card events."""
    seen, put = _events()
    streaming._translate_bridge_frame(
        {"type": "state", "state": "thinking", "message": "thinking"}, put, "s1")
    streaming._translate_bridge_frame(
        {"type": "state", "busy": True}, put, "s1")
    assert seen == []


def test_model_reasoning_frame_is_preserved_separately_from_answer():
    seen, put = _events()
    streaming.STREAM_REASONING_TEXT["s1"] = ""

    streaming._translate_bridge_frame(
        {"type": "reasoning", "text": "inspect then verify"}, put, "s1",
    )

    assert seen == [("reasoning", {"text": "inspect then verify"})]
    assert streaming.STREAM_REASONING_TEXT["s1"] == "inspect then verify"
    assert "s1" not in streaming.STREAM_DELTA_TEXT


def test_tool_frames_still_translate_alongside_deltas():
    """The delta branch returns early — it must not shadow the frames
    that were already being forwarded."""
    seen, put = _events()
    streaming._translate_bridge_frame(
        {"type": "tool", "name": "read_file", "status": "done"}, put, "s1")
    assert seen and seen[0][0] == "tool"


# ── reconciling the final reply ─────────────────────────────────────


def test_nothing_streamed_sends_the_whole_answer():
    """An older runtime emits no deltas at all — behaviour is exactly
    what it was before deltas existed."""
    assert streaming._delta_remainder("s1", "the full answer") == "the full answer"


def test_a_continued_answer_sends_only_the_tail():
    streaming.STREAM_DELTA_TEXT["s1"] = "the full "
    assert streaming._delta_remainder("s1", "the full answer") == "answer"


def test_a_fully_streamed_answer_sends_nothing():
    streaming.STREAM_DELTA_TEXT["s1"] = "the full answer"
    assert streaming._delta_remainder("s1", "the full answer") == ""


def test_a_diverged_answer_sends_nothing():
    """The persona filter re-voices the finished answer, and the loop
    streams narration between tool calls — so divergence is normal.
    Appending the final text would render the answer twice; the `done`
    event settles the transcript from the saved session instead."""
    streaming.STREAM_DELTA_TEXT["s1"] = "Let me check that for you..."
    assert streaming._delta_remainder("s1", "The answer is 42.") == ""


# ── the client dispatches the frame ─────────────────────────────────


def test_bridge_client_forwards_delta_frames():
    """`turn()` must hand deltas to on_event like tool/state frames, and
    still return the authoritative reply text."""
    import io

    from api.providers.jaeger.bridge_client import JaegerClient

    frames = [
        '{"type": "delta", "text": "Hel"}\n',
        '{"type": "delta", "text": "lo"}\n',
        '{"type": "reply", "text": "Hello"}\n',
    ]

    client = JaegerClient.__new__(JaegerClient)
    client._rx = iter(frames)
    client._io_lock = __import__("threading").RLock()
    client._write = lambda payload: None

    seen: list[dict] = []
    result = client.turn("hi", "s1", on_event=seen.append)

    assert result == {"text": "Hello", "error": None}
    assert [f["text"] for f in seen] == ["Hel", "lo"]


def test_an_unknown_frame_type_is_still_ignored():
    """Forward compatibility runs both ways: a frame this client does not
    know must not break the turn."""
    import io

    from api.providers.jaeger.bridge_client import JaegerClient

    frames = [
        '{"type": "something_new", "text": "?"}\n',
        '{"type": "reply", "text": "done"}\n',
    ]
    client = JaegerClient.__new__(JaegerClient)
    client._rx = iter(frames)
    client._io_lock = __import__("threading").RLock()
    client._write = lambda payload: None

    seen: list[dict] = []
    assert client.turn("hi", "s1", on_event=seen.append)["text"] == "done"
    assert seen == []
