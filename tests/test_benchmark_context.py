from scripts.benchmark_context import measure


def test_context_benchmark_reports_size_and_retrieval_metrics():
    result = measure(10, max_chars=1000)

    assert result["records"] == 10
    assert result["baseline"]["characters"] > result["optimized_context"]["characters"]
    assert "precision_at_3" in result["retrieval"]
    assert "precision_at_10" in result["retrieval"]
    assert result["token_counter"]
