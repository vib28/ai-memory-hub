from memory_hub.benchmark_handoff import run_benchmark, write_report


def test_replay_covers_both_directions_and_arms_without_live_usage():
    report = run_benchmark()

    assert report["pair_count"] == 30
    assert report["destination_session_count"] == 60
    assert {pair["direction"] for pair in report["pairs"]} == {"claude->codex", "codex->claude"}
    assert {case["arm"] for case in report["cases"]} == {"off", "on"}
    assert all(case["snapshot_id"] == next(
        pair["snapshot_id"] for pair in report["pairs"] if pair["pair_id"] == case["pair_id"]
    ) for case in report["cases"])
    assert all(case["usage"]["destination_provider"]["input_tokens"]["value"] is None
               for case in report["cases"])
    assert report["live_verification"]["status"] == "not-run"
    assert report["gate"]["status"] == "open"


def test_replay_report_keeps_formula_and_unavailable_counter_semantics(tmp_path):
    report = run_benchmark(pairs_per_task=1)
    savings = report["aggregate"]["savings"]["whole_workflow"]
    off = report["aggregate"]["off"]["whole_workflow_tokens"]
    on = report["aggregate"]["on"]["whole_workflow_tokens"]
    assert savings["absolute"] == off - on
    assert savings["percent"] == round(100 * (off - on) / off, 4)
    assert all(case["usage"]["source_provider"]["input_tokens"]["basis"] == "unavailable"
               for case in report["cases"])

    json_path = tmp_path / "result.json"
    markdown_path = tmp_path / "result.md"
    write_report(report, json_path=json_path, markdown_path=markdown_path)
    assert "live gate remains open" in markdown_path.read_text(encoding="utf-8")
    assert json_path.exists()
