"""Agent.approval_tools must gate consequential mutations, not only be stored."""
from __future__ import annotations

import pytest

from core.automation.adapters import AdapterResult, AgentAdapter, default_adapters
from core.automation.models import tool_requires_approval
from core.automation.service import AutomationService
from core.automation.store import AutomationStore
from core.runtimes import durable_runtime_ids, is_durable_runtime


class GatingAdapter(AgentAdapter):
    def __init__(self, tool: str) -> None:
        self.tool = tool
        self.continuations: list[dict] = []
        self.started = 0

    def probe(self, agent):
        return {"available": True, "owner": agent.runtime}

    def start_run(self, agent, prompt, session_id, emit, cancel):
        self.started += 1
        emit("tool_requested", {"tool": self.tool, "command": self.tool})
        return AdapterResult("used tool", session_id or "session")

    def continue_runtime_run(
        self, agent, owner_run_id, owner_approval_id, owner_cursor,
        decision, session_id, emit, cancel,
    ):
        self.continuations.append({
            "owner_run_id": owner_run_id,
            "decision": decision,
            "session_id": session_id,
        })
        return AdapterResult("finished\nARES_STATUS: complete", session_id)

    def cancel_run(self, session_id):
        return None


def wait_for_run(controller, run_id):
    import time
    for _ in range(100):
        run = next(row for row in controller.snapshot()["runs"] if row["id"] == run_id)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_tool_requires_approval_matches_dotted_capability_names():
    tools = ("publish", "delete", "credentials")
    assert tool_requires_approval(tools, "publish") is True
    assert tool_requires_approval(tools, "workspace.write") is False
    assert tool_requires_approval(("write",), "workspace.write") is True
    assert tool_requires_approval(tools, "search") is False
    assert tool_requires_approval((), "publish") is False


def test_gated_tool_requested_pauses_for_ares_approval(tmp_path):
    adapter = GatingAdapter("publish")
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
        "approval_tools": ["publish", "delete", "credentials"],
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "publish a note"})
    run = wait_for_run(controller, controller.wake("hermes", goal_id=goal["id"])["id"])
    assert run["status"] == "approval_required"
    approval = controller.snapshot()["approvals"][0]
    assert approval["operation"] == "publish"
    assert approval["status"] == "pending"
    event = next(
        row for row in controller.snapshot()["events"]
        if row["run_id"] == run["id"] and row["type"] == "approval_required"
    )
    assert event["data"]["gated_by"] == "approval_tools"
    assert adapter.started == 1
    assert adapter.continuations == []


def test_ungated_tool_requested_does_not_raise_approval(tmp_path):
    adapter = GatingAdapter("search")
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
        "approval_tools": ["publish", "delete", "credentials"],
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "search notes"})
    run = wait_for_run(controller, controller.wake("hermes", goal_id=goal["id"])["id"])
    assert run["status"] == "complete"
    assert controller.snapshot()["approvals"] == []
    assert any(
        row["type"] == "tool_requested" and row["data"]["tool"] == "search"
        for row in controller.snapshot()["events"]
    )


def test_default_adapters_raises_when_durable_runtime_lacks_adapter(monkeypatch):
    import core.automation.adapters as adapters

    monkeypatch.setattr(adapters, "ADAPTER_TYPES", {
        "hermes": adapters.HermesAdapter,
        "jaeger": adapters.JaegerAdapter,
        "openclaw": adapters.OpenClawAdapter,
    })
    missing = [rid for rid in durable_runtime_ids() if rid not in adapters.ADAPTER_TYPES]
    assert missing, "fixture needs a durable runtime without an adapter"
    with pytest.raises(RuntimeError, match="no adapter"):
        adapters.default_adapters()


def test_durable_cli_runtimes_keep_named_adapters():
    from core.automation.adapters import (
        ADAPTER_TYPES,
        ClaudeAdapter,
        CodexAdapter,
        GeminiAdapter,
        GrokAdapter,
    )

    assert is_durable_runtime("claude")
    assert is_durable_runtime("codex")
    assert is_durable_runtime("gemini")
    assert is_durable_runtime("grok")
    assert not is_durable_runtime("pi")
    assert ADAPTER_TYPES["claude"] is ClaudeAdapter
    assert ADAPTER_TYPES["codex"] is CodexAdapter
    assert ADAPTER_TYPES["gemini"] is GeminiAdapter
    assert ADAPTER_TYPES["grok"] is GrokAdapter
    assert set(default_adapters()) == set(durable_runtime_ids())


def test_gated_approval_does_not_replay_the_prompt(tmp_path):
    adapter = GatingAdapter("delete")
    controller = AutomationService(
        store=AutomationStore(tmp_path / "automation.json"),
        adapters={"hermes": adapter, "jaeger": adapter},
    )
    controller.put_agent({
        "id": "hermes", "runtime": "hermes", "name": "Hermes",
        "identity": "worker", "model": "", "workspace": "/workspace",
        "approval_tools": ["publish", "delete", "credentials"],
    })
    goal = controller.create_goal({"agent_id": "hermes", "objective": "delete a draft"})
    run = wait_for_run(controller, controller.wake("hermes", goal_id=goal["id"])["id"])
    approval = controller.snapshot()["approvals"][0]
    resolved = controller.resolve_approval({"id": approval["id"], "decision": "approved"})
    assert resolved["status"] == "approved"
    assert "resumed_run_id" not in resolved
    assert adapter.started == 1
    assert adapter.continuations == []
    assert wait_for_run(controller, run["id"])["status"] == "approval_required"
