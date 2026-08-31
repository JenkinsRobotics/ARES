from __future__ import annotations

import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient

from core.automation.adapters import (
    AdapterResult,
    AgentAdapter,
    HermesAdapter,
    JaegerAdapter,
)
from core.automation.models import Agent, Approval
from core.automation.service import AutomationService
from core.automation.store import AutomationStore
from fastapi_app.main import create_app


class FakeAdapter(AgentAdapter):
    def __init__(self):
        self.prompts = []
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
        self.prompts.append(prompt)
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


def test_successful_final_answer_without_magic_marker_completes_goal():
    assert AutomationService._status("ARES_JAEGER_LIVE_OK") == "complete"


def test_explicit_continue_marker_keeps_goal_active():
    assert AutomationService._status("more work remains\nARES_STATUS: continue") == "continue"


def test_agent_model_catalog_uses_live_local_and_installed_cloud_lanes(tmp_path, monkeypatch):
    import integrations.workers.model_discovery as discovery

    monkeypatch.setattr(discovery, "list_ollama_local_models", lambda: [{"id": "local-model"}])
    monkeypatch.setattr(discovery, "list_ollama_cloud_models", lambda: [{"id": "cloud-model"}])
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes", "identity": "worker",
        "model": "cloud-model", "model_provider": "ollama-cloud", "workspace": "/workspace",
    })
    providers = controller.model_catalog()["providers"]
    assert [(row["id"], row["models"][0]["id"]) for row in providers] == [
        ("ollama-local", "local-model"),
        ("ollama-cloud", "cloud-model"),
    ]
    assert providers[0]["models"][0]["in_use"] is False
    assert providers[1]["models"][0]["in_use"] is True


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


def test_rag_context_is_routed_only_to_explicit_local_models(tmp_path, monkeypatch):
    local_adapter = FakeAdapter()
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": local_adapter, "jaeger": FakeAdapter()},
    )
    chunk = type("Chunk", (), {
        "text": "private local fact", "source_key": "memory", "source_type": "memory",
        "path": "MEMORY.md", "heading": "", "distance": 0.1,
    })()
    monkeypatch.setattr("api.context_store.retrieve", lambda *args, **kwargs: [chunk])
    controller.put_agent({
        "id": "local", "runtime": "hermes", "identity": "worker", "model": "qwen",
        "model_location": "local", "model_provider": "ollama-local", "workspace": "/workspace",
    })
    local_goal = controller.create_goal({"agent_id": "local", "objective": "local question"})
    local_run = controller.wake("local", goal_id=local_goal["id"])
    wait_for_run(controller, local_run["id"])
    assert "private local fact" in local_adapter.prompts[-1]
    assert "untrusted reference data" in local_adapter.prompts[-1]

    cloud_adapter = FakeAdapter()
    controller.adapters["hermes"] = cloud_adapter
    controller.put_agent({
        "id": "cloud", "runtime": "hermes", "identity": "worker", "model": "glm",
        "model_location": "cloud", "model_provider": "ollama-cloud", "workspace": "/workspace",
    })
    cloud_goal = controller.create_goal({"agent_id": "cloud", "objective": "cloud question"})
    cloud_run = controller.wake("cloud", goal_id=cloud_goal["id"])
    wait_for_run(controller, cloud_run["id"])
    assert "private local fact" not in cloud_adapter.prompts[-1]


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
        wait_for_run(controller, wake.json()["id"])
        thread = client.post("/api/threads", json={"agent_id": "jaeger", "title": "Remote continuity"})
        assert thread.status_code == 200
        sent = client.post(
            f"/api/threads/{thread.json()['id']}/messages",
            json={"agent_id": "jaeger", "content": "remember this"},
        )
        assert sent.status_code == 200
        wait_for_run(controller, sent.json()["run"]["id"])
        detail = client.get(f"/api/threads/{thread.json()['id']}")
        assert [row["role"] for row in detail.json()["messages"]] == ["user", "assistant"]
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
            assert _kwargs["stdin"] is subprocess.PIPE
            self.returncode = 1 if "--resume" in args else 0

        def communicate(self, input=None, timeout=None):
            assert timeout > 0
            if input is not None:
                assert input == "continue"
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
    assert "--query-file" in calls[0]
    assert "-q" not in calls[0]
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


def test_new_goal_does_not_reuse_an_unrelated_runtime_session(tmp_path):
    class RecordingAdapter(FakeAdapter):
        def __init__(self):
            self.sessions = []

        def start_run(self, agent, prompt, session_id, emit, cancel):
            self.sessions.append(session_id)
            return AdapterResult("done\nARES_STATUS: complete", f"session-{len(self.sessions)}")

    adapter = RecordingAdapter()
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    first_goal = controller.create_goal({"agent_id": "hermes", "objective": "first"})
    first = controller.wake("hermes", goal_id=first_goal["id"])
    wait_for_run(controller, first["id"])
    second_goal = controller.create_goal({"agent_id": "hermes", "objective": "second"})
    second = controller.wake("hermes", goal_id=second_goal["id"])
    wait_for_run(controller, second["id"])

    assert adapter.sessions == ["", ""]


def test_system_thread_persists_messages_and_reuses_only_its_owner_session(tmp_path):
    class RecordingAdapter(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.sessions = []

        def start_run(self, agent, prompt, session_id, emit, cancel):
            self.sessions.append(session_id)
            return AdapterResult(
                f"answer-{len(self.sessions)}\nARES_STATUS: complete",
                session_id or f"owner-session-{len(self.sessions)}",
            )

    adapter = RecordingAdapter()
    store = AutomationStore(tmp_path / "automation.json")
    controller = AutomationService(
        store=store, adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    thread = controller.create_thread({"agent_id": "hermes"})
    first = controller.send_thread_message(thread["id"], {"content": "first"})
    wait_for_run(controller, first["run"]["id"])
    second = controller.send_thread_message(thread["id"], {"content": "second"})
    wait_for_run(controller, second["run"]["id"])

    other = controller.create_thread({"agent_id": "hermes", "title": "Separate"})
    third = controller.send_thread_message(other["id"], {"content": "fresh"})
    wait_for_run(controller, third["run"]["id"])
    assert adapter.sessions == ["", "owner-session-1", ""]

    restored = AutomationService(
        store=store, adapters={"hermes": adapter, "jaeger": adapter},
    )
    detail = restored.thread(thread["id"])
    assert [row["role"] for row in detail["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]
    assert detail["messages"][-1]["run_id"] == second["run"]["id"]
    assert detail["messages"][-1]["status"] == "complete"


def test_goal_can_be_closed_with_a_durable_reason(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "obsolete"})
    closed = controller.close_goal(
        goal["id"], status="blocked", reason="Superseded by the audited implementation plan.",
    )
    assert closed["status"] == "blocked"
    assert "Superseded" in closed["terminal_reason"]
    with pytest.raises(ValueError, match="already terminal"):
        controller.close_goal(goal["id"], status="blocked", reason="again")


def test_successful_goal_can_be_reconciled_complete_with_evidence(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "prove it"})
    closed = controller.close_goal(
        goal["id"], status="complete", reason="Run evidence contains the expected result.",
    )
    assert closed["status"] == "complete"
    assert closed["terminal_reason"] == "Run evidence contains the expected result."


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

        def communicate(self, input=None, timeout=None):
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


def test_goal_accepts_large_context_and_rejects_unbounded_payload(tmp_path):
    controller = service(tmp_path)
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    useful_context = "context " * 50_000
    goal = controller.create_goal({"agent_id": "hermes", "objective": useful_context})
    assert goal["objective"] == useful_context.strip()

    with pytest.raises(ValueError, match="1024 KiB context limit"):
        controller.create_goal({"agent_id": "hermes", "objective": "x" * 1_048_577})


def test_capability_request_and_approval_flow(tmp_path, monkeypatch):
    import json

    grants_file = tmp_path / "grants.json"
    grants_file.write_text(json.dumps({
        "version": 1,
        "identities": {
            "hermes": {
                "roots": ["/workspace"],
                "capabilities": ["capabilities.inspect"],
            },
        },
    }))
    monkeypatch.setenv("ARES_CAPABILITY_GRANTS", str(grants_file))
    monkeypatch.setenv("ARES_CAPABILITY_AUDIT", str(tmp_path / "audit.jsonl"))

    controller = service(tmp_path)
    res = controller.request_capability("hermes", capability="calendar.list", reason="Need to view schedule")
    assert res["status"] == "pending"
    approval_id = res["approval_id"]

    pending = [a for a in controller.snapshot()["approvals"] if a["id"] == approval_id]
    assert len(pending) == 1
    assert pending[0]["kind"] == "capability"
    assert "calendar.list" in pending[0]["reason"]

    resolved = controller.resolve_approval({"id": approval_id, "decision": "approved"})
    assert resolved["status"] == "approved"

    updated_grants = json.loads(grants_file.read_text())
    assert "calendar.list" in updated_grants["identities"]["hermes"]["capabilities"]

    res_again = controller.request_capability("hermes", capability="calendar.list")
    assert res_again["status"] == "already_granted"

    new_dir = tmp_path / "extra"
    new_dir.mkdir()
    res_root = controller.request_capability("hermes", root=str(new_dir), reason="Extra workspace")
    approval_id_root = res_root["approval_id"]
    denied = controller.resolve_approval({"id": approval_id_root, "decision": "denied"})
    assert denied["status"] == "denied"
    updated_grants2 = json.loads(grants_file.read_text())
    assert str(new_dir.resolve()) not in updated_grants2["identities"]["hermes"]["roots"]


def test_effect_approval_is_informed_exact_and_one_shot(tmp_path, monkeypatch):
    import hashlib
    import json

    grants_file = tmp_path / "grants.json"
    grants_file.write_text(json.dumps({
        "version": 1,
        "identities": {
            "hermes": {
                "roots": ["/workspace"],
                "capabilities": ["calendar.create"],
            },
        },
    }))
    monkeypatch.setenv("ARES_CAPABILITY_GRANTS", str(grants_file))
    controller = service(tmp_path)
    payload_hash = hashlib.sha256(b"exact calendar payload").hexdigest()
    requested = controller.request_effect({
        "agent_id": "hermes", "capability": "calendar.create",
        "payload_sha256": payload_hash, "operation": "calendar.create",
        "reason": "Create 'Dentist' at 10:00 tomorrow",
        "benefit": "Records the requested appointment.",
        "risks": ["Creates a record visible to calendar participants."],
        "scope": "One event titled Dentist at 10:00 tomorrow",
        "reversible": "Yes, by deleting the event.",
        "safer_alternative": "Return an event draft.",
        "provider": "local-mac", "data_destination": "Apple Calendar",
    })
    approval_id = requested["approval_id"]
    resolved = controller.resolve_approval({"id": approval_id, "decision": "approved"})
    assert resolved["status"] == "approved"
    assert resolved["provider"] == "local-mac"

    with pytest.raises(PermissionError, match="does not match"):
        controller.consume_effect(approval_id, {
            "agent_id": "hermes", "capability": "calendar.create",
            "payload_sha256": hashlib.sha256(b"different").hexdigest(),
        })
    consumed = controller.consume_effect(approval_id, {
        "agent_id": "hermes", "capability": "calendar.create",
        "payload_sha256": payload_hash,
    })
    assert consumed["authorized"] is True
    with pytest.raises(PermissionError, match="one-shot"):
        controller.consume_effect(approval_id, {
            "agent_id": "hermes", "capability": "calendar.create",
            "payload_sha256": payload_hash,
        })


def test_approval_without_plain_language_consequences_fails_closed(tmp_path):
    controller = service(tmp_path)
    approval = Approval(
        id="approval_opaque", run_id="", operation="runtime_request",
        reason="Agent requested a consequential action", created_at=time.time(),
    )
    controller.store.update(lambda state: state["approvals"].append(approval.as_dict()))

    with pytest.raises(ValueError, match="informed-consent context"):
        controller.resolve_approval({"id": approval.id, "decision": "approved"})

    denied = controller.resolve_approval({"id": approval.id, "decision": "denied"})
    assert denied["status"] == "denied"


def test_approval_preview_is_non_executing_and_expired_consent_fails_closed(tmp_path):
    controller = service(tmp_path)
    approval = Approval(
        id="approval_expiring", run_id="", operation="test", reason="Test change",
        created_at=time.time() - 100, benefit="Test benefit", risks=("Test risk",),
        scope="Test only", duration="One action", reversible="Yes",
        safer_alternative="Do nothing", expires_at=time.time() + 60,
    )
    controller.store.update(lambda state: state["approvals"].append(approval.as_dict()))
    preview = controller.preview_approval(approval.id)
    assert preview["dry_run"] is True
    assert preview["will_execute"] is False
    assert controller.snapshot()["approvals"][0]["status"] == "pending"

    controller._expire_approvals(now=time.time() + 61)
    assert controller.snapshot()["approvals"][0]["status"] == "expired"
    with pytest.raises(ValueError, match="already resolved"):
        controller.resolve_approval({"id": approval.id, "decision": "approved"})


def test_runtime_approval_links_ares_id_and_continues_exact_owner_run(tmp_path):
    class ApprovalAdapter(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.continuations = []

        def start_run(self, agent, prompt, session_id, emit, cancel):
            emit("approval_required", {
                "approval_id": "jaeger-approval-1",
                "owner": "jaeger",
                "owner_run_id": "jaeger-run-1",
                "owner_approval_id": "jaeger-approval-1",
                "owner_cursor": "cursor-after-approval",
                "operation": "calendar.create",
                "description": "Create one calendar event",
                "scope": "Calendar event 'Test' at 10:00",
                "benefit": "Records the requested appointment.",
                "risks": ["Creates an externally visible calendar record."],
                "duration": "One action",
                "reversible": "Yes, by deleting the event.",
                "safer_alternative": "Return an event draft without creating it.",
            })
            return AdapterResult("waiting", "jaeger-session")

        def continue_runtime_run(
            self, agent, owner_run_id, owner_approval_id, owner_cursor,
            decision, session_id, emit, cancel,
        ):
            self.continuations.append({
                "owner_run_id": owner_run_id,
                "owner_approval_id": owner_approval_id,
                "owner_cursor": owner_cursor,
                "decision": decision,
                "session_id": session_id,
            })
            return AdapterResult("finished\nARES_STATUS: complete", session_id)

    adapter = ApprovalAdapter()
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "jaeger", "runtime": "jaeger", "name": "Jaeger",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    goal = controller.create_goal({"agent_id": "jaeger", "objective": "create event"})
    first = controller.wake("jaeger", goal_id=goal["id"])
    first = wait_for_run(controller, first["id"])
    assert first["status"] == "approval_required"

    approval = controller.snapshot()["approvals"][0]
    event = next(
        row for row in controller.snapshot()["events"]
        if row["run_id"] == first["id"] and row["type"] == "approval_required"
    )
    assert event["data"]["approval_id"] == approval["id"]
    assert event["data"]["owner_approval_id"] == "jaeger-approval-1"

    resolved = controller.resolve_approval({"id": approval["id"], "decision": "approved"})
    resumed = wait_for_run(controller, resolved["resumed_run_id"])
    assert resumed["status"] == "complete"
    assert adapter.continuations == [{
        "owner_run_id": "jaeger-run-1",
        "owner_approval_id": "jaeger-approval-1",
        "owner_cursor": "cursor-after-approval",
        "decision": "approved",
        "session_id": "jaeger-session",
    }]
    assert controller._goal(goal["id"])["status"] == "complete"


def test_jaeger_new_goals_receive_unique_owner_sessions(monkeypatch):
    adapter = JaegerAdapter(runner_url="http://jaeger.invalid")
    requests = []

    def request(method, path, payload=None):
        requests.append((method, path, payload))
        if method == "POST" and path == "/v1/runs":
            return {"run_id": f"run-{len([row for row in requests if row[1] == '/v1/runs'])}"}
        if path.endswith("/events"):
            return {"events": [], "cursor": "done"}
        if method == "GET" and path.startswith("/v1/runs/"):
            return {"status": "completed", "terminal_state": "completed"}
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(adapter, "_request", request)
    agent = Agent.from_dict({
        "id": "jaeger", "runtime": "jaeger", "name": "Jaeger",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    for _ in range(2):
        result = adapter.start_run(agent, "work", "", lambda *_: None, threading.Event())
        assert result.error == ""
    session_ids = [payload["session_id"] for method, path, payload in requests if method == "POST" and path == "/v1/runs"]
    assert len(session_ids) == 2
    assert session_ids[0] != session_ids[1]
    assert all(value.startswith("ares-jaeger-") for value in session_ids)


def test_reconcile_closes_goals_only_from_terminal_evidence(tmp_path):
    store = AutomationStore(tmp_path / "automation.json")
    state = store.read()
    now = time.time()
    state["goals"] = [
        {"id": "complete-goal", "agent_id": "hermes", "objective": "done", "status": "active", "created_at": 1, "updated_at": 1},
        {"id": "fresh-goal", "agent_id": "hermes", "objective": "new", "status": "active", "created_at": now, "updated_at": now},
    ]
    state["runs"] = [{
        "id": "complete-run", "agent_id": "hermes", "goal_id": "complete-goal",
        "trigger": "manual", "policy_version": 1, "created_at": 1,
        "status": "complete", "attempt": 1, "session_id": "session",
        "result": "done", "error": "", "started_at": 1, "finished_at": 2,
    }]
    store.update(lambda current: current.update(state))
    controller = AutomationService(
        store=store, adapters={"hermes": FakeAdapter(), "jaeger": FakeAdapter()},
    )
    goals = {row["id"]: row for row in controller.snapshot()["goals"]}
    assert goals["complete-goal"]["status"] == "complete"
    assert goals["complete-goal"]["terminal_reason"] == "latest run is complete"
    assert goals["fresh-goal"]["status"] == "active"


def test_reconcile_times_out_unleased_and_nonprogressing_goals(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_GOAL_IDLE_TIMEOUT_SECONDS", "900")
    store = AutomationStore(tmp_path / "automation.json")
    state = store.read()
    state["goals"] = [
        {"id": "unleased", "agent_id": "hermes", "objective": "old", "status": "active", "created_at": 1, "updated_at": 1},
        {"id": "stalled", "agent_id": "hermes", "objective": "old", "status": "active", "created_at": 1, "updated_at": 1},
    ]
    state["runs"] = [{
        "id": "stalled-run", "agent_id": "hermes", "goal_id": "stalled",
        "trigger": "manual", "policy_version": 1, "created_at": 2,
        "status": "continue", "attempt": 1, "session_id": "session",
        "result": "partial", "error": "", "started_at": 2, "finished_at": 3,
    }]
    store.update(lambda current: current.update(state))
    controller = AutomationService(
        store=store, adapters={"hermes": FakeAdapter(), "jaeger": FakeAdapter()},
    )
    controller.reconcile(now=1000)
    snapshot = controller.snapshot()
    assert {row["status"] for row in snapshot["goals"]} == {"timed_out"}
    assert snapshot["runs"][0]["status"] == "timed_out"


def test_reconcile_repairs_phantom_approval_run_from_terminal_marker(tmp_path):
    store = AutomationStore(tmp_path / "automation.json")
    state = store.read()
    state["goals"] = [{
        "id": "blocked-goal", "agent_id": "jaeger", "objective": "restart",
        "status": "blocked", "created_at": 1, "updated_at": 3,
    }]
    state["runs"] = [{
        "id": "legacy-run", "agent_id": "jaeger", "goal_id": "blocked-goal",
        "trigger": "approval", "policy_version": 1, "created_at": 1,
        "status": "approval_required", "attempt": 1, "session_id": "session",
        "result": "Operator action is required.\nARES_STATUS: blocked",
        "error": "", "started_at": 1, "finished_at": 2,
    }]
    store.update(lambda current: current.update(state))

    controller = AutomationService(
        store=store, adapters={"hermes": FakeAdapter(), "jaeger": FakeAdapter()},
    )

    run = controller.snapshot()["runs"][0]
    assert run["status"] == "blocked"
    assert run["finished_at"] == 2
    assert run["error"] == "reconciled from explicit terminal runtime evidence"


def test_catalog_uses_one_gateway_and_run_has_trace_id(tmp_path):
    controller = service(tmp_path)
    catalog = controller.list_integrations()
    assert catalog["strategy"] == "single-ares-gateway"
    assert catalog["alternate_gateways_enabled"] is False
    assert next(row for row in catalog["integrations"] if row["id"] == "docker-mcp")["mode"] == "disabled"

    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "trace this"})
    run = controller.wake("hermes", goal_id=goal["id"])
    assert len(run["trace_id"]) == 32
    wait_for_run(controller, run["id"])
    started = next(row for row in controller.snapshot()["events"] if row["type"] == "run_started")
    assert started["data"]["trace_id"] == run["trace_id"]
