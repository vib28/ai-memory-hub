"""Test that native backend imports correctly and Python fallback works."""
from __future__ import annotations

import os
import sys

# Force Python fallback for testing
os.environ["MEMORY_NATIVE_BACKEND"] = "false"

from memory_hub import native_backend


def test_tokenize():
    tokens = native_backend.tokenize("The quick brown fox jumps over the lazy dog")
    assert isinstance(tokens, list)
    assert len(tokens) > 0
    # Stopwords should be filtered
    assert "the" not in tokens


def test_tokenize_batch():
    texts = [
        "First memory about Python",
        "Second memory about Rust",
        "Third memory about testing",
    ]
    result = native_backend.tokenize_batch(texts)
    assert len(result) == 3
    assert all(isinstance(r, list) for r in result)


def test_token_cache():
    cache = native_backend.TokenCache()
    texts = [
        ("id1", "Python programming with classes and objects"),
        ("id2", "Rust memory safety and borrowing"),
        ("id3", "Testing with pytest and fixtures"),
    ]
    cache.build(texts)
    results = cache.query("python classes", 5)
    assert len(results) > 0
    assert results[0][0] == "id1"


def test_cosine_similarity():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]

    assert native_backend.cosine_similarity(a, b) == 1.0
    assert native_backend.cosine_similarity(a, c) == 0.0


def test_cosine_top_k():
    query = [1.0, 0.0, 0.0]
    matrix = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.5, 0.5, 0.0],
    ]
    results = native_backend.cosine_top_k(query, matrix, 2)
    assert len(results) == 2
    assert results[0][0] == 0  # First vector is identical


def test_normalize_vector():
    v = [3.0, 4.0]
    normalized = native_backend.normalize_vector(v)
    assert abs(sum(x * x for x in normalized) - 1.0) < 1e-6


def test_pairwise_cosine():
    embeddings = [
        ("a", [1.0, 0.0]),
        ("b", [1.0, 0.0]),
        ("c", [0.0, 1.0]),
    ]
    results = native_backend.pairwise_cosine(embeddings, 0.5)
    assert len(results) >= 1


def test_is_native_available():
    assert native_backend.is_native_available() is False  # We forced fallback


if __name__ == "__main__":
    import traceback
    tests = [
        test_tokenize,
        test_tokenize_batch,
        test_token_cache,
        test_cosine_similarity,
        test_cosine_top_k,
        test_normalize_vector,
        test_pairwise_cosine,
        test_is_native_available,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✓ {test.__name__}")
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    if failed:
        print(f"\n{failed} tests failed")
        sys.exit(1)
    else:
        print(f"\nAll {len(tests)} tests passed")
