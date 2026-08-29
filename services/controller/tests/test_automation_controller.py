from __future__ import annotations

import subprocess
import threading
import time

from fastapi.testclient import TestClient

from core.automation.adapters import AdapterResult, AgentAdapter, HermesAdapter
from core.automation.models import Agent
from core.automation.service import AutomationService
from core.automation.store import AutomationStore
from fastapi_app.main import create_app


class FakeAdapter(AgentAdapter):
    def __init__(self):
        self.configuration = {
            "owner": "hermes",
            "endpoint": "http://runtime.invalid",
            "soul": "Original\n",
            "soul_path": "/runtime/SOUL.md",
            "workspaces": [{"path": "/workspace", "name": "Home"}],
            "last_workspace": "/workspace",
        }

    def probe(self, agent):
        return {"available": True, "owner": agent.runtime}

    def start_run(self, agent, prompt, session_id, emit, cancel):
        emit("text_delta", {"text": "working"})
        return AdapterResult("done\nARES_STATUS: complete", session_id or f"{agent.runtime}-session")

    def cancel_run(self, session_id):
        return None

    def inspect_configuration(self, agent):
        return self.configuration

    def apply_configuration(self, agent, desired):
        paths = {row["path"] for row in self.configuration["workspaces"]}
        paths.update(desired.get("workspaces") or [])
        self.configuration = {
            **self.configuration,
            "soul": desired.get("soul", self.configuration["soul"]),
            "workspaces": [{"path": path, "name": path.rsplit("/", 1)[-1]} for path in sorted(paths)],
        }
        return self.configuration


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


def test_agent_id_rejects_dashboard_script_injection(tmp_path):
    controller = service(tmp_path)
    try:
        controller.put_agent({
            "id": "bad');alert(1);//", "runtime": "hermes", "name": "bad",
            "identity": "bad", "model": "", "workspace": "/workspace",
        })
    except ValueError as exc:
        assert "agent id" in str(exc)
    else:
        raise AssertionError("unsafe agent id was accepted")


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
        wake = client.post("/api/agents/jaeger/wake", json={"goal_id": goal.json()["id"]})
        assert wake.status_code == 200
        assert client.get("/api/runs").status_code == 200
        assert client.get("/api/approvals").status_code == 200


def test_hermes_configuration_is_approval_gated_and_audited(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "reference agent", "model": "cloud", "workspace": "/workspace",
    })
    requested = controller.request_agent_configuration("hermes", {
        "soul": "Independent reference agent",
        "workspaces": ["/workspace", "/workspace/GitHub"],
    })
    change = requested["change"]
    approval = requested["approval"]
    assert change["status"] == "pending"
    assert approval["kind"] == "configuration"
    assert controller.inspect_agent_configuration("hermes")["current"]["soul"] == "Original\n"

    resolved = controller.resolve_approval({"id": approval["id"], "decision": "approved"})
    assert resolved["configuration_change_id"] == change["id"]
    effective = controller.inspect_agent_configuration("hermes")
    assert effective["current"]["soul"] == "Independent reference agent\n"
    assert {row["path"] for row in effective["current"]["workspaces"]} == {
        "/workspace", "/workspace/GitHub",
    }
    applied = effective["changes"][0]
    assert applied["status"] == "applied"
    assert len(applied["evidence"]["soul_sha256"]) == 64


def test_hermes_configuration_rejects_unmounted_host_paths(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "reference agent", "model": "cloud", "workspace": "/workspace",
    })
    try:
        controller.request_agent_configuration("hermes", {
            "workspaces": ["/Users/matthewjenkins/GitHub"],
        })
    except ValueError as exc:
        assert "approved /workspace mount" in str(exc)
    else:
        raise AssertionError("host path bypassed the Hermes container boundary")


def test_configuration_api_creates_approval_before_mutation(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "reference agent", "model": "cloud", "workspace": "/workspace",
    })
    app = create_app()
    app.state.automation_service = controller
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        before = client.get("/api/agents/hermes/configuration")
        assert before.status_code == 200
        requested = client.put(
            "/api/agents/hermes/configuration",
            json={"soul": "Managed by its runtime", "workspaces": ["/workspace"]},
        )
        assert requested.status_code == 200
        assert requested.json()["approval"]["status"] == "pending"
        assert client.get("/api/agents/hermes/configuration").json()["current"]["soul"] == "Original\n"


def test_hermes_adapter_uses_runtime_owned_configuration_api():
    adapter = HermesAdapter(command="/bin/true", webui_url="http://127.0.0.1:8787")
    calls = []
    state = {
        "soul": "Before\n",
        "workspaces": [{"path": "/workspace", "name": "Home"}],
    }

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/api/memory" and method == "GET":
            return {"soul": state["soul"], "soul_path": "/runtime/SOUL.md"}
        if path == "/api/workspaces" and method == "GET":
            return {"workspaces": state["workspaces"], "last": "/workspace"}
        if path == "/api/workspaces/add":
            state["workspaces"].append({"path": payload["path"], "name": "GitHub"})
            return {"ok": True}
        if path == "/api/memory/write":
            state["soul"] = payload["content"]
            return {"ok": True}
        raise AssertionError((method, path, payload))

    adapter._webui_request = request
    agent = Agent.from_dict({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "reference", "model": "cloud", "workspace": "/workspace",
    })
    effective = adapter.apply_configuration(agent, {
        "soul": "After\n", "workspaces": ["/workspace", "/workspace/GitHub"],
    })
    assert effective["soul"] == "After\n"
    assert ("POST", "/api/workspaces/add", {"path": "/workspace/GitHub"}) in calls
    assert ("POST", "/api/memory/write", {"section": "soul", "content": "After\n"}) in calls


def test_hermes_adapter_recovers_when_runtime_history_was_cleaned(tmp_path, monkeypatch):
    calls = []

    class Process:
        def __init__(self, args, **_kwargs):
            calls.append(args)
            self.returncode = 1 if "--resume" in args else 0

        def communicate(self, timeout):
            assert timeout > 0
            if self.returncode:
                return "", "Session not found: deleted-session"
            return "fresh answer\nsession_id: fresh-session\n", ""

        def terminate(self):
            return None

    monkeypatch.setattr("core.automation.adapters.subprocess.Popen", Process)
    adapter = HermesAdapter(command="/runtime/hermes")
    agent = Agent.from_dict({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "reference", "model": "", "workspace": str(tmp_path),
    })
    events = []
    result = adapter.start_run(
        agent, "continue", "deleted-session",
        lambda kind, data: events.append((kind, data)),
        __import__("threading").Event(),
    )

    assert result.error == ""
    assert result.session_id == "fresh-session"
    assert result.text == "fresh answer"
    assert "--resume" in calls[0]
    assert "--resume" not in calls[1]
    assert events[0][0] == "checkpoint"


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
    controller.create_goal({"agent_id": "hermes", "objective": "continue"})
    first = controller.tick(now=120)
    assert len(first) == 1
    wait_for_run(controller, first[0]["id"])
    assert controller.tick(now=121) == []
    assert controller.tick(now=181) == []  # fake adapter completed the durable goal


def test_duplicate_wake_is_rejected_before_a_run_record_is_written(tmp_path):
    class BlockingAdapter(FakeAdapter):
        def start_run(self, agent, prompt, session_id, emit, cancel):
            time.sleep(0.15)
            return super().start_run(agent, prompt, session_id, emit, cancel)

    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": BlockingAdapter(), "jaeger": BlockingAdapter()},
    )
    controller.put_agent({"id": "hermes", "runtime": "hermes", "name": "Hermes", "identity": "worker", "model": "", "workspace": "/workspace"})
    goal = controller.create_goal({"agent_id": "hermes", "objective": "hold lease"})
    first = controller.wake("hermes", goal_id=goal["id"], idempotency_key="first")
    try:
        controller.wake("hermes", goal_id=goal["id"], idempotency_key="second")
    except RuntimeError as exc:
        assert "active" in str(exc)
    else:
        raise AssertionError("duplicate wake was admitted")
    assert [row["id"] for row in controller.snapshot()["runs"]] == [first["id"]]
    assert controller.tick(now=time.time() + 3600) == []
    wait_for_run(controller, first["id"])


def test_interrupted_run_is_checkpointed_for_safe_resume(tmp_path):
    store = AutomationStore(tmp_path / "automation.json")
    state = store.read()
    state["runs"].append({"id": "run_old", "agent_id": "hermes", "goal_id": "goal", "trigger": "manual", "policy_version": 1, "created_at": 1, "status": "running", "attempt": 1, "session_id": "s", "result": "", "error": "", "started_at": 1, "finished_at": None})
    store.update(lambda current: current.update(state))
    controller = AutomationService(store=store, adapters={"hermes": FakeAdapter(), "jaeger": FakeAdapter()})
    recovered = controller.snapshot()
    assert recovered["runs"][0]["status"] == "continue"
    assert recovered["events"][0]["type"] == "checkpoint"


def test_cancellation_stops_adapter_and_remains_terminal(tmp_path):
    class BlockingAdapter(FakeAdapter):
        def start_run(self, agent, prompt, session_id, emit, cancel):
            assert cancel.wait(2)
            return AdapterResult("", session_id, "cancelled")

    adapter = BlockingAdapter()
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "hold"})
    run = controller.wake("hermes", goal_id=goal["id"])
    cancelled = controller.cancel(run["id"])
    assert cancelled["status"] == "cancelled"
    time.sleep(0.05)
    assert controller._run(run["id"])["status"] == "cancelled"


def test_failed_runs_retry_with_bounded_backoff(tmp_path):
    class FailingAdapter(FakeAdapter):
        def start_run(self, agent, prompt, session_id, emit, cancel):
            return AdapterResult("", session_id or "failed-session", "temporary failure")

    adapter = FailingAdapter()
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
        "heartbeat_minutes": 1,
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "retry"})
    first = controller.wake("hermes", goal_id=goal["id"], attempt=1)
    first = wait_for_run(controller, first["id"])
    second = controller.tick(now=first["finished_at"] + 31)[0]
    second = wait_for_run(controller, second["id"])
    third = controller.tick(now=second["finished_at"] + 61)[0]
    third = wait_for_run(controller, third["id"])
    assert [first["attempt"], second["attempt"], third["attempt"]] == [1, 2, 3]
    assert controller.tick(now=third["finished_at"] + 3600) == []


def test_hermes_timeout_terminates_child_and_fails_closed(tmp_path, monkeypatch):
    class TimedOutProcess:
        returncode = 1

        def __init__(self, *_args, **_kwargs):
            self.terminated = False
            self.communications = 0

        def communicate(self, timeout):
            self.communications += 1
            if self.communications == 1:
                raise subprocess.TimeoutExpired("hermes", timeout)
            assert self.terminated
            return "", "terminated"

        def terminate(self):
            self.terminated = True

    monkeypatch.setattr("core.automation.adapters.subprocess.Popen", TimedOutProcess)
    adapter = HermesAdapter(command="/runtime/hermes")
    agent = Agent.from_dict({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "reference", "model": "", "workspace": str(tmp_path),
        "timeout_seconds": 10,
    })
    result = adapter.start_run(agent, "work", "", lambda *_: None, threading.Event())
    assert result.error == "Hermes run timed out"
