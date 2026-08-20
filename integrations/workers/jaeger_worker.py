"""JaegerAI dispatch adapter over the canonical stdio bridge."""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def is_jaeger_available() -> bool:
    from integrations.providers.jaeger.status import check_status

    return check_status().available


def get_jaeger_models() -> dict[str, Any]:
    try:
        from api.providers.jaeger.streaming import query_local_companion

        payload = query_local_companion("model_catalog", {})
        return payload if isinstance(payload, dict) else {}
    except Exception:
        logger.debug("Jaeger model inventory query failed", exc_info=True)
        return {}


class JaegerWorker:
    name = "jaeger_local"
    model_name = "jaeger-ai"
    supports_tools = True
    supports_streaming = True

    def is_available(self) -> bool:
        return is_jaeger_available()

    def run_turn(self, message: str, session_id: str, **kwargs: Any) -> dict[str, Any]:
        if not self.is_available():
            return {"error": "Jaeger AI is not available", "text": ""}
        from api.providers.jaeger.streaming import _run_local_jaeger_turn

        requested_cancel = kwargs.get("cancel_event")
        cancel_event = requested_cancel if hasattr(requested_cancel, "is_set") else threading.Event()
        text, error, tool_activity = _run_local_jaeger_turn(
            message, session_id, str(kwargs.get("workspace") or ""), cancel_event
        )
        return {
            "text": text, "error": error or None, "model": self.model_name,
            "provider": "jaeger", "input_tokens": 0, "output_tokens": 0,
            "mode": "bridge", "tool_activity": tool_activity,
        }

    def health(self) -> dict[str, Any]:
        return {"status": "ok" if self.is_available() else "error", "mode": "bridge"}

    def capabilities(self) -> dict[str, Any]:
        return {
            "chat": True, "tools": self.supports_tools,
            "streaming": self.supports_streaming, "models": get_jaeger_models(),
        }
