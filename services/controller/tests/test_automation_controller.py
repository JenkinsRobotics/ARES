from __future__ import annotations

import time

from fastapi.testclient import TestClient

from core.automation.adapters import AdapterResult, AgentAdapter
from core.automation.service import AutomationService
from core.automation.store import AutomationStore
from fastapi_app.main import create_app


class FakeAdapter(AgentAdapter):
    def probe(self, agent):
        return {"available": True, "owner": agent.runtime}

    def start_run(self, agent, prompt, session_id, emit, cancel):
        emit("text_delta", {"text": "working"})
        return AdapterResult("done\nARES_STATUS: complete", session_id or f"{agent.runtime}-session")

    def cancel_run(self, session_id):
        return None


def service(tmp_path):
    return AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": FakeAdapter(), "jaeger": FakeAdapter()},
    )


def wait_for_run(controller, run_id):
    for _ in range(100):
        run = next(row for row in controller.snapshot()["runs"] if row["id"] == run_id)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_closed_loop_persists_agent_goal_run_and_events(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({"id": "hermes", "runtime": "hermes", "name": "Hermes", "identity": "worker", "model": "local", "workspace": "/workspace"})
    goal = controller.create_goal({"agent_id": "hermes", "objective": "finish the task"})
    run = controller.wake("hermes", goal_id=goal["id"], idempotency_key="same")
    assert controller.wake("hermes", goal_id=goal["id"], idempotency_key="same")["id"] == run["id"]
    finished = wait_for_run(controller, run["id"])
    assert finished["status"] == "complete"
    assert finished["session_id"] == "hermes-session"
    assert {row["type"] for row in controller.snapshot()["events"]} >= {"run_started", "text_delta", "run_completed"}
    assert (tmp_path / "automation.json").stat().st_mode & 0o777 == 0o600


def test_credentials_must_be_opaque_references(tmp_path):
    controller = service(tmp_path)
    try:
        controller.put_agent({"id": "bad", "runtime": "hermes", "name": "bad", "identity": "bad", "model": "", "workspace": "/workspace", "credential_references": ["actual-secret"]})
    except ValueError as exc:
        assert "keychain" in str(exc)
    else:
        raise AssertionError("raw credential was accepted")


def test_public_api_and_lightweight_dashboard(tmp_path):
    controller = service(tmp_path)
    app = create_app()
    app.state.automation_service = controller
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/").status_code == 200
        assert "Independent agents" in client.get("/").text
        put = client.put("/api/agents", json={"id": "jaeger", "runtime": "jaeger", "name": "Jaeger", "identity": "native worker", "model": "local", "workspace": "/tmp"})
        assert put.status_code == 200
        goal = client.post("/api/goals", json={"agent_id": "jaeger", "objective": "test"})
        assert goal.status_code == 200
        wake = client.post(f"/api/agents/jaeger/wake", json={"goal_id": goal.json()["id"]})
        assert wake.status_code == 200
        assert client.get("/api/runs").status_code == 200
        assert client.get("/api/approvals").status_code == 200


def test_global_pause_blocks_new_work(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({"id": "hermes", "runtime": "hermes", "name": "Hermes", "identity": "worker", "model": "", "workspace": "/workspace"})
    goal = controller.create_goal({"agent_id": "hermes", "objective": "wait"})
    controller.pause(True)
    try:
        controller.wake("hermes", goal_id=goal["id"])
    except RuntimeError as exc:
        assert "paused" in str(exc)
    else:
        raise AssertionError("paused controller accepted work")


def test_heartbeat_tick_resumes_incomplete_goal_with_bounded_idempotency(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({"id": "hermes", "runtime": "hermes", "name": "Hermes", "identity": "worker", "model": "", "workspace": "/workspace", "heartbeat_minutes": 1})
    goal = controller.create_goal({"agent_id": "hermes", "objective": "continue"})
    first = controller.tick(now=120)
    assert len(first) == 1
    wait_for_run(controller, first[0]["id"])
    assert controller.tick(now=121) == []
    assert controller.tick(now=181) == []  # fake adapter completed the durable goal


def test_interrupted_run_is_checkpointed_for_safe_resume(tmp_path):
    store = AutomationStore(tmp_path / "automation.json")
    state = store.read()
    state["runs"].append({"id": "run_old", "agent_id": "hermes", "goal_id": "goal", "trigger": "manual", "policy_version": 1, "created_at": 1, "status": "running", "attempt": 1, "session_id": "s", "result": "", "error": "", "started_at": 1, "finished_at": None})
    store.update(lambda current: current.update(state))
    controller = AutomationService(store=store, adapters={"hermes": FakeAdapter(), "jaeger": FakeAdapter()})
    recovered = controller.snapshot()
    assert recovered["runs"][0]["status"] == "continue"
    assert recovered["events"][0]["type"] == "checkpoint"
