import json
import queue
import threading

import pytest
from api.providers.jaeger.bridge_client import JaegerClient, JaegerError


class _Lines:
    def __init__(self):
        self.items = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self):
        item = self.items.get(timeout=2)
        if item is None:
            raise StopIteration
        return json.dumps(item) + "\n"


def test_query_result_is_not_blocked_behind_active_turn():
    client = JaegerClient(command=["unused"])
    lines = _Lines()
    writes = []
    client._rx = lines
    client._write = writes.append
    client._start_reader()

    turn_result = {}
    turn_thread = threading.Thread(
        target=lambda: turn_result.update(client.turn("work", session="s1"))
    )
    turn_thread.start()

    while not any(frame.get("op") == "send" for frame in writes):
        pass

    query_result = {}
    query_thread = threading.Thread(
        target=lambda: query_result.update(value=client.query("list_sessions"))
    )
    query_thread.start()
    while not any(frame.get("op") == "query" for frame in writes):
        pass
    request = next(frame for frame in writes if frame.get("op") == "query")

    lines.items.put({"type": "result", "id": request["id"], "ok": True, "data": ["ready"]})
    query_thread.join(timeout=1)
    assert query_result == {"value": ["ready"]}
    assert turn_thread.is_alive(), "the model turn should still be in flight"

    lines.items.put({"type": "reply", "text": "done", "session": "s1"})
    turn_thread.join(timeout=1)
    assert turn_result["text"] == "done"
    lines.items.put(None)


def test_read_only_query_timeout_is_bounded_and_configurable():
    client = JaegerClient(command=["unused"])
    lines = _Lines()
    client._rx = lines
    client._write = lambda _frame: None
    client._start_reader()

    with pytest.raises(JaegerError, match="timed out after 0.01 seconds"):
        client.query("serving_model", timeout=0.01)

    lines.items.put(None)
