"""Versioned, secret-free automation records owned by ARES."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..runtimes import is_durable_runtime, normalize_runtime_id

#: Runtime ids are validated against ``core.runtimes`` rather than frozen into
#: a Literal here, so a newly registered runtime does not need a type edit.
Runtime = str
RunStatus = Literal[
    "queued", "running", "continue", "complete", "blocked",
    "approval_required", "failed", "paused", "cancelled", "timed_out",
]


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    runtime: Runtime
    identity: str
    model: str
    workspace: str
    model_provider: str = "owner-default"
    model_location: str = "owner-default"
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
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", agent_id):
            raise ValueError("a valid agent id is required")
        runtime = normalize_runtime_id(runtime)
        if not runtime:
            raise ValueError(f"unknown runtime: {raw.get('runtime')!r}")
        # An agent record is a standing grant of goals, run leases, and
        # approvals, so a registered-but-unpromoted runtime is refused here
        # rather than failing later at dispatch with no adapter.
        if not is_durable_runtime(runtime):
            raise ValueError(f"runtime {runtime!r} is not enabled for durable agent runs")
        if any(not str(ref).startswith("keychain://") for ref in raw.get("credential_references") or []):
            raise ValueError("credentials must be opaque keychain:// references")
        heartbeat = int(raw.get("heartbeat_minutes") or 15)
        timeout = int(raw.get("timeout_seconds") or 900)
        if heartbeat < 1 or timeout < 10:
            raise ValueError("heartbeat_minutes and timeout_seconds are below safe minimums")
        model = str(raw.get("model") or "").strip()
        location = str(raw.get("model_location") or "").strip().lower()
        # Preserve the old explicit test/config shorthands without guessing
        # the location of a real model id. Unknown is deliberately fail-closed
        # for local-context routing.
        if not location and model.lower() in {"local", "cloud"}:
            location = model.lower()
        location = location or "owner-default"
        if location not in {"local", "cloud", "owner-default"}:
            raise ValueError("model_location must be local, cloud, or owner-default")
        provider = str(raw.get("model_provider") or "").strip().lower()
        if not provider:
            provider = "ollama-local" if location == "local" else (
                "ollama-cloud" if location == "cloud" else "owner-default"
            )
        return cls(
            id=agent_id,
            name=str(raw.get("name") or agent_id).strip(),
            runtime=runtime,
            identity=str(raw.get("identity") or "Autonomous assistant").strip(),
            model=model,
            workspace=str(raw.get("workspace") or "/workspace").strip(),
            model_provider=provider,
            model_location=location,
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
    thread_id: str = ""
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SystemThread:
    id: str
    title: str
    selected_agent_id: str
    created_at: float
    updated_at: float
    status: str = "active"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadMessage:
    id: str
    thread_id: str
    role: str
    content: str
    created_at: float
    agent_id: str = ""
    goal_id: str = ""
    run_id: str = ""
    status: str = ""

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
    trace_id: str = ""

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
    kind: str = "run"
    subject_id: str = ""
    benefit: str = ""
    risks: tuple[str, ...] = ()
    scope: str = ""
    duration: str = ""
    reversible: str = ""
    safer_alternative: str = ""
    expires_at: float | None = None
    requesting_agent: str = ""
    provider: str = ""
    data_destination: str = ""
    payload_sha256: str = ""
    consumed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfigurationChange:
    """ARES-owned request to configure an independently owned runtime."""

    id: str
    agent_id: str
    desired: dict[str, Any]
    status: str = "pending"
    created_at: float = 0.0
    resolved_at: float | None = None
    applied_at: float | None = None
    error: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
