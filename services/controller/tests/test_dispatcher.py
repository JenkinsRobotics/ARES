from __future__ import annotations

import threading
import time

from core.automation import AutomationService
from core.automation.adapters import AdapterResult, AgentAdapter
from core.automation.dispatcher import (
    REQUIRED_PROBES,
    build_benchmark_record,
    capability_manifest,
    default_dispatcher_config,
    select_agent,
)
from core.automation.models import Agent
from core.automation.store import AutomationStore


class RecordingAdapter(AgentAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def probe(self, _agent):
        return {"available": True}

    def start_run(self, agent, _prompt, session_id, _emit, _cancel: threading.Event):
        self.calls.append((agent.id, session_id))
        return AdapterResult("ok\nARES_STATUS: complete", session_id or f"{agent.id}-session")

    def cancel_run(self, _session_id):
        return None


def agent(agent_id: str, *, location: str = "local") -> dict:
    return {
        "id": agent_id,
        "runtime": agent_id,
        "name": agent_id.title(),
        "identity": "Independent worker",
        "model": "gemma4:latest",
        "model_provider": "ollama-local",
        "model_location": location,
        "workspace": "/workspace",
        "toolsets": ["ares-host"],
    }


def passing_record(agent_id: str, latency: float) -> dict:
    return build_benchmark_record(agent_id, {
        "attempts": 3,
        "successes": 3,
        "median_latency_seconds": latency,
        "probes": {name: True for name in REQUIRED_PROBES},
    })


def wait_for_run(service: AutomationService, run_id: str) -> dict:
    deadline = time.time() + 3
    while time.time() < deadline:
        run = next(row for row in service.snapshot()["runs"] if row["id"] == run_id)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_capability_manifest_is_deterministic_and_a2a_shaped():
    manifest = capability_manifest(Agent.from_dict(agent("hermes")), "https://ares.example")
    assert manifest["protocolVersion"] == "0.3"
    assert manifest["metadata"]["protocols"]["mcp"] == "2025-06-18"
    assert manifest["metadata"]["ragEligible"] is True
    assert manifest["skills"][0]["id"] == "delegated_task"
    assert manifest["supportedInterfaces"][0]["url"].startswith("https://ares.example/")


def test_only_a_100_percent_benchmark_is_qualified():
    failed = build_benchmark_record("hermes", {
        "attempts": 3,
        "successes": 2,
        "probes": {name: True for name in REQUIRED_PROBES},
    })
    assert failed["success_rate"] == 66.67
    assert failed["passed"] is False
    assert passing_record("hermes", 30)["passed"] is True


def test_single_success_is_diagnostic_not_qualification():
    diagnostic = build_benchmark_record("openclaw", {
        "attempts": 1,
        "successes": 1,
        "median_latency_seconds": 30,
        "probes": {name: True for name in REQUIRED_PROBES},
    })
    assert diagnostic["success_rate"] == 100.0
    assert diagnostic["passed"] is False


def test_tier_selection_is_configurable_and_not_a_hardcoded_runtime():
    agents = [agent("hermes"), agent("jaeger")]
    records = [passing_record("hermes", 120), passing_record("jaeger", 10)]
    config = {**default_dispatcher_config(), "tier": "fast"}
    chosen, decision = select_agent(config, agents, records)
    assert chosen == "jaeger"
    assert decision["qualified"] is True

    fixed, fixed_decision = select_agent(
        {**config, "mode": "fixed", "fixed_agent_id": "hermes"}, agents, records,
    )
    assert fixed == "hermes"
    assert fixed_decision["reason"] == "fixed_by_operator"


def test_legacy_single_attempt_record_cannot_select_a_dispatcher():
    agents = [agent("openclaw"), agent("hermes")]
    diagnostic = build_benchmark_record("openclaw", {
        "attempts": 1,
        "successes": 1,
        "median_latency_seconds": 10,
        "probes": {name: True for name in REQUIRED_PROBES},
    })
    diagnostic["passed"] = True  # Simulate a record written by older code.
    chosen, decision = select_agent(default_dispatcher_config(), agents, [diagnostic])
    assert chosen == "hermes"
    assert decision["qualified"] is False


def test_new_thread_defaults_to_ares_dispatcher_and_records_selection(tmp_path):
    adapter = RecordingAdapter()
    service = AutomationService(
        store=AutomationStore(tmp_path / "state.json"),
        adapters={"hermes": adapter, "jaeger": adapter, "openclaw": adapter},
    )
    service.put_agent(agent("hermes"))
    thread = service.create_thread({})
    assert thread["routing_mode"] == "dispatcher"
    sent = service.send_thread_message(thread["id"], {"agent_id": "dispatcher", "content": "hello"})
    wait_for_run(service, sent["run"]["id"])
    assert sent["dispatch"]["selected_agent_id"] == "hermes"
    assert sent["dispatch"]["reason"] == "provisional_unbenchmarked_fallback"
    events = [row for row in service.snapshot()["events"] if row["run_id"] == sent["run"]["id"]]
    assert any(row["data"].get("kind") == "dispatcher_selection" for row in events)


def test_local_model_policy_is_ram_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("ARES_OLLAMA_KEEP_ALIVE", "45s")
    service = AutomationService(
        store=AutomationStore(tmp_path / "state.json"),
        adapters={"hermes": RecordingAdapter(), "jaeger": RecordingAdapter(), "openclaw": RecordingAdapter()},
    )
    policy = service.local_model_policy()
    assert policy["serialized"] is True
    assert policy["max_loaded_models"] == 1
    assert policy["parallel_requests"] == 1
    assert policy["keep_alive"] == "45s"
