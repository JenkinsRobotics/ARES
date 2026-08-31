"""Ollama is the model layer: local weights plus the cloud catalog.

Two things make this simple, and both were got wrong before:

* Every model in the ollama.com catalog is runnable in the cloud under its
  ``:cloud`` / ``-cloud`` id, with no pull and no local weights. The daemon
  resolves those ids straight to Ollama Cloud.
* The *bare* catalog name is the opposite -- it means downloadable weights
  (``deepseek-v4-pro:0813`` is 893 GB). Listing bare names as selectable is how
  a picker entry turns into a multi-hundred-gigabyte download.

So: cloud ids are always the ``:cloud``/``-cloud`` spelling.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from integrations.workers import model_discovery


@pytest.fixture(autouse=True)
def _clear_cache():
    model_discovery.reset_cloud_cache()
    yield
    model_discovery.reset_cloud_cache()


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


CATALOG = {
    "models": [
        {"name": "glm-5.2", "size": 0},
        {"name": "gpt-oss:20b", "size": 13_000_000_000},
        {"name": "deepseek-v4-pro:0813", "size": 893_000_000_000},
    ]
}

LOCAL_TAGS = {
    "models": [
        {"name": "local-agent", "capabilities": ["completion", "tools"]},
        {
            "name": "gemini-3-flash-preview:latest",
            "remote_model": "gemini-3-flash-preview",
            "capabilities": ["completion", "tools"],
        },
        {"name": "embedder", "capabilities": ["embedding"]},
    ]
}


def _fake_urlopen(monkeypatch):
    seen: list[str] = []

    def fake(request, timeout=None):  # noqa: ANN001
        url = request.full_url
        seen.append(url)
        return _FakeResponse(CATALOG if "ollama.com" in url else LOCAL_TAGS)

    monkeypatch.setattr(model_discovery.urllib.request, "urlopen", fake)
    return seen


def test_cloud_models_come_from_the_cloud_registry(monkeypatch):
    seen = _fake_urlopen(monkeypatch)
    models = model_discovery.list_ollama_cloud_models()

    assert models
    assert any("ollama.com" in url for url in seen)
    assert not any("127.0.0.1" in url for url in seen), (
        "cloud lister regressed to reading the local daemon"
    )


def test_cloud_ids_use_the_cloud_spelling_never_the_bare_name(monkeypatch):
    """The bare name downloads weights; the :cloud id runs remotely."""
    _fake_urlopen(monkeypatch)
    ids = {row["id"] for row in model_discovery.list_ollama_cloud_models()}

    assert ids == {"glm-5.2:cloud", "gpt-oss:20b-cloud", "deepseek-v4-pro:0813-cloud"}
    assert "deepseek-v4-pro:0813" not in ids, "bare name would download 893 GB"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("glm-5.2", "glm-5.2:cloud"),          # untagged -> :cloud
        ("gpt-oss:20b", "gpt-oss:20b-cloud"),  # already tagged -> -cloud
        ("kimi-k3:cloud", "kimi-k3:cloud"),    # already cloud -> unchanged
        ("foo-cloud", "foo-cloud"),
    ],
)
def test_cloud_ref_spelling(name, expected):
    assert model_discovery._cloud_ref(name) == expected


def test_every_cloud_entry_is_labelled_cloud(monkeypatch):
    _fake_urlopen(monkeypatch)
    for row in model_discovery.list_ollama_cloud_models():
        assert row["location"] == "cloud"
        assert row["provider"] == "ollama-cloud"


def test_offline_registry_returns_empty_not_an_exception(monkeypatch):
    def boom(request, timeout=None):  # noqa: ANN001
        raise OSError("offline")

    monkeypatch.setattr(model_discovery.urllib.request, "urlopen", boom)
    assert model_discovery.list_ollama_cloud_models() == []


def test_catalog_is_cached_between_calls(monkeypatch):
    seen = _fake_urlopen(monkeypatch)
    first = model_discovery.list_ollama_cloud_models()
    count = len(seen)
    second = model_discovery.list_ollama_cloud_models()

    assert first == second
    assert len(seen) == count, "cached call must not hit the network"


def test_registered_cloud_models_come_from_the_daemon(monkeypatch):
    _fake_urlopen(monkeypatch)
    ids = {row["id"] for row in model_discovery.list_ollama_registered_cloud_models()}
    assert ids == {"gemini-3-flash-preview:latest"}


def test_inventory_offers_local_and_cloud_together(monkeypatch):
    from integrations.workers.cli_backends import OllamaLocalBackend

    _fake_urlopen(monkeypatch)
    models = OllamaLocalBackend().inventory()["models"]
    ids = {row["id"] for row in models}

    assert "local-agent" in ids
    assert "gemini-3-flash-preview:latest" in ids
    assert {"glm-5.2:cloud", "gpt-oss:20b-cloud", "deepseek-v4-pro:0813-cloud"} <= ids
    assert "embedder" not in ids, "embedding-only models are not chat models"
    assert "deepseek-v4-pro:0813" not in ids, "bare name must never be selectable"


def test_inventory_survives_an_offline_cloud(monkeypatch):
    """Being offline drops the cloud half; it must not empty the picker."""
    from integrations.workers.cli_backends import OllamaLocalBackend

    def fake(request, timeout=None):  # noqa: ANN001
        if "ollama.com" in request.full_url:
            raise OSError("offline")
        return _FakeResponse(LOCAL_TAGS)

    monkeypatch.setattr(model_discovery.urllib.request, "urlopen", fake)
    ids = {row["id"] for row in OllamaLocalBackend().inventory()["models"]}
    assert "local-agent" in ids
