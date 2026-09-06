from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory_hub.embeddings import LocalEmbeddingProvider, cosine_similarity
from memory_hub.index import MemoryIndex
from memory_hub.models import MemoryRecord


class FakeEmbeddingProvider:
    model = "fake"

    def embed(self, texts):
        return [[1.0, 0.0] if "auth" in text.lower() else [0.0, 1.0] for text in texts]


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

    def test_vector_candidates_are_bounded_to_same_kind(self):
        with tempfile.TemporaryDirectory() as temp:
            index = MemoryIndex(Path(temp), FakeEmbeddingProvider())
            index.upsert(MemoryRecord("one", "/one.md", "Authentication refresh decision",
                                      "decision", "decided", "auth", "user", "2026-09-06"))
            index.upsert(MemoryRecord("two", "/two.md", "Authentication project note",
                                      "project", "stated", "auth", "user", "2026-09-06"))
            index.upsert(MemoryRecord("three", "/three.md", "Database decision",
                                      "decision", "decided", "db", "user", "2026-09-06"))
            rows = index.vector_candidates("auth flow", "decision", limit=1)
            self.assertEqual([row["memory_id"] for row in rows], ["one"])
            index.close()


if __name__ == "__main__":
    unittest.main()
