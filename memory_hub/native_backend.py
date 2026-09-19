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


def project_rows(index_rows: list[dict], project: str | None) -> list[dict]:
    """Port of context_packet._project_rows using Rust when available."""
    if _native is not None:
        return _native.project_rows(index_rows, project)
    # Python fallback
    from .utils import slugify
    if not project:
        return []
    slug = slugify(project)
    wanted = f"/projects/{slug}.md"
    rows = [row for row in index_rows
            if row.get("tag") != "superseded" and str(row.get("path", "")).lower() == wanted]
    rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("memory_id", ""))), reverse=True)
    return rows


def global_rows(index_rows: list[dict]) -> list[dict]:
    """Port of context_packet._global_rows using Rust when available."""
    if _native is not None:
        return _native.global_rows(index_rows)
    # Python fallback
    rows = [row for row in index_rows
            if row.get("tag") != "superseded"
            and str(row.get("path", "")).lower() in {"/preferences.md", "/profile.md"}]
    rows.sort(key=lambda row: (row.get("path") != "/profile.md", str(row.get("date", ""))), reverse=False)
    return rows


def related_rows(index_rows: list[dict], prompt: str, project: str | None = None, limit: int = 6) -> list[dict]:
    """Port of context_packet._related_rows using Rust when available."""
    if _native is not None:
        return _native.related_rows(index_rows, prompt, project, limit)
    # Python fallback
    from .utils import slugify

    def _tokens(text: str) -> frozenset[str]:
        import re
        _WORD_RE = re.compile(r"[a-z0-9][a-z0-9_\-\.]{2,}")
        _STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "into"}
        raw = {token for token in _WORD_RE.findall(text.lower()) if token not in _STOPWORDS}
        return frozenset(token for token in raw if len(token) >= 6)

    query = _tokens(prompt)
    if len(query) < 1:
        return []
    project_slug = slugify(project) if project else None
    scored: list[tuple[float, dict]] = []
    for row in index_rows:
        if row.get("tag") == "superseded" or row.get("kind") == "session":
            continue
        path = str(row.get("path", "")).lower()
        if path.startswith("/projects/") and project_slug and path != f"/projects/{project_slug}.md":
            continue
        if path.startswith("/sessions/"):
            continue
        overlap = query & _tokens(f"{row.get('subject', '')} {row.get('text', '')}")
        if len(overlap) < 2:
            continue
        score = len(overlap) / max(1, len(query) ** 0.5)
        if score < 0.3:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: (item[0], str(item[1].get("date", ""))), reverse=True)
    return [row for _score, row in scored[:limit]]


class TokenCache:
    """Batch tokenization cache. Uses Rust if available, else Python dict."""

    def __init__(self) -> None:
        if _native is not None:
            self._inner = _native.TokenCache()
            self._has_native = True
        else:
            self._inner: dict[str, tuple[list[str], set[str]]] = {}
            self._has_native = False

    def build(self, texts: list[tuple[str, str]]) -> None:
        if self._has_native:
            self._inner.build(texts)
        else:
            import re
            _WORD_RE = re.compile(r"[a-z0-9_]{2,}")
            _STOPWORDS = {"the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on"}
            for id_, text in texts:
                tokens = [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]
                self._inner[id_] = (tokens, set(tokens))

    def query(self, prompt: str, limit: int) -> list[tuple[str, float]]:
        if self._has_native:
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

def normalize_event(value: Any) -> str:
    """Port of capture.normalize_event using Rust when available."""
    if _native is not None:
        return _native.normalize_event(value)
    from .utils import to_kebab
    raw = "" if value is None else str(value).strip()
    if not raw:
        return "observation"
    kebab = to_kebab(raw, limit=80)
    _EVENT_ALIASES = {
        "sessionstart": "session-start", "session-start": "session-start",
        "sessionend": "session-end", "session-end": "session-end",
        "userpromptsubmit": "user-prompt-submit", "user-prompt-submit": "user-prompt-submit",
        "pretooluse": "pre-tool-use", "pre-tool-use": "pre-tool-use",
        "posttooluse": "post-tool-use", "post-tool-use": "post-tool-use",
    }
    return _EVENT_ALIASES.get(kebab, _EVENT_ALIASES.get(kebab.replace("-", ""), kebab))


def normalize_client(value: Any) -> str:
    """Port of capture.normalize_client using Rust when available."""
    if _native is not None:
        return _native.normalize_client(value)
    raw = "" if value is None else str(value).strip().lower().replace(" ", "-")
    if not raw:
        return ""
    _CLIENT_ALIASES = {
        "claude": "claude", "claude-code": "claude", "claude_code": "claude",
        "codex": "codex", "codex-cli": "codex",
        "gemini": "gemini", "gemini-cli": "gemini",
        "hermes": "hermes", "hermes-agent": "hermes",
    }
    if raw in _CLIENT_ALIASES:
        return _CLIENT_ALIASES[raw]
    return raw[:100]


class ObservationBuffer:
    """Rust-backed capture buffer with fallback to Python SQLite."""

    def __init__(self, vault_path: str | None = None) -> None:
        if _native is not None:
            self._inner = _native.ObservationBuffer(vault_path)
            self._has_native = True
        else:
            self._has_native = False
            # Python fallback - would need full port of ObservationBuffer
            raise NotImplementedError("ObservationBuffer Python fallback not implemented")

    def append(self, payload: Observation | dict) -> dict:
        if self._has_native:
            from .capture import Observation
            observation = payload if isinstance(payload, Observation) else Observation.from_payload(payload)
            return self._inner.append(observation)
        raise NotImplementedError

    def claim_for_session(self, session_id: str, owner: str, limit: int = 500, lease_seconds: int = 300) -> list[dict]:
        if self._has_native:
            return self._inner.claim_for_session(session_id, owner, limit, lease_seconds)
        raise NotImplementedError

    def mark_status(self, observation_ids: list[str], status: str, error: str | None = None, owner: str | None = None) -> int:
        if self._has_native:
            return self._inner.mark_status(observation_ids, status, error, owner)
        raise NotImplementedError

    def for_session(self, session_id: str, limit: int = 500, statuses: list[str] | None = None) -> list[dict]:
        if self._has_native:
            return self._inner.for_session(session_id, limit, statuses)
        raise NotImplementedError

    def prune_expired(self, include_pending: bool = False) -> int:
        if self._has_native:
            return self._inner.prune_expired(include_pending)
        raise NotImplementedError

    def pending_count(self, statuses: list[str] | None = None) -> int:
        if self._has_native:
            return self._inner.pending_count(statuses)
        raise NotImplementedError

    def pending_sessions(self, limit: int = 100) -> list[str]:
        if self._has_native:
            return self._inner.pending_sessions(limit)
        raise NotImplementedError

    def recover_processing(self, session_id: str) -> int:
        if self._has_native:
            return self._inner.recover_processing(session_id)
        raise NotImplementedError

    def sessions_for_project(self, project: str, statuses: list[str] | None = None, limit: int = 100) -> list[str]:
        if self._has_native:
            return self._inner.sessions_for_project(project, statuses, limit)
        raise NotImplementedError

    def batch_sequence(self, rows: list[dict], limit: int = 500) -> int:
        if self._has_native:
            return self._inner.batch_sequence(rows, limit)
        raise NotImplementedError

    def close(self) -> None:
        if self._has_native:
            self._inner.close()


# --------------------------------------------------------------------------- manager

def best_match(text: str, kind: str, rows: list[dict], norm_cache: dict | None = None) -> tuple[dict | None, float]:
    """Port of manager._best_match using Rust when available."""
    if _native is not None:
        return _native.best_match(text, kind, rows, norm_cache)
    # Python fallback
    from difflib import SequenceMatcher

    from .utils import normalize_text
    norm = normalize_text(text)
    best_row, best_ratio = None, 0.0
    text_length = len(norm)
    if text_length == 0:
        return None, 0.0
    threshold = 0.85
    minimum = max(1, int((threshold * text_length / (2 - threshold)) + 0.999999))
    maximum = int((2 - threshold) * text_length / threshold)
    cache = norm_cache or {}
    for row in rows:
        row_text = row.get("text", "")
        row_length = len(row_text)
        if row_length < minimum or row_length > maximum:
            continue
        row_id = row.get("memory_id", "")
        existing = cache.get(row_id)
        if existing is None:
            existing = normalize_text(row_text)
            cache[row_id] = existing
        ratio = SequenceMatcher(None, norm, existing).ratio()
        if ratio > best_ratio:
            best_row, best_ratio = row, ratio
    return best_row, best_ratio


def semantic_candidates(kind: str, rows: list[dict], embeddings: list[tuple[str, list[float]]], threshold: float = 0.85, limit: int = 200) -> list[dict]:
    """Port of index.semantic_candidates using Rust when available."""
    if _native is not None:
        return _native.semantic_candidates(kind, threshold, limit, rows, embeddings)
    # Python fallback
    if len(rows) < 2:
        return []
    vectors_by_parent: dict[str, list[list[float]]] = {row["memory_id"]: [] for row in rows}
    for emb_id, vector in embeddings:
        parent_id = emb_id.split("::")[0] if "::" in emb_id else emb_id
        if parent_id in vectors_by_parent:
            vectors_by_parent[parent_id].append(vector)
    pairs = []
    for index, left in enumerate(rows):
        left_vectors = vectors_by_parent[left["memory_id"]]
        for right in rows[index + 1:]:
            right_vectors = vectors_by_parent[right["memory_id"]]
            scores = [cosine_similarity(lv, rv) for lv in left_vectors for rv in right_vectors]
            if not scores:
                continue
            score = max(scores)
            if score >= threshold and left.get("normalized_hash") != right.get("normalized_hash"):
                pairs.append({
                    "kind": kind,
                    "memory_ids": [left["memory_id"], right["memory_id"]],
                    "subjects": [left["subject"], right["subject"]],
                    "similarity": round(score, 4),
                })
    pairs.sort(key=lambda item: item["similarity"], reverse=True)
    return pairs[:max(1, limit)]


class NormCache:
    """Rust-backed norm cache with fallback to Python dict."""

    def __init__(self):
        if _native is not None:
            self._inner = _native.NormCache()
            self._has_native = True
        else:
            self._inner: dict[str, str] = {}
            self._has_native = False

    def get_or_compute(self, memory_id: str, text: str) -> str:
        if self._has_native:
            return self._inner.get_or_compute(memory_id, text)
        if memory_id in self._inner:
            return self._inner[memory_id]
        from .utils import normalize_text
        result = normalize_text(text)
        self._inner[memory_id] = result
        return result

    def get(self, memory_id: str) -> str | None:
        if self._has_native:
            return self._inner.get(memory_id)
        return self._inner.get(memory_id)

    def insert(self, memory_id: str, normalized: str) -> None:
        if self._has_native:
            self._inner.insert(memory_id, normalized)
        else:
            self._inner[memory_id] = normalized

    def clear(self) -> None:
        if self._has_native:
            self._inner.clear()
        else:
            self._inner.clear()

    def __len__(self) -> int:
        if self._has_native:
            return self._inner.len()
        return len(self._inner)


# --------------------------------------------------------------------------- constants

def get_true_duplicate_threshold() -> float:
    if _native is not None:
        return _native.get_true_duplicate_threshold()
    return 0.985


def get_duplicate_update_band() -> float:
    if _native is not None:
        return _native.get_duplicate_update_band()
    return 0.85


# --------------------------------------------------------------------------- capture helpers

def sanitize_text(value: str | None = None, excluded_paths: list[str] | None = None) -> str:
    """Port of capture.sanitize_text using Rust when available."""
    if _native is not None:
        return _native.sanitize_text(value, excluded_paths or [])
    # Python fallback
    from .capture import _sanitize_text
    return _sanitize_text(value, excluded_paths or [])


def sanitize_payload(payload: dict) -> dict:
    """Port of capture.sanitize_payload using Rust when available."""
    if _native is not None:
        return _native.sanitize_payload(payload)
    from .capture import _sanitize_payload
    return _sanitize_payload(payload)


def create_observation_buffer(path: str | None = None) -> ObservationBuffer:
    """Create an ObservationBuffer, using Rust when available."""
    if _native is not None:
        return _native.ObservationBuffer(path)
    raise NotImplementedError("ObservationBuffer Python fallback not implemented")
