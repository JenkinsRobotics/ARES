from __future__ import annotations

import importlib
import os


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_HOME", str(tmp_path))
    from api import kanban_store

    return importlib.reload(kanban_store)


def test_native_store_persists_tasks_boards_and_secure_files(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    store.create_board("release", name="Release")
    store.set_current_board("release")
    store.init_db()
    with store.connect_closing() as conn:
        task_id = store.create_task(
            conn, title="Ship", body="Run checks", idempotency_key="ship"
        )
        assert (
            store.create_task(conn, title="duplicate", idempotency_key="ship")
            == task_id
        )
        assert store.get_task(conn, task_id).title == "Ship"
        assert store.block_task(conn, task_id, "waiting") is True
        assert store.unblock_task(conn, task_id) is True

    # Reloading the module/process view retains the same canonical record.
    store = importlib.reload(store)
    with store.connect_closing() as conn:
        assert store.get_task(conn, task_id).status == "ready"
    assert store.get_current_board() == "release"
    assert os.stat(store._db_path()).st_mode & 0o777 == 0o600


def test_native_dispatch_uses_existing_delegation_router(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    store.create_board("default")
    store.init_db()
    calls = []
    monkeypatch.setattr(
        "api.delegation_runner.delegate",
        lambda **kwargs: calls.append(kwargs) or {"id": "delegated-1"},
    )
    monkeypatch.setattr(
        "api.backend_selector.get_active_backend", lambda _config: "jaeger_local"
    )
    monkeypatch.setattr("api.config.get_config", lambda: {})
    monkeypatch.setattr(
        store.threading,
        "Thread",
        lambda **_kwargs: type("T", (), {"start": lambda self: None})(),
    )

    with store.connect_closing() as conn:
        task_id = store.create_task(conn, title="Research", body="facts")
        result = store.dispatch_once(conn)
        task = store.get_task(conn, task_id)

    assert calls == [{"prompt": "Research\n\nfacts", "backend": "jaeger_local"}]
    assert result["spawned"][0]["delegation_id"] == "delegated-1"
    assert task.status == "running"
