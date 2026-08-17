"""Explicit, environment-gated acceptance checks for real worker installs."""

from __future__ import annotations

import os
import uuid

import pytest

from fastapi_app.adapters import AdapterRegistry


def _requested_workers() -> list[str]:
    return [
        value.strip()
        for value in os.environ.get("ARES_LIVE_WORKERS", "").split(",")
        if value.strip()
    ]


@pytest.mark.live_worker
@pytest.mark.parametrize("worker_id", _requested_workers() or ["__not_selected__"])
def test_requested_live_worker_completes_bounded_turn(worker_id: str):
    if os.environ.get("ARES_LIVE_ACCEPTANCE") != "1":
        pytest.skip("live acceptance was not explicitly enabled")
    assert worker_id != "__not_selected__", "ARES_LIVE_WORKERS must select workers"

    if worker_id == "jaeger_local" and os.environ.get("ARES_LIVE_JAEGER_HOME"):
        os.environ["ARES_JAEGER_HOME"] = os.environ["ARES_LIVE_JAEGER_HOME"]
        if os.environ.get("ARES_LIVE_JAEGER_INSTANCE"):
            os.environ["ARES_JaegerAI_INSTANCE"] = os.environ["ARES_LIVE_JAEGER_INSTANCE"]
        from api.providers.jaeger.status import reset_cache

        reset_cache()

    adapter = AdapterRegistry().execution_adapter(worker_id)
    health = adapter.check_health(profile=None)
    assert health.available, f"{worker_id} unavailable: {health.message}"

    model = None
    if worker_id == "ollama_local":
        model = os.environ.get("ARES_LIVE_OLLAMA_MODEL") or _local_ollama_model()

    result = adapter.run_turn(
        "Reply with exactly ARES_LIVE_OK.",
        session_id=f"live-acceptance-{uuid.uuid4().hex}",
        profile=None,
        model=model,
    )
    assert not str(result.get("error") or "").strip(), result
    assert str(result.get("text") or result.get("response") or "").strip(), result


def _local_ollama_model() -> str | None:
    """Prefer an installed on-device tag over an Ollama cloud proxy tag."""
    import requests

    response = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
    response.raise_for_status()
    models = response.json().get("models") or []
    for item in models:
        if isinstance(item, dict) and not item.get("remote_host"):
            value = str(item.get("name") or item.get("model") or "").strip()
            if value:
                return value
    return None
