"""ARES-owned dispatcher policy, capability registration, and scoring.

The dispatcher is a control-plane role, not another model runtime.  ARES owns
the durable conversation and selects an independently owned execution engine
from measured, versioned evidence.  The selection remains configurable and a
direct ``@agent`` route always wins.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..runtimes import RUNTIME_BY_ID, durable_runtime_ids
from .models import Agent

DISPATCHER_CONTRACT_VERSION = "1.0"
# Protocol version negotiated by the pinned A2A Python handler. This is
# distinct from the ARES dispatcher capability-contract version above.
A2A_PROTOCOL_VERSION = "0.3"
# This is the version the running ARES gateway currently negotiates.  MCP
# discovery remains authoritative; a language model never invents tool names.
MCP_PROTOCOL_VERSION = "2025-06-18"
MIN_QUALIFICATION_ATTEMPTS = 3
TIERS = ("fast", "balanced", "accurate")
REQUIRED_PROBES = (
    "capability_registration",
    "read_only_tool",
    "session_continuity",
    "rag_context",
    "completion",
)


def default_dispatcher_config() -> dict[str, Any]:
    return {
        "version": 1,
        "mode": "automatic",
        "tier": "balanced",
        "fixed_agent_id": "",
        "fallback_order": list(durable_runtime_ids()),
        "require_qualified": True,
        "rag_policy": "local-only",
    }


def normalize_dispatcher_config(raw: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    current = default_dispatcher_config()
    current.update({key: value for key, value in raw.items() if key in current})
    mode = str(current["mode"]).strip().lower()
    tier = str(current["tier"]).strip().lower()
    if mode not in {"automatic", "fixed"}:
        raise ValueError("dispatcher mode must be automatic or fixed")
    if tier not in TIERS:
        raise ValueError("dispatcher tier must be fast, balanced, or accurate")
    enabled_ids = {str(row.get("id") or "") for row in agents if row.get("enabled", True)}
    fixed = str(current.get("fixed_agent_id") or "").strip()
    if mode == "fixed" and fixed not in enabled_ids:
        raise ValueError("fixed dispatcher agent must be enabled")
    requested_order = [str(value).strip() for value in current.get("fallback_order") or []]
    order = [value for value in requested_order if value in enabled_ids]
    order.extend(value for value in durable_runtime_ids() if value in enabled_ids and value not in order)
    current.update(
        mode=mode,
        tier=tier,
        fixed_agent_id=fixed,
        fallback_order=order,
        require_qualified=bool(current.get("require_qualified", True)),
        rag_policy="local-only",
    )
    return current


def capability_manifest(agent: Agent, base_url: str = "") -> dict[str, Any]:
    """Build a deterministic A2A-shaped capability card from observed config."""

    runtime = RUNTIME_BY_ID[agent.runtime]
    endpoint = f"{base_url.rstrip('/')}/api/agents/{agent.id}" if base_url else runtime.endpoint
    toolsets = sorted(set(agent.toolsets))
    skills = [
        {
            "id": "delegated_task",
            "name": "Delegated task execution",
            "description": "Execute an ARES-leased goal and return durable evidence.",
            "tags": [agent.runtime, "ares-governed", "durable"],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ]
    if toolsets:
        skills.append(
            {
                "id": "registered_tool_use",
                "name": "Registered tool use",
                "description": "Use only tools discovered by the owning runtime and allowed by ARES policy.",
                "tags": ["mcp", "tools", *toolsets],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        )
    return {
        "name": agent.name,
        "description": agent.identity,
        "version": DISPATCHER_CONTRACT_VERSION,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "supportedInterfaces": [
            {
                "url": endpoint,
                "protocolBinding": "ARES",
                "protocolVersion": A2A_PROTOCOL_VERSION,
            }
        ],
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "capabilities": {"streaming": True, "stateTransitionHistory": True},
        "skills": skills,
        "metadata": {
            "agentId": agent.id,
            "runtimeOwner": agent.runtime,
            "deployment": runtime.deployment,
            "transport": runtime.transport,
            "modelProvider": agent.model_provider,
            "modelLocation": agent.model_location,
            "ragEligible": agent.model_location == "local",
            "toolsets": toolsets,
            "aresManaged": ["goals", "leases", "routing", "approvals", "audit"],
            "protocols": {"a2a": A2A_PROTOCOL_VERSION, "mcp": MCP_PROTOCOL_VERSION},
        },
    }


def benchmark_prompt(agent: Agent, nonce: str) -> str:
    """Return the common, model-independent registration benchmark prompt."""

    return (
        f"ARES dispatcher capability benchmark {DISPATCHER_CONTRACT_VERSION} for runtime {agent.runtime}.\n"
        "Use only read-only tools. Discover tools from the runtime/MCP interface; do not invent names. "
        "Inspect the requested file once, then answer with one JSON object containing exactly these keys: "
        "schema_version, runtime_id, observed_tools, file_nonce, session_nonce, context_nonce, and status. "
        f"Set schema_version to {DISPATCHER_CONTRACT_VERSION} and runtime_id to exactly {agent.runtime}. "
        "observed_tools must contain actual tool API names, not file paths. Set file_nonce to the nonce read from the file. "
        f"Set session_nonce to {nonce}. Set context_nonce to the nonce found in the supplied ARES context. "
        "Set status to complete only after the read-only tool call succeeds."
    )


def build_benchmark_record(agent_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    probes = raw.get("probes") if isinstance(raw.get("probes"), dict) else {}
    normalized = {name: bool(probes.get(name, False)) for name in REQUIRED_PROBES}
    attempts = max(1, int(raw.get("attempts") or 1))
    successes = int(raw.get("successes") or 0)
    if successes < 0 or successes > attempts:
        raise ValueError("benchmark successes must be between zero and attempts")
    latency = max(0.0, float(raw.get("median_latency_seconds") or 0.0))
    success_score = (successes / attempts) * 100.0
    latency_score = 100.0 / (1.0 + latency / 30.0)
    passed = (
        attempts >= MIN_QUALIFICATION_ATTEMPTS
        and successes == attempts
        and all(normalized.values())
    )
    return {
        "id": f"benchmark_{uuid.uuid4().hex[:16]}",
        "contract_version": DISPATCHER_CONTRACT_VERSION,
        "agent_id": agent_id,
        "model": str(raw.get("model") or ""),
        "model_location": str(raw.get("model_location") or "local"),
        "attempts": attempts,
        "successes": successes,
        "success_rate": round(success_score, 2),
        "median_latency_seconds": round(latency, 3),
        "probes": normalized,
        "passed": passed,
        "tier_scores": {
            "fast": round(success_score * 0.65 + latency_score * 0.35, 2),
            "balanced": round(success_score * 0.80 + latency_score * 0.20, 2),
            "accurate": round(success_score * 0.95 + latency_score * 0.05, 2),
        },
        "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {},
        "created_at": time.time(),
    }


def select_agent(
    config: dict[str, Any],
    agents: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Select an execution engine without making one framework the dispatcher."""

    normalized = normalize_dispatcher_config(config, agents)
    enabled = {str(row["id"]): row for row in agents if row.get("enabled", True)}
    if normalized["mode"] == "fixed":
        chosen = normalized["fixed_agent_id"]
        return chosen, {"reason": "fixed_by_operator", "tier": normalized["tier"], "qualified": _qualified(chosen, benchmarks)}

    latest: dict[str, dict[str, Any]] = {}
    for row in benchmarks:
        agent_id = str(row.get("agent_id") or "")
        if agent_id in enabled and (
            agent_id not in latest
            or float(row.get("created_at") or 0) > float(latest[agent_id].get("created_at") or 0)
        ):
            latest[agent_id] = row
    qualified = [row for agent_id, row in latest.items() if _record_qualified(row) and agent_id in enabled]
    if qualified:
        tier = normalized["tier"]
        order = {agent_id: index for index, agent_id in enumerate(normalized["fallback_order"])}
        winner = max(
            qualified,
            key=lambda row: (
                float((row.get("tier_scores") or {}).get(tier) or 0),
                -order.get(str(row.get("agent_id") or ""), 10_000),
            ),
        )
        chosen = str(winner["agent_id"])
        return chosen, {
            "reason": "highest_qualified_score",
            "tier": tier,
            "qualified": True,
            "score": float((winner.get("tier_scores") or {}).get(tier) or 0),
            "benchmark_id": winner.get("id", ""),
        }

    fallback = next((agent_id for agent_id in normalized["fallback_order"] if agent_id in enabled), "")
    if not fallback:
        raise RuntimeError("no enabled dispatcher execution engine is available")
    return fallback, {
        "reason": "provisional_unbenchmarked_fallback",
        "tier": normalized["tier"],
        "qualified": False,
    }


def _qualified(agent_id: str, benchmarks: list[dict[str, Any]]) -> bool:
    rows = [row for row in benchmarks if row.get("agent_id") == agent_id]
    if not rows:
        return False
    return _record_qualified(max(rows, key=lambda row: float(row.get("created_at") or 0)))


def _record_qualified(row: dict[str, Any]) -> bool:
    attempts = int(row.get("attempts") or 0)
    successes = int(row.get("successes") or 0)
    probes = row.get("probes") if isinstance(row.get("probes"), dict) else {}
    return bool(
        row.get("passed")
        and attempts >= MIN_QUALIFICATION_ATTEMPTS
        and successes == attempts
        and all(bool(probes.get(name)) for name in REQUIRED_PROBES)
    )


__all__ = [
    "A2A_PROTOCOL_VERSION",
    "DISPATCHER_CONTRACT_VERSION",
    "MCP_PROTOCOL_VERSION",
    "MIN_QUALIFICATION_ATTEMPTS",
    "REQUIRED_PROBES",
    "TIERS",
    "benchmark_prompt",
    "build_benchmark_record",
    "capability_manifest",
    "default_dispatcher_config",
    "normalize_dispatcher_config",
    "select_agent",
]
