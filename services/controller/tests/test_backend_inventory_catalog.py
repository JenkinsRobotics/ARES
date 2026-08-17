"""Adapter inventory catalogs models, transports, gateways, and MCP."""

from __future__ import annotations

from api.backends.catalog import (
    empty_inventory,
    finalize_inventory,
    infer_model_location,
    model_entry,
)
from api.providers.jaeger.backend import JaegerBackend


def test_infer_model_location_local_and_cloud():
    assert infer_model_location("ollama", "llama3") == "local"
    assert infer_model_location("ollama-cloud", "deepseek-v4-flash") == "cloud"
    assert infer_model_location("xai", "grok-3") == "cloud"
    assert infer_model_location("local", "gemma.gguf") == "local"


def test_empty_inventory_has_latency_note():
    inv = empty_inventory(worker_id="x", display_name="X")
    assert inv["schema_version"] == 1
    assert "selected_model" in inv["latency"]["depends_on"]
    assert "LLM" in inv["latency"]["note"] or "model" in inv["latency"]["note"].lower()


def test_jaeger_inventory_uses_owner_bridge(monkeypatch):
    monkeypatch.setattr(JaegerBackend, "is_available", lambda _self: True)
    inv = JaegerBackend().inventory()
    inv = finalize_inventory(inv)
    kinds = {t["kind"] for t in inv["transports"]}
    assert kinds == {"subprocess"}
    assert inv["active_execution"]["transport"] == "stdio_bridge"
    for m in inv.get("models", []):
        assert m.get("location") in {"local", "cloud", "unknown"}


def test_model_entry_shape():
    m = model_entry(id="x", location="cloud", provider="openai", in_use=True)
    assert m["location"] == "cloud"
    assert m["in_use"] is True
