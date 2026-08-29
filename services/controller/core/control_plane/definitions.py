"""Versioned definitions for independently owned agent runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ResourceKind = Literal["model", "tool", "memory", "session", "credential"]
AccessMode = Literal["use", "read", "write", "delegate"]


@dataclass(frozen=True)
class SharingGrant:
    resource: ResourceKind
    resource_id: str
    grantee: str
    modes: tuple[AccessMode, ...] = ("use",)
    expires_at: float | None = None
    approval_required: bool = False
    credential_reference: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SharingGrant":
        resource = str(raw.get("resource") or "")
        if resource not in {"model", "tool", "memory", "session", "credential"}:
            raise ValueError(f"unsupported resource kind: {resource}")
        resource_id = str(raw.get("resource_id") or "").strip()
        grantee = str(raw.get("grantee") or "").strip()
        if not resource_id or not grantee:
            raise ValueError("resource_id and grantee are required")
        modes = tuple(str(value) for value in (raw.get("modes") or ["use"]))
        if not modes or any(value not in {"use", "read", "write", "delegate"} for value in modes):
            raise ValueError("grant contains an unsupported access mode")
        reference = str(raw.get("credential_reference") or "").strip() or None
        if resource == "credential" and not reference:
            raise ValueError("credential grants require an opaque credential_reference")
        if resource != "credential" and reference:
            raise ValueError("credential_reference is valid only for credential grants")
        return cls(
            resource=resource, resource_id=resource_id, grantee=grantee,
            modes=modes, expires_at=raw.get("expires_at"),
            approval_required=bool(raw.get("approval_required", False)),
            credential_reference=reference,
        )


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    runtime: Literal["hermes", "jaeger"]
    enabled: bool = True
    ollama_base_url: str = "http://192.168.64.1:11434/v1"
    heartbeat_enabled: bool = True
    schedules_enabled: bool = True
    grants: tuple[SharingGrant, ...] = field(default_factory=tuple)
    policy_version: int = 1

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentDefinition":
        agent_id = str(raw.get("id") or "").strip()
        runtime = str(raw.get("runtime") or "").strip()
        if not agent_id or runtime not in {"hermes", "jaeger"}:
            raise ValueError("agent id and supported runtime are required")
        url = str(raw.get("ollama_base_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("ollama_base_url must be an HTTP(S) URL")
        return cls(
            id=agent_id, runtime=runtime, enabled=bool(raw.get("enabled", True)),
            ollama_base_url=url,
            heartbeat_enabled=bool(raw.get("heartbeat_enabled", True)),
            schedules_enabled=bool(raw.get("schedules_enabled", True)),
            grants=tuple(SharingGrant.from_dict(row) for row in (raw.get("grants") or [])),
            policy_version=int(raw.get("policy_version") or 1),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GrantDecision:
    allowed: bool
    reason: str
    approval_required: bool = False
    credential_reference: str | None = None
