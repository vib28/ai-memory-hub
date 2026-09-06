"""Optional OpenAI-compatible local embedding provider."""

from __future__ import annotations

import json
import os
import urllib.request
from math import sqrt
from typing import Any


class EmbeddingError(RuntimeError):
    pass


class LocalEmbeddingProvider:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    @classmethod
    def from_environment(cls) -> "LocalEmbeddingProvider | None":
        base_url = os.environ.get("MEMORY_EMBED_BASE_URL", "").strip()
        model = os.environ.get("MEMORY_EMBED_MODEL", "nomic-embed-text").strip()
        return cls(base_url, model) if base_url else None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/embeddings", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            rows = sorted(payload["data"], key=lambda row: row.get("index", 0))
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
            if len(vectors) != len(texts) or any(not vector for vector in vectors):
                raise ValueError("embedding response count or dimensions are invalid")
            return vectors
        except Exception as exc:
            raise EmbeddingError(f"local embedding request failed: {exc}") from exc


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denominator
