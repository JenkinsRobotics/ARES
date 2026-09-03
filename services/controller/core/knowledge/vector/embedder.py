"""Ollama embeddings client for the knowledge base.

Uses mxbai-embed-large (1024 dims) by default for best recall.
Falls back gracefully if Ollama is unreachable.
"""

from __future__ import annotations

import logging
import urllib.request
import json
from typing import Sequence

from ..config import KBConfig

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    """Thin client for Ollama's /api/embeddings endpoint."""

    def __init__(self, base_url: str, model: str, dims: int, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dims = dims
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: KBConfig) -> "Embedder":
        return cls(
            base_url=config.ollama_base_url,
            model=config.embedding_model,
            dims=config.embedding_dims,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input text.

        Retries with progressively shorter text if the model's context
        window is exceeded.
        """
        if not texts:
            return []
        vectors: list[list[float]] = []
        for text in texts:
            vec = self._embed_one(text)
            vectors.append(vec)
        return vectors

    def _embed_one(self, text: str, max_chars: int = 1500) -> list[float]:
        """Embed a single text with retry-on-overflow."""
        # Truncate to avoid context length errors
        if len(text) > max_chars:
            text = text[:max_chars]
        # Retry with progressively smaller text on HTTP 500
        for attempt in range(4):
            payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    vec = data.get("embedding", [])
                    if len(vec) != self.dims:
                        raise EmbeddingError(
                            f"embedding dimension mismatch: got {len(vec)}, expected {self.dims}"
                        )
                    return vec
            except urllib.error.HTTPError as exc:
                if exc.code == 500 and max_chars > 200:
                    # Context length exceeded — halve and retry
                    max_chars = max_chars // 2
                    text = text[:max_chars]
                    continue
                raise EmbeddingError(f"Ollama embedding failed: {exc}")
            except Exception as exc:
                raise EmbeddingError(f"Ollama embedding failed: {exc}")
        # Final fallback: embed a minimal placeholder
        payload = json.dumps({"model": self.model, "prompt": text[:100]}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("embedding", [])

    def embed_one(self, text: str) -> list[float]:
        result = self.embed([text])
        return result[0] if result else []

    def health_check(self) -> bool:
        """Quick check if Ollama is reachable and the model is available."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self.model in m for m in models)
        except Exception:
            return False