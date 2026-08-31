"""The runtime registry is the single source of truth for agent runtimes.

These tests exist because "which runtimes exist" was previously answered in
nine independent places that could drift. They pin the invariants that make one
registry safe to rely on, so a future runtime addition fails loudly here rather
than silently in one unmigrated allowlist.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.automation.adapters import ADAPTER_TYPES, OpenClawAdapter, default_adapters
from core.automation.models import Agent
from core.control_plane.definitions import AgentDefinition
from core.runtimes import (
    ADMIN_IDENTITY,
    RUNTIME_BY_ID,
    RUNTIMES,
    durable_runtime_ids,
    is_actor_identity,
    is_durable_runtime,
    is_runtime,
    normalize_runtime_id,
    runtime_display_name,
)


def test_runtime_ids_are_unique_and_lowercase():
    ids = [runtime.id for runtime in RUNTIMES]
    assert ids == [rid.lower() for rid in ids]
    assert len(ids) == len(set(ids)), "duplicate runtime id in registry"


def test_aliases_never_collide_with_a_canonical_id():
    """An alias shadowing a real runtime would silently reroute its traffic."""
    canonical = {runtime.id for runtime in RUNTIMES}
    for runtime in RUNTIMES:
        for alias in runtime.aliases:
            assert alias not in canonical, (
                f"alias {alias!r} on {runtime.id!r} shadows a canonical runtime id"
            )


def test_pi_is_not_aliased_to_openclaw():
    """OpenClaw normalizes its internal `pi` harness id to `openclaw`.

    ARES must not copy that: `pi` is a separately installed product on this
    host with its own runtime entry, so borrowing OpenClaw's alias would route
    Pi's work to OpenClaw.
    """
    assert normalize_runtime_id("pi") == "pi"


def test_container_runtimes_declare_an_endpoint():
    """A container runtime's command is not reachable from the host."""
    for runtime in RUNTIMES:
        if runtime.deployment == "container":
            assert runtime.endpoint, (
                f"container runtime {runtime.id!r} needs a loopback endpoint"
            )


def test_http_capable_runtimes_declare_an_endpoint():
    for runtime in RUNTIMES:
        if "http" in runtime.transport:
            assert runtime.endpoint, f"{runtime.id!r} claims http transport but has no endpoint"


def test_cli_capable_runtimes_declare_a_command():
    for runtime in RUNTIMES:
        if "cli" in runtime.transport:
            assert runtime.command, f"{runtime.id!r} claims cli transport but has no command"


def test_backend_ids_reference_real_connections():
    """Kills the jaeger/jaeger_local drift: a claimed backend must exist."""
    from api.backend_catalog import BACKEND_BY_ID

    for runtime in RUNTIMES:
        if runtime.backend_id:
            assert runtime.backend_id in BACKEND_BY_ID, (
                f"runtime {runtime.id!r} names unknown backend {runtime.backend_id!r}"
            )


def test_every_durable_runtime_has_an_adapter():
    """Promotion to durable is only real once an adapter can execute a run."""
    for runtime_id in durable_runtime_ids():
        assert runtime_id in ADAPTER_TYPES, (
            f"{runtime_id!r} is durable but has no adapter in ADAPTER_TYPES"
        )
    assert set(default_adapters()) == set(durable_runtime_ids())


def test_adapters_are_not_registered_for_unknown_runtimes():
    for runtime_id in ADAPTER_TYPES:
        assert runtime_id in RUNTIME_BY_ID, f"adapter for unknown runtime {runtime_id!r}"


def test_normalize_rejects_unknown_and_reports_empty():
    assert normalize_runtime_id("nope") == ""
    assert normalize_runtime_id("") == ""
    assert normalize_runtime_id(None) == ""
    assert not is_runtime("nope")


def test_normalize_accepts_legacy_persisted_ids():
    assert normalize_runtime_id("jaeger_local") == "jaeger"
    assert normalize_runtime_id("JaegerAI") == "jaeger"
    assert normalize_runtime_id("hermes-agent") == "hermes"


def test_normalize_fallback_only_applies_to_known_runtimes():
    assert normalize_runtime_id("nope", fallback="hermes") == "hermes"
    assert normalize_runtime_id("nope", fallback="also-nope") == ""


def test_actor_identity_admits_admin_but_not_arbitrary_names():
    assert is_actor_identity(ADMIN_IDENTITY)
    assert is_actor_identity("hermes")
    assert not is_actor_identity("root")
    assert not is_actor_identity("")


def test_display_name_falls_back_to_raw_value():
    assert runtime_display_name("openclaw") == "OpenClaw"
    assert runtime_display_name("unknown-thing") == "unknown-thing"


def _agent_payload(runtime: str) -> dict:
    return {
        "id": "test-agent",
        "name": "Test Agent",
        "runtime": runtime,
        "identity": "Test",
        "model": "test-model",
        "workspace": "/workspace",
    }


def test_agent_accepts_a_durable_runtime():
    agent = Agent.from_dict(_agent_payload("hermes"))
    assert agent.runtime == "hermes"


def test_agent_normalizes_a_legacy_runtime_id():
    agent = Agent.from_dict(_agent_payload("jaeger_local"))
    assert agent.runtime == "jaeger"


def test_agent_rejects_a_registered_but_unpromoted_runtime():
    """claude is installed and classified but has no adapter yet, so it must
    fail at record creation with an actionable message rather than later at
    dispatch with a KeyError."""
    assert is_runtime("claude")
    assert not is_durable_runtime("claude")
    with pytest.raises(ValueError, match="not enabled for durable agent runs"):
        Agent.from_dict(_agent_payload("claude"))


def test_openclaw_is_promoted_and_dispatchable():
    assert is_durable_runtime("openclaw")
    assert "openclaw" in default_adapters()


def test_openclaw_exec_loads_gateway_secret_from_runtime_file():
    command = OpenClawAdapter(container_cli="container")._exec("node --version")
    rendered = " ".join(command)
    assert "/home/node/.openclaw/gateway.token" in rendered
    assert "OPENCLAW_GATEWAY_TOKEN=" in rendered
    assert "node --version" in rendered


def test_openclaw_installer_pins_image_and_uses_stable_private_host_route():
    installer = Path(__file__).parents[3] / "scripts" / "install-openclaw-container.sh"
    source = installer.read_text(encoding="utf-8")

    assert "ghcr.io/openclaw/openclaw@sha256:" in source
    assert "http://host.container.internal:11434" in source
    assert "ensure_provider_auth ollama-local" in source
    assert "ensure_provider_auth ollama-cloud-via-host" in source
    assert '--env "OPENCLAW_GATEWAY_TOKEN=$gateway_token"' not in source


def test_agent_rejects_an_unknown_runtime():
    with pytest.raises(ValueError, match="unknown runtime"):
        Agent.from_dict(_agent_payload("definitely-not-a-runtime"))


def test_agent_definition_normalizes_and_rejects():
    base = {"id": "a1", "ollama_base_url": "http://127.0.0.1:11434/v1"}
    definition = AgentDefinition.from_dict({**base, "runtime": "jaeger_local"})
    assert definition.runtime == "jaeger"
    with pytest.raises(ValueError):
        AgentDefinition.from_dict({**base, "runtime": "nope"})
