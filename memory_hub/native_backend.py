"""Native backend for hot-path operations.

This module tries to import Rust extensions from ai_memory_hub_native.
If the native module is not available (not compiled, import error, or MEMORY_NATIVE_BACKEND=false),
it falls back to pure-Python implementations.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Feature flag: set MEMORY_NATIVE_BACKEND=false to force Python fallback
_USE_NATIVE = os.environ.get("MEMORY_NATIVE_BACKEND", "true").lower() not in ("0", "false", "no")

_native = None
if _USE_NATIVE:
    try:
        import ai_memory_hub_native as _native
        logger.info("Native backend enabled (ai_memory_hub_native loaded)")
    except ImportError:
        logger.debug("ai_memory_hub_native not available; using Python fallback")
        _native = None


# --------------------------------------------------------------------------- tokenization

def is_native_available() -> bool:
    return _native is not None


def tokenize(text: str) -> list[str]:
    if _native is not None:
        return _native.tokenize(text)
    # Python fallback
    import re
    _WORD_RE = re.compile(r"[a-z0-9_]{2,}")
    _STOPWORDS = {"the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on"}
    return [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]


def tokenize_batch(texts: list[str]) -> list[list[str]]:
    if _native is not None:
        return _native.tokenize_batch(texts)
    import re
    _WORD_RE = re.compile(r"[a-z0-9_]{2,}")
    _STOPWORDS = {"the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on"}
    return [
        [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]
        for text in texts
    ]


class TokenCache:
    """Batch tokenization cache. Uses Rust if available, else Python dict."""

    def __init__(self) -> None:

        import re
        _WORD_RE = re.compile(r"[a-z0-9_]{2,}")
        _STOPWORDS = {"the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on"}
        for id_, text in texts:
            tokens = [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]
            self._inner[id_] = (tokens, set(tokens))

    def query(self, prompt: str, limit: int) -> list[tuple[str, float]]:
        if hasattr(self, "_inner") and hasattr(self._inner, "query"):
            return self._inner.query(prompt, limit)
        import re
        _WORD_RE = re.compile(r"[a-z0-9_]{2,}")
        _STOPWORDS = {"the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on"}
        prompt_tokens = {t for t in _WORD_RE.findall(prompt.lower()) if t not in _STOPWORDS}
        if not prompt_tokens:
            return []
        results = []
        for id_, (_, token_set) in self._inner.items():
            score = len(prompt_tokens & token_set)
            if score > 0:
                results.append((id_, float(score)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]


# --------------------------------------------------------------------------- embeddings

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if _native is not None:
        return _native.cosine_similarity(a, b)
    dot = sum(ai * bi for ai, bi in zip(a, b, strict=False))
    norm_a = sum(ai * ai for ai in a) ** 0.5
    norm_b = sum(bi * bi for bi in b) ** 0.5
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return dot / (norm_a * norm_b)


def cosine_top_k(query: list[float], matrix: list[list[float]], k: int) -> list[tuple[int, float]]:
    if _native is not None:
        return _native.cosine_top_k(query, matrix, k)
    results = [(i, cosine_similarity(query, emb)) for i, emb in enumerate(matrix)]
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:k]


def pairwise_cosine(embeddings: list[tuple[str, list[float]]], threshold: float) -> list[tuple[str, str, float]]:
    if _native is not None:
        return _native.pairwise_cosine(embeddings, threshold)
    results = []
    n = len(embeddings)
    for i in range(n):
        for j in range(i + 1, n):
            score = cosine_similarity(embeddings[i][1], embeddings[j][1])
            if score >= threshold:
                results.append((embeddings[i][0], embeddings[j][0], score))
    return results


def normalize_vector(v: list[float]) -> list[float]:
    if _native is not None:
        return _native.normalize_vector(v)
    mag = sum(x * x for x in v) ** 0.5
    if mag < 1e-10:
        return v
    return [x / mag for x in v]


# --------------------------------------------------------------------------- capture

class CaptureBuffer:
    """Rust-backed capture buffer with fallback to Python SQLite."""

    def __init__(self, vault_path: str, key: str | None = None) -> None:
        if _native is not None:
            self._inner = _native.capture_buffer(vault_path)
            self._has_native = True
        else:
            self._has_native = False
            # Python fallback - will be implemented if needed
            raise NotImplementedError("CaptureBuffer Python fallback not implemented")

    def append(self, payload: dict) -> str:
        from types import SimpleNamespace
        p = SimpleNamespace(**payload)
        return self._inner.append(p)

    def claim(self, session_id: str, limit: int, claim_token: str) -> list[str]:
        return self._inner.claim(session_id, limit, claim_token)

    def mark_completed(self, ids: list[str]) -> int:
        return self._inner.mark_completed(ids)

    def stats(self) -> dict[str, int]:
        return dict(self._inner.stats())
