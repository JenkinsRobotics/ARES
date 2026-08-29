"""Versioned, secret-free automation records owned by ARES."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Runtime = Literal["hermes", "jaeger"]
RunStatus = Literal[
    "queued", "running", "continue", "complete", "blocked",
    "approval_required", "failed", "paused", "cancelled",
]


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    runtime: Runtime
    identity: str
    model: str
    workspace: str
    runtime_instance: str = ""
    enabled: bool = True
    heartbeat_minutes: int = 15
    max_turns: int = 30
    timeout_seconds: int = 900
    toolsets: tuple[str, ...] = ()
    approval_tools: tuple[str, ...] = ("publish", "delete", "credentials")
    credential_references: tuple[str, ...] = ()
    policy_version: int = 1

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Agent":
        agent_id = str(raw.get("id") or "").strip()
        runtime = str(raw.get("runtime") or "").strip()
        if not agent_id or runtime not in {"hermes", "jaeger"}:
            raise ValueError("agent id and runtime hermes|jaeger are required")
        if any(not str(ref).startswith("keychain://") for ref in raw.get("credential_references") or []):
            raise ValueError("credentials must be opaque keychain:// references")
        heartbeat = int(raw.get("heartbeat_minutes") or 15)
        timeout = int(raw.get("timeout_seconds") or 900)
        if heartbeat < 1 or timeout < 10:
            raise ValueError("heartbeat_minutes and timeout_seconds are below safe minimums")
        return cls(
            id=agent_id,
            name=str(raw.get("name") or agent_id).strip(),
            runtime=runtime,
            identity=str(raw.get("identity") or "Autonomous assistant").strip(),
            model=str(raw.get("model") or "").strip(),
            workspace=str(raw.get("workspace") or "/workspace").strip(),
            runtime_instance=str(raw.get("runtime_instance") or agent_id).strip(),
            enabled=bool(raw.get("enabled", True)),
            heartbeat_minutes=heartbeat,
            max_turns=max(1, int(raw.get("max_turns") or 30)),
            timeout_seconds=timeout,
            toolsets=tuple(str(row) for row in raw.get("toolsets") or []),
            approval_tools=tuple(str(row) for row in raw.get("approval_tools") or ("publish", "delete", "credentials")),
            credential_references=tuple(str(row) for row in raw.get("credential_references") or []),
            policy_version=max(1, int(raw.get("policy_version") or 1)),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Goal:
    id: str
    agent_id: str
    objective: str
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Run:
    id: str
    agent_id: str
    goal_id: str
    trigger: str
    policy_version: int
    created_at: float
    status: RunStatus = "queued"
    attempt: int = 1
    session_id: str = ""
    result: str = ""
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunEvent:
    id: str
    run_id: str
    type: str
    created_at: float
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Approval:
    id: str
    run_id: str
    operation: str
    reason: str
    status: str = "pending"
    created_at: float = 0.0
    resolved_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
