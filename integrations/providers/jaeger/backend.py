"""Canonical ARES backend adapter for JaegerAI."""
from __future__ import annotations

import threading
from typing import Any

from api.providers.agentic_backend import AgenticBackend


class JaegerBackend(AgenticBackend):
    name = "jaeger_local"
    supports_tools = True
    supports_persona = True

    def is_available(self) -> bool:
        from api.providers.jaeger.status import check_status

        return check_status().available

    def get_worker_target(self) -> tuple:
        from api.providers.jaeger.streaming import run_jaeger_streaming

        return run_jaeger_streaming, False, True

    def get_backend_name(self) -> str:
        return "Jaeger AI"

    def health(self) -> dict[str, Any]:
        status = self.get_status()
        return {
            "status": "ok" if status["available"] else "error",
            "latency_ms": 0.0,
            "message": status["message"],
            "details": status.get("details", {}),
        }

    def identity_projection(self) -> dict[str, Any]:
        try:
            from api.providers.jaeger.streaming import query_local_companion

            identity = query_local_companion("identity", {})
        except Exception:
            identity = {}
        identity = identity if isinstance(identity, dict) else {}
        name = str(identity.get("agent_name") or identity.get("instance") or "Jaeger AI")
        return {"name": name, "description": "Jaeger AI runtime", "avatar_state": "idle"}

    def capabilities(self) -> dict[str, Any]:
        try:
            from api.providers.jaeger.streaming import query_local_companion

            contract = query_local_companion("contract", {})
            return dict(contract.get("features") or {}) if isinstance(contract, dict) else {}
        except Exception:
            return {}

    def chat_session_support(self) -> dict[str, Any]:
        try:
            from api.providers.jaeger.active_model import active_model

            window = int(active_model().get("ctx") or 0)
        except Exception:
            window = 0
        return {"streaming": True, "context_window": window, "multimodal": True}

    def tools(self) -> list[dict[str, Any]]:
        try:
            from api.providers.jaeger.streaming import query_local_companion

            tools = query_local_companion("list_tools", {})
            return list(tools) if isinstance(tools, list) else list((tools or {}).get("tools") or [])
        except Exception:
            return []

    def settings_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "jaeger_instance_name": {
                    "type": "string", "title": "Jaeger AI Instance Name", "default": "",
                }
            },
        }

    def run_turn(self, message: str, session_id: str, **kwargs: Any) -> dict[str, Any]:
        from api.providers.jaeger.streaming import _run_local_jaeger_turn

        requested_cancel = kwargs.get("cancel_event")
        event = requested_cancel if hasattr(requested_cancel, "is_set") else threading.Event()
        text, error, tool_activity = _run_local_jaeger_turn(
            message, session_id, str(kwargs.get("workspace") or ""), event
        )
        return {"text": text, "error": error, "tool_activity": tool_activity}

    def get_status(self) -> dict[str, Any]:
        from api.providers.jaeger.status import check_status

        return check_status().as_dict()

    def inventory(self) -> dict[str, Any]:
        from api.backends.catalog import finalize_inventory, transport_entry
        try:
            from api.providers.jaeger.streaming import query_local_companion

            catalog = query_local_companion("model_catalog", {})
            contract = query_local_companion("contract", {})
        except Exception:
            catalog, contract = {}, {}
        catalog = catalog if isinstance(catalog, dict) else {}
        contract = contract if isinstance(contract, dict) else {}
        serving = catalog.get("serving") if isinstance(catalog.get("serving"), dict) else {}
        return finalize_inventory({
            "worker_id": self.name,
            "display_name": "Jaeger AI",
            "models": list(catalog.get("models") or []),
            "providers": list(catalog.get("providers") or []),
            "default": serving,
            "transports": [transport_entry(
                id="stdio_bridge", kind="subprocess", label="Jaeger AI stdio bridge",
                in_use=True, notes="Versioned NDJSON bridge owned by JaegerAI.",
            )],
            "gateways": [],
            "mcp": list(catalog.get("mcp") or []),
            "tools_summary": self.tools(),
            "active_execution": {
                "available": self.is_available(), "transport": "stdio_bridge",
                "instance": catalog.get("instance"), "model": serving.get("model"),
                "provider": serving.get("provider"),
            },
            "notes": f"Jaeger integration contract v{contract.get('contract_version', 'unknown')}",
        })


from api.backends.cli_backends import BackendRegistry  # noqa: E402

BackendRegistry.register(JaegerBackend)
