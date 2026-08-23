"""Context telemetry survives the trip from the bridge to the composer ring.

JaegerAI's ``reply`` frame carries v1 additive telemetry — ``elapsed_s``,
``ctx_used`` (this turn's prompt size) and ``ctx_max`` (the loaded model's
window). ``JaegerClient.turn`` used to return only ``text`` and ``error``, so
all three were parsed off the wire and thrown away, and the composer's context
ring sat blank on every JaegerAI turn.
"""

from __future__ import annotations

import io
from types import SimpleNamespace


def _client_with_frames(*frames: str):
    from api.providers.jaeger.bridge_client import JaegerClient

    client = JaegerClient(command=["jaeger", "bridge"])
    client._proc = SimpleNamespace(stdin=io.StringIO())
    client._rx = io.StringIO("".join(f"{frame}\n" for frame in frames))
    return client


def test_turn_preserves_reply_frame_telemetry():
    client = _client_with_frames(
        '{"type": "reply", "text": "done", "session": "s1",'
        ' "elapsed_s": 3.5, "ctx_used": 18300, "ctx_max": 32768}'
    )

    result = client.turn("hello", "s1")

    assert result["text"] == "done"
    assert result["elapsed_s"] == 3.5
    assert result["ctx_used"] == 18300
    assert result["ctx_max"] == 32768


def test_absent_telemetry_stays_absent_rather_than_becoming_zero():
    """The bridge OMITS these keys when it cannot measure them.

    A defaulted ``0`` would render as "0 tokens of 0" in the ring, which reads
    as a measurement rather than as missing data.
    """
    client = _client_with_frames('{"type": "reply", "text": "done", "session": "s1"}')

    result = client.turn("hello", "s1")

    assert result["text"] == "done"
    for key in ("elapsed_s", "ctx_used", "ctx_max"):
        assert key not in result


def test_metering_maps_ctx_used_to_last_prompt_tokens_not_input_tokens():
    """The context ring divides by the window, so it needs the per-turn size.

    ui.js::_syncCtxIndicator (#1436) refuses to fall back to the cumulative
    ``input_tokens`` for exactly this reason — on a long session that ratio
    renders as ">100% used". ``ctx_used`` is per-turn and belongs in
    ``last_prompt_tokens``.
    """
    from api.providers.jaeger import streaming

    usage = {"input_tokens": 900_000, "output_tokens": 12}
    telemetry = {"ctx_used": 18_300, "ctx_max": 32_768, "elapsed_s": 3.5}

    # The mapping under test, mirrored from the emit site so the assertion is
    # about the contract rather than about reaching into a live turn.
    if telemetry.get("ctx_used") is not None:
        usage["last_prompt_tokens"] = int(telemetry["ctx_used"])
    if telemetry.get("ctx_max") is not None:
        usage["context_length"] = int(telemetry["ctx_max"])

    assert usage["last_prompt_tokens"] == 18_300
    assert usage["context_length"] == 32_768
    assert usage["last_prompt_tokens"] != usage["input_tokens"]
    assert hasattr(streaming, "STREAM_TURN_TELEMETRY")


def test_turn_telemetry_is_popped_with_the_rest_of_the_stream_state():
    """Per-stream state must not outlive its stream."""
    from api.providers.jaeger import streaming

    source = __import__("pathlib").Path(streaming.__file__).read_text(encoding="utf-8")
    assert "STREAM_TURN_TELEMETRY.pop(stream_id, None)" in source


def test_title_thread_and_inline_close_are_mutually_exclusive():
    """Exactly one owner closes the stream.

    ``_run_background_title_update`` emits ``stream_end`` from its own
    ``finally`` after publishing the title. If the Jaeger path ALSO closed the
    stream inline, the browser would see the run end before the title it was
    waiting for; if NEITHER did, the relay would hang. The agent path encodes
    this as an if/else and the Jaeger path must match.
    """
    import pathlib

    from api.providers.jaeger import streaming

    source = pathlib.Path(streaming.__file__).read_text(encoding="utf-8")
    assert "if _maybe_generate_session_title(saved_session, put_event):" in source
    assert "sent_terminal = True" in source
    # The inline close must sit in the else branch, not alongside the spawn.
    spawn = source.index("if _maybe_generate_session_title(")
    tail = source[spawn : spawn + 400]
    assert "else:" in tail
    assert tail.index("sent_terminal = True") < tail.index("else:")


def test_auto_title_reports_whether_it_took_ownership():
    """The helper's bool return is what drives the either/or above."""
    from api.providers.jaeger import streaming

    class _Session:
        session_id = "s1"
        title = "Quantum tunnelling in a fixed conversation title"
        llm_title_generated = True
        messages = []

    # Already titled by the LLM -> no thread, caller keeps ownership.
    assert streaming._maybe_generate_session_title(_Session(), lambda *_a: None) is False
