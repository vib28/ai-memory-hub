from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory_hub.embeddings import LocalEmbeddingProvider, cosine_similarity
from memory_hub.index import MemoryIndex, embedding_text_for
from memory_hub.models import MemoryRecord


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

if __name__ == "__main__":
    unittest.main()
