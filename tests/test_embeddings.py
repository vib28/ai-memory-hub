from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from memory_hub.embeddings import LocalEmbeddingProvider, cosine_similarity
from memory_hub.index import MemoryIndex, embedding_text_for
from memory_hub.models import MemoryRecord
from memory_hub.vault import parse_records


class FakeEmbeddingProvider:
    model = "fake"

    def embed(self, texts):
        return [[1.0, 0.0] if "auth" in text.lower() else [0.0, 1.0] for text in texts]


class RecordingEmbeddingProvider:
    """Captures exactly what string each call embedded, so a test can assert
    on the input to the model, not just its (fake) output."""
    model = "recording"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.extend(texts)
        return [[float(len(t)), 0.0] for t in texts]


class SectionEmbeddingProvider:
    model = "sections"

    def embed(self, texts):
        return [[1.0, 0.0] if "sqlite" in text.lower() else [0.0, 1.0] for text in texts]


class EmbeddingTests(unittest.TestCase):
    def test_cosine_similarity(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_index_uses_vector_results_and_fts_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            index = MemoryIndex(Path(temp), FakeEmbeddingProvider())
            index.upsert(MemoryRecord("one", "/one.md", "Authentication refresh decision", "decision", "decided", "auth", "user", "2026-09-06"))
            index.upsert(MemoryRecord("two", "/two.md", "Database migration notes", "topic", "stated", "db", "user", "2026-09-06"))
            results = index.search("auth flow", 2)
            self.assertEqual(results[0]["memory_id"], "one")
            index.embedding_provider = None
            self.assertEqual(index.search("database", 1)[0]["memory_id"], "two")
            index.close()

    def test_semantic_candidates_are_read_only_audit_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            index = MemoryIndex(Path(temp), FakeEmbeddingProvider())
            index.upsert(MemoryRecord("one", "/one.md", "Authentication refresh decision",
                                      "decision", "decided", "auth-one", "user", "2026-09-06"))
            index.upsert(MemoryRecord("two", "/two.md", "Authentication migration decision",
                                      "decision", "decided", "auth-two", "user", "2026-09-06"))
            pairs = index.semantic_candidates("decision")
            self.assertEqual(pairs[0]["memory_ids"], ["one", "two"])
            self.assertGreaterEqual(pairs[0]["similarity"], 0.85)
            index.close()

    def test_embedding_text_includes_kind_and_subject(self):
        """#39: record.text alone carries no signal about which kind/subject
        bucket a memory belongs to, so two records with identical wording
        under unrelated kinds would otherwise embed as the exact same input."""
        record = MemoryRecord("id1", "/p.md", "Prefers a concise response format.",
                              "preference", "preference", "response-format", "user", "2026-09-06")
        text = embedding_text_for(record)
        self.assertIn("preference", text)
        self.assertIn("response-format", text)
        self.assertIn("Prefers a concise response format.", text)

    def test_records_with_identical_text_embed_differently_across_kinds(self):
        provider = RecordingEmbeddingProvider()
        with tempfile.TemporaryDirectory() as temp:
            index = MemoryIndex(Path(temp), provider)
            same_text = "Keep responses short and direct."
            index.upsert(MemoryRecord("a", "/a.md", same_text, "preference", "preference",
                                      "response-format", "user", "2026-09-06"))
            index.upsert(MemoryRecord("b", "/b.md", same_text, "project", "stated",
                                      "response-format", "user", "2026-09-06"))
            index.close()
        # Before #39, both calls embedded the identical raw string; now the
        # kind prefix makes them different inputs to the model.
        self.assertEqual(len(provider.calls), 2)
        self.assertNotEqual(provider.calls[0], provider.calls[1])

    def test_query_embedding_has_no_kind_subject_prefix(self):
        """Asymmetric retrieval: only the indexed side gets a prefix -- a
        search query has no kind/subject of its own to prepend."""
        provider = RecordingEmbeddingProvider()
        with tempfile.TemporaryDirectory() as temp:
            index = MemoryIndex(Path(temp), provider)
            index.upsert(MemoryRecord("a", "/a.md", "Keep responses short.",
                                      "preference", "preference", "response-format", "user", "2026-09-06"))
            provider.calls.clear()
            index.search("responses", 5)
            index.close()
        self.assertEqual(provider.calls, ["responses"])

    def test_session_sections_embed_separately_and_resolve_to_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "sessions" / "codex.md"
            path.parent.mkdir()
            path.write_text(
                "---\n"
                "type: session\n"
                "---\n\n"
                "## codex-retrieval-2026-09-09-120000\n"
                "**Model:** codex\n"
                "**Session title:** Retrieval\n"
                "**Date:** 2026-09-09T12:00:00\n"
                "**Project:** None\n"
                "**Tags:** #codex #2026-09-09\n\n"
                "### Investigated\n"
                "- Reviewed the OAuth refresh flow.\n\n"
                "### Learned\n"
                "- SQLite WAL checkpoints keep writes recoverable.\n\n"
                "### Completed\n\n"
                "### Next Steps\n"
                "- Verify the worker retry path.\n\n"
                "<!-- session:session-1 -->\n",
                encoding="utf-8",
            )
            record = parse_records(path, root)[0]
            self.assertEqual(
                record.text,
                "Reviewed the OAuth refresh flow. SQLite WAL checkpoints keep writes recoverable. "
                "Verify the worker retry path.",
            )
            provider = SectionEmbeddingProvider()
            index = MemoryIndex(root, provider)
            index.upsert(record)

            keys = [row[0] for row in index.conn.execute(
                "SELECT memory_id FROM memory_embeddings ORDER BY memory_id"
            )]
            self.assertEqual(keys, ["session-1::investigated", "session-1::learned", "session-1::next-steps"])
            self.assertEqual(index.search("SQLite WAL", 1)[0]["memory_id"], "session-1")

            live_vectors = [tuple(row) for row in index.conn.execute(
                "SELECT memory_id, vector_json, content_hash FROM memory_embeddings ORDER BY memory_id"
            )]
            index.rebuild(parse_records(path, root))
            rebuilt_vectors = [tuple(row) for row in index.conn.execute(
                "SELECT memory_id, vector_json, content_hash FROM memory_embeddings ORDER BY memory_id"
            )]
            self.assertEqual(rebuilt_vectors, live_vectors)
            index.close()

    def test_semantic_candidates_resolve_chunked_session_pairs_to_parent_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "sessions" / "codex.md"
            path.parent.mkdir()
            path.write_text(
                "---\n"
                "type: session\n"
                "---\n\n"
                "## first\n### Investigated\n- SQLite recovery notes.\n\n<!-- session:first -->\n\n"
                "## second\n### Learned\n- SQLite recovery decisions.\n\n<!-- session:second -->\n",
                encoding="utf-8",
            )
            records = parse_records(path, root)
            index = MemoryIndex(root, SectionEmbeddingProvider())
            for record in records:
                index.upsert(record)
            pairs = index.semantic_candidates("session")
            self.assertEqual(pairs[0]["memory_ids"], ["first", "second"])
            self.assertNotIn("::", " ".join(pairs[0]["memory_ids"]))
            index.close()

    def test_provider_sorts_response_by_index(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps({"data": [{"index": 1, "embedding": [2]}, {"index": 0, "embedding": [1]}]}).encode()
        provider = LocalEmbeddingProvider("http://local/v1", "nomic-embed-text")
        def provider_urlopen(*args, **kwargs):
            return Response()
        import unittest.mock
        with unittest.mock.patch("urllib.request.urlopen", provider_urlopen):
            self.assertEqual(provider.embed(["a", "b"]), [[1.0], [2.0]])

    def test_embedding_model_role_is_configured_separately(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {
            "MEMORY_EMBED_BASE_URL": "http://embed/v1",
            "MEMORY_EMBED_MODEL": "nomic-embed-text",
        }, clear=False):
            provider = LocalEmbeddingProvider.from_environment()
        self.assertEqual(provider.base_url, "http://embed/v1")
        self.assertEqual(provider.model, "nomic-embed-text")

if __name__ == "__main__":
    unittest.main()
