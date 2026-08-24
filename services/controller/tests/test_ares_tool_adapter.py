"""Tests for ARES Tool Adapter and Runtime Context.

These modules let ARES expose shared tools and inject live state into an
explicitly selected external runtime.

RED phase: all tests should FAIL until implementation is written.
"""

from __future__ import annotations

import json
import asyncio
from unittest.mock import patch

import pytest


# ── ARES Runtime Context ──────────────────────────────────────────

class TestRuntimeContext:
    """ares_runtime_context.py: builds a live state packet every turn."""

    def test_module_exports_build_context(self):
        """Module exports build_runtime_context()."""
        from api.ares_runtime_context import build_runtime_context

        assert callable(build_runtime_context)

    def test_build_context_returns_dict(self):
        """build_runtime_context() returns a dict with required keys."""
        from api.ares_runtime_context import build_runtime_context

        ctx = build_runtime_context()
        assert isinstance(ctx, dict)
        # Required keys for ARES operating state
        assert "identity_projection" in ctx
        assert "active_backend" in ctx
        assert "capabilities" in ctx

    def test_identity_is_backend_projection(self):
        """Identity is a backend projection, not an ARES-owned canonical soul."""
        from api.ares_runtime_context import build_runtime_context

        ctx = build_runtime_context()
        assert isinstance(ctx["identity_projection"], dict)
        assert "name" in ctx["identity_projection"]

    def test_no_runtime_is_not_silently_replaced_when_jaeger_is_down(self):
        from api.ares_runtime_context import build_runtime_context

        with patch(
            "api.ares_runtime_context.is_jaeger_available",
            return_value=False,
        ):
            ctx = build_runtime_context(backend="")
            assert ctx["active_backend"] == ""
            assert ctx["capabilities"]["active_runtime"]["available"] is False
            assert ctx["capabilities"]["jaeger"]["available"] is False

    def test_external_runtime_and_ares_resources_are_distinct(self):
        from api.ares_runtime_context import build_runtime_context

        with patch(
            "api.ares_runtime_context.is_jaeger_available",
            return_value=True,
        ):
            ctx = build_runtime_context(backend="claude_local")
            assert ctx["active_backend"] == "claude_local"
            assert ctx["capabilities"]["ares_resources"]["available"] is True
            assert ctx["capabilities"]["active_runtime"]["available"] is True
            assert ctx["capabilities"]["jaeger"]["available"] is True

    def test_render_context_prompt_compact(self):
        """render_context_prompt() produces a compact text block for injection."""
        from api.ares_runtime_context import (
            build_runtime_context,
            render_context_prompt,
        )

        ctx = build_runtime_context(backend="claude_local")
        prompt = render_context_prompt(ctx)
        assert isinstance(prompt, str)
        assert "Projected identity" in prompt
        assert len(prompt) > 0
        # Must be compact — under 500 chars for injection
        assert len(prompt) < 500


# ── ARES Tool Adapter ────────────────────────────────────────────

class TestToolAdapter:
    """ares_tool_adapter.py: registers ARES tools into Ares or JaegerAI."""

    def test_module_exports_register_ares_tools(self):
        """Module exports register_ares_tools()."""
        from api.ares_tool_adapter import register_ares_tools

        assert callable(register_ares_tools)

    def test_module_exports_ares_tool_definitions(self):
        """Module exports ARES_TOOL_DEFS — the tool catalog."""
        from api.ares_tool_adapter import ARES_TOOL_DEFS

        assert isinstance(ARES_TOOL_DEFS, list)
        assert len(ARES_TOOL_DEFS) > 0

    def test_tool_defs_have_required_fields(self):
        """Each tool def has name, description, args_model, fn."""
        from api.ares_tool_adapter import ARES_TOOL_DEFS

        for tdef in ARES_TOOL_DEFS:
            assert "name" in tdef, f"Tool missing name: {tdef}"
            assert "description" in tdef, f"Tool missing description: {tdef}"
            assert "fn" in tdef, f"Tool missing fn: {tdef}"

    def test_register_into_mcp_format(self):
        """register_ares_tools produces MCP-compatible tool schemas."""
        from api.ares_tool_adapter import register_ares_tools

        schemas = register_ares_tools(target="mcp")
        assert isinstance(schemas, list)
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema

    def test_register_into_jaeger_tooldef_format(self):
        """register_ares_tools produces JaegerAI ToolDef-compatible dicts for JaegerAI."""
        from api.ares_tool_adapter import register_ares_tools

        tooldefs = register_ares_tools(target="jaeger")
        assert isinstance(tooldefs, list)
        for td in tooldefs:
            assert "name" in td
            assert "description" in td
            assert "args_model" in td
            assert "fn" in td

    def test_unknown_target_raises(self):
        """register_ares_tools raises ValueError for unknown backend target."""
        from api.ares_tool_adapter import register_ares_tools

        with pytest.raises(ValueError, match="Unknown target"):
            register_ares_tools(target="unknown_backend")

    def test_stdio_mcp_server_publishes_canonical_ares_tools(self):
        from api.ares_tools import ARES_TOOL_DEFS
        from mcp_server import HANDLERS, TOOLS

        published = {tool.name for tool in TOOLS}
        expected = {tool["name"] for tool in ARES_TOOL_DEFS}
        assert expected.issubset(published)
        assert expected.issubset(HANDLERS)

    def test_stdio_mcp_dispatches_canonical_ares_tool(self):
        """A registered tool is callable through the MCP boundary.

        Uses ``ares_get_mode`` — a read-only tool taking no arguments — so the
        test exercises real dispatch rather than a stub, without side effects.
        The retired ``ares_list_artifacts`` this used to call was removed in
        651c14433 along with the rest of the old surface.
        """
        import mcp_server
        from api.ares_tools import ARES_TOOL_DEFS

        name = "ares_get_mode"
        assert name in {tool["name"] for tool in ARES_TOOL_DEFS}, (
            "the probe tool is no longer registered; pick another NoArgs tool"
        )
        result = asyncio.run(mcp_server.call_tool(name, {}))
        payload = json.loads(result[0].text)
        assert isinstance(payload, dict)
        assert "error" not in payload or payload.get("ok") is not False


class TestAresToolRegistryContract:
    """The registry contract, not a list of tool names copied into a test.

    651c14433 replaced the entire ARES tool surface — eleven tools out
    (``ares_get_runtime_context``, ``ares_create_task``, ``ares_extract_pdf``,
    ``ares_ingest_youtube``, ``ares_edit_image``, ``ares_create_visual_report``,
    ``ares_list_artifacts``, ``ares_start_research`` and friends), eight in.
    The previous tests named the old ones and so failed on every run after that
    commit, which is what a hand-copied list of names always eventually does.

    These assert the PROPERTIES the registry has to keep instead, so adding or
    retiring a tool is a one-line change in ``ares_tools.py`` and nothing here
    needs editing — while a tool that silently loses its metadata, its
    callable, or its place at the MCP boundary still fails loudly.
    """

    def test_every_registered_tool_is_discoverable_and_callable(self):
        from api.ares_tools import ARES_TOOL_DEFS, ARES_TOOLS_REGISTRY

        assert ARES_TOOL_DEFS, "the ARES tool registry is empty"
        names = [str(d["name"]) for d in ARES_TOOL_DEFS]
        assert len(names) == len(set(names)), f"duplicate tool names: {names}"
        for definition in ARES_TOOL_DEFS:
            name = str(definition["name"])
            assert name.startswith("ares_"), f"{name} is not namespaced to ARES"
            assert callable(ARES_TOOLS_REGISTRY.get(name)), f"{name} has no callable"

    def test_registry_is_derived_from_the_definitions(self):
        """One registration point (AGENTS.md rule 4) — so it cannot drift."""
        from api.ares_tools import ARES_TOOL_DEFS, ARES_TOOLS_REGISTRY

        assert set(ARES_TOOLS_REGISTRY) == {str(d["name"]) for d in ARES_TOOL_DEFS}
        for definition in ARES_TOOL_DEFS:
            assert ARES_TOOLS_REGISTRY[str(definition["name"])] is definition["fn"]

    def test_capability_metadata_is_complete(self):
        """Every tool carries what a consumer needs to publish it.

        A missing description or args_model does not fail at registration — it
        fails later, at the MCP or JaegerAI boundary, where the cause is much
        harder to see.
        """
        from api.ares_tools import ARES_TOOL_DEFS

        for definition in ARES_TOOL_DEFS:
            name = str(definition.get("name") or "")
            description = str(definition.get("description") or "").strip()
            assert description, f"{name} has no description"
            assert description.endswith("."), f"{name} description is not a sentence"
            assert definition.get("args_model") is not None, f"{name} has no args_model"
            assert hasattr(definition["args_model"], "model_json_schema"), (
                f"{name} args_model is not a pydantic model"
            )

    def test_retired_tools_do_not_silently_reappear(self):
        """The old surface was retired deliberately; re-adding one is a decision.

        Named explicitly rather than as "anything not in the current list",
        because the point is not to freeze the registry — it is to make the
        return of a specific withdrawn tool visible in review instead of
        arriving as a merge artifact from the pre-651c14433 tree.
        """
        from api.ares_tools import ARES_TOOLS_REGISTRY

        retired = {
            "ares_get_runtime_context", "ares_create_task", "ares_update_task",
            "ares_extract_pdf", "ares_fill_pdf_form", "ares_ingest_youtube",
            "ares_edit_image", "ares_create_visual_report", "ares_list_artifacts",
            "ares_start_research", "ares_get_research",
        }
        returned = retired & set(ARES_TOOLS_REGISTRY)
        assert not returned, (
            f"tools retired in 651c14433 are registered again: {sorted(returned)}. "
            "If that is intended, remove them from this list in the same change."
        )

    def test_dispatch_rejects_an_unknown_tool_without_raising(self):
        """Consumers get a stable error shape, not an exception."""
        from api.ares_tools import dispatch_ares_tool

        result = dispatch_ares_tool("ares_definitely_not_a_tool", {})
        assert result["ok"] is False
        assert "Unknown ARES tool" in result["error"]

    def test_consumers_receive_stable_structures(self):
        """Both boundaries publish every registered tool, with schemas.

        The MCP surface and the JaegerAI ToolDef surface read the same list, so
        a tool that reaches one and not the other means a consumer stopped
        deriving from ``ARES_TOOL_DEFS``.
        """
        from api.ares_tool_adapter import register_ares_tools
        from api.ares_tools import ARES_TOOL_DEFS

        expected = {str(d["name"]) for d in ARES_TOOL_DEFS}
        for target in ("mcp", "jaeger"):
            published = register_ares_tools(target)
            assert isinstance(published, list), f"{target} did not return a list"
            names = {
                str(item.get("name") if isinstance(item, dict) else getattr(item, "name", ""))
                for item in published
            }
            assert expected <= names, (
                f"{target} is missing {sorted(expected - names)}"
            )


class TestStreamingIntegration:
    """Runtime context is injectable into the streaming path."""

    def test_context_injectable_into_ares_prompt(self):
        """Runtime context can be rendered for Ares ephemeral_system_prompt."""
        from api.ares_runtime_context import (
            build_runtime_context,
            render_context_prompt,
        )

        ctx = build_runtime_context(backend="claude_local")
        prompt = render_context_prompt(ctx)
        # Must contain backend designation
        assert "claude_local" in prompt.lower()

    def test_context_injectable_into_jaeger_prompt(self):
        """Runtime context can be rendered for JaegerAI system_prompt."""
        from api.ares_runtime_context import (
            build_runtime_context,
            render_context_prompt,
        )

        ctx = build_runtime_context(backend="jaeger_local")
        prompt = render_context_prompt(ctx)
        # Must contain backend designation
        assert "jaeger" in prompt.lower()

    def test_context_prompt_includes_capabilities(self):
        """Context prompt includes capability summary for both backends."""
        from api.ares_runtime_context import (
            build_runtime_context,
            render_context_prompt,
        )

        # Hermetic: availability is a live JaegerAI gateway health probe now,
        # so pin it instead of depending on the test machine's setup.
        with patch(
            "api.ares_runtime_context.is_jaeger_available",
            return_value=True,
        ):
            ctx = build_runtime_context(backend="jaeger_local")
        prompt = render_context_prompt(ctx)
        # JaegerAI presence is an optional managed capability.
        assert "jaeger" in prompt.lower()
        assert ctx["capabilities"]["ares_resources"]["available"] is True
        assert ctx["capabilities"]["jaeger"]["available"] is True


# ── Route Registration ────────────────────────────────────────────

class TestRouteRegistration:
    """ARES runtime-context and tools routes are registered in FastAPI."""

    @staticmethod
    def _get(path):
        from fastapi.testclient import TestClient
        from fastapi_app.main import create_app

        with TestClient(create_app()) as client:
            return client.get(path)

    def test_runtime_context_route_is_registered(self):
        assert self._get("/api/ares/runtime-context").status_code != 404

    def test_tools_route_is_registered(self):
        assert self._get("/api/ares/tools").status_code != 404


# ── Streaming Wiring ──────────────────────────────────────────────

class TestStreamingWiring:
    """Runtime context is wired into streaming.py alongside self-persistence."""

    def test_runtime_context_injection_in_streaming(self):
        """streaming.py imports and calls build_runtime_context."""
        import api.streaming as streaming_mod
        source = open(streaming_mod.__file__).read()
        assert "ares_runtime_context" in source
        assert "build_runtime_context" in source
        assert "render_context_prompt" in source

    def test_runtime_context_prompt_in_merge_order(self):
        """Runtime context is merged after self-persistence in _combined_prompt_parts."""
        import api.streaming as streaming_mod
        source = open(streaming_mod.__file__).read()
        # Self-persistence must come before runtime context
        sp_pos = source.find("_self_persistence_prompt")
        rc_pos = source.find("_runtime_context_prompt")
        assert sp_pos < rc_pos, "Self-persistence must be injected before runtime context"
