"""Durable, fail-closed ARES autonomous execution service."""

from __future__ import annotations

import hashlib
import posixpath
import re
import os
import threading
import time
import uuid
from typing import Any

from .adapters import AgentAdapter, HermesAdapter, JaegerAdapter
from .models import Agent, Approval, ConfigurationChange, Goal, Run, RunEvent
from .store import AutomationStore


class AutomationService:
    def __init__(self, store: AutomationStore | None = None, adapters: dict[str, AgentAdapter] | None = None) -> None:
        self.store = store or AutomationStore()
        self.adapters = adapters or {"hermes": HermesAdapter(), "jaeger": JaegerAdapter()}
        self._guard = threading.RLock()
        self._agent_locks: dict[str, threading.Lock] = {}
        self._cancellations: dict[str, threading.Event] = {}
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._recover_interrupted_runs()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    def snapshot(self) -> dict[str, Any]:
        return self.store.read()

    def list_agents(self) -> list[dict[str, Any]]:
        return self.snapshot()["agents"]

    def put_agent(self, raw: dict[str, Any]) -> dict[str, Any]:
        agent = Agent.from_dict(raw)
        def update(state: dict[str, Any]) -> None:
            state["agents"] = [row for row in state["agents"] if row["id"] != agent.id] + [agent.as_dict()]
        self.store.update(update)
        return agent.as_dict()

    def probe_agent(self, agent_id: str) -> dict[str, Any]:
        agent = self._agent(agent_id)
        return self.adapters[agent.runtime].probe(agent)

    def inspect_agent_configuration(self, agent_id: str) -> dict[str, Any]:
        agent = self._agent(agent_id)
        current = self.adapters[agent.runtime].inspect_configuration(agent)
        changes = [
            row for row in self.snapshot()["configuration_changes"]
            if row["agent_id"] == agent_id
        ]
        return {"agent_id": agent_id, "current": current, "changes": list(reversed(changes))}

    def request_agent_configuration(self, agent_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        agent = self._agent(agent_id)
        if agent.runtime != "hermes":
            raise ValueError("configuration management is not available for this runtime")
        desired = self._validate_configuration(raw)
        now = time.time()
        with self._guard:
            state = self.snapshot()
            if any(
                row["agent_id"] == agent_id and row["status"] in {"pending", "applying"}
                for row in state["configuration_changes"]
            ):
                raise RuntimeError("another configuration change is pending for this agent")
            change = ConfigurationChange(
                id=self._id("config"), agent_id=agent_id, desired=desired,
                created_at=now,
            )
            summary = []
            if "soul" in desired:
                summary.append("identity document")
            if desired.get("workspaces"):
                summary.append(f"{len(desired['workspaces'])} workspace registration(s)")
            approval = Approval(
                id=self._id("approval"), run_id="", operation="configure_agent",
                reason=f"Apply {', '.join(summary)} to {agent.name} through its runtime API",
                created_at=now, kind="configuration", subject_id=change.id,
            )
            def update(current: dict[str, Any]) -> None:
                current["configuration_changes"].append(change.as_dict())
                current["approvals"].append(approval.as_dict())
            self.store.update(update)
        return {"change": change.as_dict(), "approval": approval.as_dict()}

    def create_goal(self, raw: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(raw.get("agent_id") or "").strip()
        self._agent(agent_id)
        objective = str(raw.get("objective") or "").strip()
        if not objective:
            raise ValueError("goal objective is required")
        now = time.time()
        goal = Goal(id=str(raw.get("id") or self._id("goal")), agent_id=agent_id, objective=objective, created_at=now, updated_at=now)
        self.store.update(lambda state: state["goals"].append(goal.as_dict()))
        return goal.as_dict()

    def wake(self, agent_id: str, *, goal_id: str = "", trigger: str = "manual", idempotency_key: str = "", attempt: int = 1) -> dict[str, Any]:
        with self._guard:
            state = self.snapshot()
            if state["paused"]:
                raise RuntimeError("ARES is paused")
            agent = self._agent(agent_id, state)
            if not agent.enabled:
                raise RuntimeError("agent is disabled")
            goal = next((row for row in state["goals"] if row["id"] == goal_id), None) if goal_id else next((row for row in state["goals"] if row["agent_id"] == agent_id and row["status"] == "active"), None)
            if goal is None:
                raise ValueError("active goal not found")
            if idempotency_key:
                existing = next((row for row in state["runs"] if row.get("idempotency_key") == idempotency_key), None)
                if existing:
                    return existing
            if any(row["agent_id"] == agent_id and row["status"] in {"queued", "running"} for row in state["runs"]):
                raise RuntimeError("another run is active for this agent")
            run = Run(id=self._id("run"), agent_id=agent_id, goal_id=goal["id"], trigger=trigger, policy_version=agent.policy_version, created_at=time.time(), attempt=max(1, attempt))
            record = {**run.as_dict(), "idempotency_key": idempotency_key}
            self.store.update(lambda current: current["runs"].append(record))
        cancel = threading.Event()
        self._cancellations[run.id] = cancel
        threading.Thread(target=self._execute, args=(run.id, cancel), name=f"ares-{run.id}", daemon=True).start()
        return record

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        event = self._cancellations.get(run_id)
        if event:
            event.set()
        agent = self._agent(run["agent_id"])
        self.adapters[agent.runtime].cancel_run(str(run.get("session_id") or ""))
        self._patch_run(run_id, status="cancelled", finished_at=time.time())
        self._event(run_id, "run_failed", {"error": "cancelled"})
        return self._run(run_id)

    def pause(self, paused: bool) -> dict[str, Any]:
        self.store.update(lambda state: state.__setitem__("paused", bool(paused)))
        return {"paused": bool(paused)}

    def tick(self, now: float | None = None) -> list[dict[str, Any]]:
        """Lease due heartbeat/retry work without creating duplicate wakes."""
        current_time = time.time() if now is None else now
        created: list[dict[str, Any]] = []
        with self._guard:
            state = self.snapshot()
            if state["paused"]:
                return created
            for raw_agent in state["agents"]:
                agent = Agent.from_dict(raw_agent)
                if not agent.enabled:
                    continue
                goal = next((row for row in state["goals"] if row["agent_id"] == agent.id and row["status"] == "active"), None)
                if goal is None:
                    continue
                runs = [row for row in state["runs"] if row["agent_id"] == agent.id and row["goal_id"] == goal["id"]]
                if any(row["status"] in {"queued", "running"} for row in runs):
                    continue
                latest = runs[-1] if runs else None
                if latest and latest["status"] in {"complete", "blocked", "approval_required", "paused", "cancelled"}:
                    continue
                delay = agent.heartbeat_minutes * 60
                attempt = 1
                trigger = "heartbeat"
                if latest:
                    finished = float(latest.get("finished_at") or latest.get("created_at") or current_time)
                    if latest["status"] == "failed":
                        attempt = int(latest.get("attempt") or 1) + 1
                        if attempt > 3:
                            continue
                        trigger = "retry"
                        delay = min(delay, 30 * (2 ** (attempt - 2)))
                    if current_time < finished + delay:
                        continue
                bucket = int(current_time // max(delay, 1))
                created.append(self.wake(agent.id, goal_id=goal["id"], trigger=trigger, idempotency_key=f"{trigger}:{agent.id}:{goal['id']}:{bucket}", attempt=attempt))
        return created

    def start_scheduler(self) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        interval = max(1, int(os.environ.get("ARES_AUTOMATION_TICK_SECONDS", "15")))
        def loop() -> None:
            while not self._scheduler_stop.wait(interval):
                try:
                    self.tick()
                except Exception:
                    continue
        self._scheduler_thread = threading.Thread(target=loop, name="ares-automation-scheduler", daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        self._scheduler_stop.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=2)
        self._scheduler_thread = None

    def resolve_approval(self, raw: dict[str, Any]) -> dict[str, Any]:
        approval_id = str(raw.get("id") or "")
        decision = str(raw.get("decision") or "").lower()
        if decision not in {"approved", "denied"}:
            raise ValueError("decision must be approved or denied")
        now = time.time()
        current = next((row for row in self.snapshot()["approvals"] if row["id"] == approval_id), None)
        if current is None:
            raise ValueError("approval not found")
        if current.get("status") != "pending":
            raise ValueError("approval is already resolved")
        if current.get("kind") == "configuration":
            return self._resolve_configuration_approval(current, decision, now)

        def update(state: dict[str, Any]) -> None:
            found = False
            for row in state["approvals"]:
                if row["id"] == approval_id:
                    row.update(status=decision, resolved_at=now)
                    found = True
            if not found:
                raise ValueError("approval not found")
        state = self.store.update(update)
        resolved = next(row for row in state["approvals"] if row["id"] == approval_id)
        if decision == "approved":
            prior = self._run(resolved["run_id"])
            resumed = self.wake(prior["agent_id"], goal_id=prior["goal_id"], trigger="approval", idempotency_key=f"approval:{approval_id}")
            return {**resolved, "resumed_run_id": resumed["id"]}
        return resolved

    def _resolve_configuration_approval(
        self, approval: dict[str, Any], decision: str, now: float,
    ) -> dict[str, Any]:
        with self._guard:
            state = self.snapshot()
            current_approval = next(
                (row for row in state["approvals"] if row["id"] == approval["id"]), None,
            )
            if current_approval is None or current_approval.get("status") != "pending":
                raise ValueError("approval is already resolved")
            change = next(
                (
                    row for row in state["configuration_changes"]
                    if row["id"] == str(current_approval.get("subject_id") or "")
                ),
                None,
            )
            if change is None or change.get("status") != "pending":
                raise ValueError("configuration change is not pending")
            if decision == "denied":
                def deny(current: dict[str, Any]) -> None:
                    for row in current["approvals"]:
                        if row["id"] == approval["id"]:
                            row.update(status="denied", resolved_at=now)
                    for row in current["configuration_changes"]:
                        if row["id"] == change["id"]:
                            row.update(status="denied", resolved_at=now)
                state = self.store.update(deny)
                return next(row for row in state["approvals"] if row["id"] == approval["id"])

            def lease(current: dict[str, Any]) -> None:
                for row in current["approvals"]:
                    if row["id"] == approval["id"]:
                        row.update(status="applying")
                for row in current["configuration_changes"]:
                    if row["id"] == change["id"]:
                        row.update(status="applying")
            self.store.update(lease)

        agent = self._agent(change["agent_id"])
        try:
            effective = self.adapters[agent.runtime].apply_configuration(agent, change["desired"])
            evidence = self._configuration_evidence(effective)
        except Exception as exc:
            failed_at = time.time()
            error = str(exc)
            def fail(state: dict[str, Any]) -> None:
                for row in state["approvals"]:
                    if row["id"] == approval["id"]:
                        row.update(status="failed", resolved_at=failed_at)
                for row in state["configuration_changes"]:
                    if row["id"] == change["id"]:
                        row.update(status="failed", resolved_at=failed_at, error=error)
            self.store.update(fail)
            raise RuntimeError(f"agent configuration failed: {error}") from exc

        applied_at = time.time()
        def apply(state: dict[str, Any]) -> None:
            for row in state["approvals"]:
                if row["id"] == approval["id"]:
                    row.update(status="approved", resolved_at=applied_at)
            for row in state["configuration_changes"]:
                if row["id"] == change["id"]:
                    row.update(
                        status="applied", resolved_at=applied_at,
                        applied_at=applied_at, error="", evidence=evidence,
                    )
        state = self.store.update(apply)
        resolved = next(row for row in state["approvals"] if row["id"] == approval["id"])
        return {**resolved, "configuration_change_id": change["id"], "evidence": evidence}

    @staticmethod
    def _validate_configuration(raw: dict[str, Any]) -> dict[str, Any]:
        desired: dict[str, Any] = {}
        if "soul" in raw:
            soul = raw.get("soul")
            if not isinstance(soul, str) or not soul.strip():
                raise ValueError("soul must be a non-empty string")
            if "\x00" in soul or len(soul.encode("utf-8")) > 65536:
                raise ValueError("soul is invalid or exceeds 64 KiB")
            desired["soul"] = soul.rstrip() + "\n"
        if "workspaces" in raw:
            rows = raw.get("workspaces")
            if not isinstance(rows, list) or len(rows) > 32:
                raise ValueError("workspaces must be a list of at most 32 paths")
            normalized: list[str] = []
            for value in rows:
                path = str(value or "").strip()
                if "\x00" in path or not path.startswith("/"):
                    raise ValueError("workspace paths must be absolute container paths")
                path = posixpath.normpath(path)
                if path != "/workspace" and not path.startswith("/workspace/"):
                    raise ValueError("Hermes workspaces must be inside the approved /workspace mount")
                if path not in normalized:
                    normalized.append(path)
            desired["workspaces"] = normalized
        if not desired:
            raise ValueError("soul or workspaces is required")
        return desired

    @staticmethod
    def _configuration_evidence(effective: dict[str, Any]) -> dict[str, Any]:
        soul = str(effective.get("soul") or "")
        return {
            "owner": str(effective.get("owner") or ""),
            "endpoint": str(effective.get("endpoint") or ""),
            "soul_sha256": hashlib.sha256(soul.encode("utf-8")).hexdigest(),
            "workspaces": [
                str(row.get("path") or "") for row in effective.get("workspaces") or []
                if isinstance(row, dict) and row.get("path")
            ],
        }

    def _recover_interrupted_runs(self) -> None:
        now = time.time()
        interrupted: list[str] = []
        def update(state: dict[str, Any]) -> None:
            for row in state["runs"]:
                if row.get("status") in {"queued", "running"}:
                    row.update(status="continue", error="controller restarted; safe resume pending", finished_at=now)
                    interrupted.append(row["id"])
            interrupted_changes = {
                row["id"] for row in state["configuration_changes"]
                if row.get("status") == "applying"
            }
            for row in state["configuration_changes"]:
                if row["id"] in interrupted_changes:
                    row.update(
                        status="failed", resolved_at=now,
                        error="controller restarted during configuration; inspect runtime state before retrying",
                    )
            for row in state["approvals"]:
                if row.get("subject_id") in interrupted_changes and row.get("status") == "applying":
                    row.update(status="failed", resolved_at=now)
        self.store.update(update)
        for run_id in interrupted:
            self._event(run_id, "checkpoint", {"reason": "controller_restart", "resume": "pending"})

    def _execute(self, run_id: str, cancel: threading.Event) -> None:
        run = self._run(run_id)
        lock = self._agent_locks.setdefault(run["agent_id"], threading.Lock())
        if not lock.acquire(blocking=False):
            self._patch_run(run_id, status="failed", error="another run is active for this agent", finished_at=time.time())
            self._event(run_id, "run_failed", {"error": "agent lease unavailable"})
            return
        try:
            self._patch_run(run_id, status="running", started_at=time.time())
            self._event(run_id, "run_started", {"trigger": run["trigger"], "policy_version": run["policy_version"]})
            agent = self._agent(run["agent_id"])
            goal = self._goal(run["goal_id"])
            previous = next((row for row in reversed(self.snapshot()["runs"]) if row["agent_id"] == agent.id and row["id"] != run_id and row.get("session_id")), None)
            session_id = str(previous.get("session_id") or "") if previous else ""
            prompt = self._prompt(agent, goal, run)
            approval_seen = False

            def emit(kind: str, data: dict[str, Any]) -> None:
                nonlocal approval_seen
                self._event(run_id, kind, data)
                if kind == "approval_required":
                    approval_seen = True
                    approval = Approval(id=self._id("approval"), run_id=run_id, operation="runtime_request", reason="Agent requested a consequential action", created_at=time.time())
                    self.store.update(lambda state: state["approvals"].append(approval.as_dict()))

            result = self.adapters[agent.runtime].start_run(agent, prompt, session_id, emit, cancel)
            if cancel.is_set() or result.error == "cancelled":
                status = "cancelled"
            elif approval_seen:
                status = "approval_required"
            elif result.error:
                status = "failed"
            else:
                status = self._status(result.text)
            self._patch_run(run_id, status=status, session_id=result.session_id, result=result.text, error=result.error, finished_at=time.time())
            self._event(run_id, "run_failed" if status in {"failed", "cancelled"} else "run_completed", {"status": status, "text": result.text, "error": result.error})
            if status == "complete":
                self._patch_goal(goal["id"], status="complete", updated_at=time.time())
        except Exception as exc:
            self._patch_run(run_id, status="failed", error=str(exc), finished_at=time.time())
            self._event(run_id, "run_failed", {"error": str(exc)})
        finally:
            self._cancellations.pop(run_id, None)
            lock.release()

    @staticmethod
    def _prompt(agent: Agent, goal: dict[str, Any], run: dict[str, Any]) -> str:
        return (
            f"Identity: {agent.identity}\nGoal: {goal['objective']}\n"
            f"This is ARES run {run['id']}. Work autonomously within your configured tools and workspace. "
            "Do not claim approval you did not receive. End with exactly one status marker: "
            "ARES_STATUS: complete, ARES_STATUS: continue, ARES_STATUS: blocked, or ARES_STATUS: approval_required."
        )

    @staticmethod
    def _status(text: str) -> str:
        match = re.search(r"ARES_STATUS:\s*(complete|continue|blocked|approval_required)", text, re.I)
        return match.group(1).lower() if match else "continue"

    def _event(self, run_id: str, kind: str, data: dict[str, Any]) -> None:
        allowed = {"run_started", "text_delta", "reasoning_delta", "tool_requested", "tool_result", "approval_required", "checkpoint", "run_completed", "run_failed"}
        event = RunEvent(id=self._id("event"), run_id=run_id, type=kind if kind in allowed else "checkpoint", created_at=time.time(), data=data)
        self.store.update(lambda state: state["events"].append(event.as_dict()))

    def _agent(self, agent_id: str, state: dict[str, Any] | None = None) -> Agent:
        row = next((row for row in (state or self.snapshot())["agents"] if row["id"] == agent_id), None)
        if row is None:
            raise ValueError("agent not found")
        return Agent.from_dict(row)

    def _goal(self, goal_id: str) -> dict[str, Any]:
        row = next((row for row in self.snapshot()["goals"] if row["id"] == goal_id), None)
        if row is None:
            raise ValueError("goal not found")
        return row

    def _run(self, run_id: str) -> dict[str, Any]:
        row = next((row for row in self.snapshot()["runs"] if row["id"] == run_id), None)
        if row is None:
            raise ValueError("run not found")
        return row

    def _configuration_change(self, change_id: str) -> dict[str, Any]:
        row = next(
            (row for row in self.snapshot()["configuration_changes"] if row["id"] == change_id),
            None,
        )
        if row is None:
            raise ValueError("configuration change not found")
        return row

    def _patch_run(self, run_id: str, **values: Any) -> None:
        self.store.update(lambda state: [row.update(values) for row in state["runs"] if row["id"] == run_id])

    def _patch_goal(self, goal_id: str, **values: Any) -> None:
        self.store.update(lambda state: [row.update(values) for row in state["goals"] if row["id"] == goal_id])
