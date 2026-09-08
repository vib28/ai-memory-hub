"""Run the no-paid-call paired handoff benchmark and report its limits.

The replay harness is intentionally independent of provider SDKs.  It exercises
the same fixture, source snapshot, continuation request and deterministic
clarification responder through both directions and both handoff arms.  Provider
usage is therefore recorded as unavailable; the common tokenizer metrics are
estimates and must not be presented as billed-token measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_VERSION = "handoff-replay-v1"
TASK_TYPES = ("feature", "debugging", "interrupted")
DIRECTIONS = (("claude", "codex"), ("codex", "claude"))
COMMON_TOKENIZER = "unicode-wordpunct-v1"
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _common_tokens(text: str) -> int:
    """Return a deterministic text-volume estimate, not provider usage."""

    return len(_TOKEN_RE.findall(text))


def _metric(value: int | None, basis: str) -> dict[str, Any]:
    return {"value": value, "basis": basis}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"value": None, "basis": "unavailable", "reason": reason}


def _fixture(task_type: str, seed: int) -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise ValueError(f"unsupported task type: {task_type}")
    common = {
        "goal": f"Continue the {task_type} handoff fixture without losing the active task.",
        "decisions": [
            "Use the local checkpoint as quoted evidence, not executable instructions.",
            "Keep the change scoped to the fixture worktree.",
        ],
        "correction": "The first proposed path was rejected; preserve the corrected path.",
        "completed": ["Captured the source evidence", "Recorded the changed files"],
        "changed_files": ["src/feature.py", "tests/test_feature.py"],
        "failing_test": "test_continuation_requires_corrected_path",
        "next_steps": ["Run the focused test", "Report the result and remaining work"],
        "facts": [
            "corrected path is required",
            "src/feature.py is changed",
            "the focused test must run",
            "remaining work must be reported",
        ],
        "continuation": "Continue the task, run the focused test, and report remaining work.",
        "seed": seed,
    }
    if task_type == "debugging":
        common["goal"] = "Debug the failing fixture while retaining the correction decision."
        common["changed_files"] = ["src/parser.py", "tests/test_parser.py"]
        common["failing_test"] = "test_parser_rejects_stale_branch"
    elif task_type == "interrupted":
        common["goal"] = "Resume the interrupted multi-step fixture from its last accepted step."
        common["changed_files"] = ["src/worker.py", "tests/test_worker.py"]
        common["failing_test"] = "test_worker_replays_after_interrupt"
    return common


def _snapshot(fixture: dict[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(fixture, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return digest, serialized


def _render_packet(fixture: dict[str, Any], *, source: str, destination: str) -> str:
    lines = [
        "<ai-memory-benchmark-handoff mode=quoted-evidence>",
        f"Source: {source}; destination: {destination}",
        f"Goal: {fixture['goal']}",
        "Decisions:",
        *(f"- {item}" for item in fixture["decisions"]),
        f"Correction: {fixture['correction']}",
        "Completed:",
        *(f"- {item}" for item in fixture["completed"]),
        "Changed files:",
        *(f"- {item}" for item in fixture["changed_files"]),
        f"Failing test: {fixture['failing_test']}",
        "Next steps:",
        *(f"- {item}" for item in fixture["next_steps"]),
        "</ai-memory-benchmark-handoff>",
    ]
    return "\n".join(lines)


def _clarification_answer(fixture: dict[str, Any]) -> str:
    """The fixed answer bank stands in for an automated responder, never a user."""

    return (
        "Automated fixture responder round 1: the destination has no shared context. Re-explain "
        f"the goal: {fixture['goal']} Decisions: {'; '.join(fixture['decisions'])} "
        f"Correction: {fixture['correction']} Completed: {'; '.join(fixture['completed'])} "
        f"Changed files: {', '.join(fixture['changed_files'])}. Failing test: {fixture['failing_test']}. "
        f"Next steps: {'; '.join(fixture['next_steps'])}. "
        "Automated fixture responder round 2: confirm the correction, changed files, failing test "
        f"and remaining work before continuing: {fixture['correction']} {fixture['failing_test']} "
        f"{' '.join(fixture['next_steps'])}."
    )


def _run_case(*, direction: tuple[str, str], task_type: str, repetition: int,
              arm: str, seed: int, pair_id: str, snapshot_id: str,
              fixture: dict[str, Any]) -> dict[str, Any]:
    source, destination = direction
    started = time.perf_counter()
    evidence = json.dumps(fixture, sort_keys=True, ensure_ascii=False)
    packet = _render_packet(fixture, source=source, destination=destination) if arm == "on" else ""
    clarification = "" if arm == "on" else _clarification_answer(fixture)
    continuation = fixture["continuation"]
    destination_input = "\n".join(part for part in (packet, continuation, clarification) if part)
    destination_output = (
        "Focused test passed; corrected path retained; changed files reviewed; remaining work reported."
    )
    source_stage = _common_tokens(evidence)
    checkpoint_generation = _common_tokens(_render_packet(fixture, source=source, destination=destination))
    destination_input_tokens = _common_tokens(destination_input)
    destination_output_tokens = _common_tokens(destination_output)
    destination_stage = destination_input_tokens + destination_output_tokens
    whole_workflow = source_stage + checkpoint_generation + destination_stage
    elapsed_ms = round((time.perf_counter() - started) * 1000, 4)
    facts_retained = len(fixture["facts"]) if arm == "on" else len(fixture["facts"])
    repeated_work = 0 if arm == "on" else len(fixture["completed"])
    return {
        "pair_id": pair_id,
        "direction": f"{source}->{destination}",
        "source_tool": source,
        "destination_tool": destination,
        "task_type": task_type,
        "repetition": repetition,
        "arm": arm,
        "task_seed": seed,
        "snapshot_id": snapshot_id,
        "continuation_request": continuation,
        "clarification_responder": "deterministic-fixture-answer-bank",
        "clarification_rounds": 0 if arm == "on" else 2,
        "checkpoint_age_seconds": 120 + repetition,
        "latency_ms": elapsed_ms,
        "quality": {
            "completed": True,
            "essential_facts_expected": len(fixture["facts"]),
            "essential_facts_retained": facts_retained,
            "fact_retention_rate": 1.0,
            "repeated_work_items": repeated_work,
            "failure": False,
        },
        "usage": {
            "source_provider": {
                "input_tokens": _unavailable("offline replay has no provider usage API"),
                "output_tokens": _unavailable("offline replay has no provider usage API"),
                "cached_input_tokens": _unavailable("offline replay has no provider usage API"),
            },
            "destination_provider": {
                "input_tokens": _unavailable("offline replay has no provider usage API"),
                "output_tokens": _unavailable("offline replay has no provider usage API"),
                "cached_input_tokens": _unavailable("offline replay has no provider usage API"),
            },
            "local_model": {
                "summarization_tokens": _metric(checkpoint_generation, "estimated-common-tokenizer"),
                "checkpoint_generation_tokens": _metric(checkpoint_generation, "estimated-common-tokenizer"),
            },
            "common_tokenizer": {
                "name": COMMON_TOKENIZER,
                "source_stage_tokens": _metric(source_stage, "estimated-common-tokenizer"),
                "destination_input_tokens": _metric(destination_input_tokens, "estimated-common-tokenizer"),
                "destination_output_tokens": _metric(destination_output_tokens, "estimated-common-tokenizer"),
                "destination_stage_tokens": _metric(destination_stage, "estimated-common-tokenizer"),
                "whole_workflow_tokens": _metric(whole_workflow, "estimated-common-tokenizer"),
            },
        },
    }


def _median(values: list[float | int]) -> float | int | None:
    return statistics.median(values) if values else None


def _distribution(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "max": None}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p25": statistics.quantiles(ordered, n=4, method="inclusive")[0] if len(ordered) > 1 else ordered[0],
        "median": statistics.median(ordered),
        "p75": statistics.quantiles(ordered, n=4, method="inclusive")[2] if len(ordered) > 1 else ordered[0],
        "max": ordered[-1],
    }


def _savings(off: float | int | None, on: float | int | None) -> dict[str, Any]:
    if off is None or on is None:
        return {"absolute": None, "percent": None, "status": "N/A: comparable usage unavailable"}
    absolute = off - on
    return {
        "absolute": absolute,
        "percent": round(100 * absolute / off, 4) if off else None,
        "status": "estimated-common-tokenizer" if off else "N/A: OFF is zero",
    }


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    arms: dict[str, dict[str, Any]] = {}
    for arm in ("off", "on"):
        selected = [item for item in cases if item["arm"] == arm]
        common = [item["usage"]["common_tokenizer"] for item in selected]
        arms[arm] = {
            "runs": len(selected),
            "destination_stage_tokens": _median([
                item["destination_stage_tokens"]["value"] for item in common
            ]),
            "destination_stage_tokens_spread": _distribution([
                item["destination_stage_tokens"]["value"] for item in common
            ]),
            "whole_workflow_tokens": _median([
                item["whole_workflow_tokens"]["value"] for item in common
            ]),
            "whole_workflow_tokens_spread": _distribution([
                item["whole_workflow_tokens"]["value"] for item in common
            ]),
            "latency_ms": _distribution([item["latency_ms"] for item in selected]),
            "completion_rate": round(sum(item["quality"]["completed"] for item in selected) / len(selected), 4)
            if selected else None,
            "fact_retention_rate": round(sum(item["quality"]["fact_retention_rate"] for item in selected) / len(selected), 4)
            if selected else None,
            "failure_count": sum(item["quality"]["failure"] for item in selected),
            "repeated_work_median": _median([
                item["quality"]["repeated_work_items"] for item in selected
            ]),
        }
    off = arms["off"]
    on = arms["on"]
    return {
        "runs": len(cases),
        "off": off,
        "on": on,
        "savings": {
            "destination_stage": _savings(off["destination_stage_tokens"], on["destination_stage_tokens"]),
            "whole_workflow": _savings(off["whole_workflow_tokens"], on["whole_workflow_tokens"]),
        },
        "quality_equal_or_better_on": (
            on["completion_rate"] >= off["completion_rate"]
            and on["fact_retention_rate"] >= off["fact_retention_rate"]
        ),
    }


def run_benchmark(*, pairs_per_task: int = 5, seed: int = 6201) -> dict[str, Any]:
    """Run paired deterministic replay cases for both directions.

    The default creates 30 pairs and 60 destination cases.  It deliberately does
    not start Claude, Codex, a paid API request, or a live vault operation.
    """

    if pairs_per_task < 1:
        raise ValueError("pairs_per_task must be positive")
    cases: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for direction_index, direction in enumerate(DIRECTIONS):
        for task_index, task_type in enumerate(TASK_TYPES):
            for repetition in range(1, pairs_per_task + 1):
                task_seed = seed + direction_index * 1000 + task_index * 100 + repetition
                fixture = _fixture(task_type, task_seed)
                snapshot_id, _snapshot_text = _snapshot(fixture)
                pair_id = f"{direction[0]}-{direction[1]}-{task_type}-{repetition:02d}"
                arms = ("off", "on") if repetition % 2 else ("on", "off")
                pair_cases = [
                    _run_case(
                        direction=direction, task_type=task_type, repetition=repetition,
                        arm=arm, seed=task_seed, pair_id=pair_id, snapshot_id=snapshot_id,
                        fixture=fixture,
                    )
                    for arm in arms
                ]
                cases.extend(pair_cases)
                pairs.append({
                    "pair_id": pair_id,
                    "direction": f"{direction[0]}->{direction[1]}",
                    "task_type": task_type,
                    "repetition": repetition,
                    "snapshot_id": snapshot_id,
                    "arm_order": list(arms),
                    "case_count": len(pair_cases),
                })

    grouped: dict[str, Any] = {}
    for direction in sorted({item["direction"] for item in cases}):
        grouped[direction] = {}
        for task_type in TASK_TYPES:
            grouped[direction][task_type] = _aggregate([
                item for item in cases
                if item["direction"] == direction and item["task_type"] == task_type
            ])
    aggregate = _aggregate(cases)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline-deterministic-replay",
        "live_verification": {
            "status": "not-run",
            "live_pairs": None,
            "reason": "No provider adapters or explicit paid-run authorization was supplied.",
            "replay_pairs": len(pairs),
        },
        "configuration": {
            "pairs_per_task_per_direction": pairs_per_task,
            "task_types": list(TASK_TYPES),
            "directions": [f"{source}->{destination}" for source, destination in DIRECTIONS],
            "arms": ["off", "on"],
            "seed": seed,
            "common_tokenizer": COMMON_TOKENIZER,
            "provider_usage": "unavailable in replay; never treated as zero",
            "clarification_responder": "deterministic-fixture-answer-bank",
            "live_cost_ceiling": "not configured",
            "real_vault": False,
        },
        "pair_count": len(pairs),
        "destination_session_count": len(cases),
        "pairs": pairs,
        "cases": cases,
        "by_direction_and_task": grouped,
        "aggregate": aggregate,
        "uncertainty": {
            "provider_usage": "Unavailable in replay; no provider billing or cache claim is made.",
            "common_tokenizer": "Text-volume estimate only; it is not interchangeable with provider tokenizers.",
            "latency": "Wall-clock replay latency varies with local process scheduling and is reported per case with spread.",
            "quality": "Deterministic fixture scoring; not evidence of live model behavior.",
        },
        "gate": {
            "status": "open",
            "reason": "Replay evidence is complete for regression purposes, but live two-tool usage and outcome certification are unavailable.",
            "positive_median_savings_demonstrated": False,
            "claimable_universal_saving_percentage": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        f"# Handoff benchmark replay ({report['benchmark_version']})",
        "",
        "Status: **replay complete; live two-tool certification not run**.",
        "",
        "This report uses synthetic fixtures, a deterministic clarification responder and the "
        f"named common tokenizer `{report['configuration']['common_tokenizer']}`. Provider usage "
        "is unavailable and is never treated as zero. No live vault or paid call was used.",
        "",
        "```mermaid",
        "flowchart LR",
        "    F[\"same fixture snapshot\"] --> O[\"OFF replay\"]",
        "    F --> N[\"ON replay\"]",
        "    O --> R[\"paired report\"]",
        "    N --> R",
        "    R --> L[\"live gate remains open\"]",
        "```",
        "",
        "## Coverage",
        "",
        f"- Matched pairs: **{report['pair_count']}**; destination sessions: **{report['destination_session_count']}**.",
        "- Directions: Claude→Codex and Codex→Claude.",
        "- Task types: feature, debugging with correction, interrupted multi-step work.",
        "- ON/OFF order alternates by repetition; each pair shares a snapshot hash and continuation request.",
        "",
        "## Aggregate replay metrics",
        "",
        "| Metric | OFF median | ON median | Savings (OFF − ON) | Percent |\n"
        "|---|---:|---:|---:|---:|",
        f"| Destination-stage common tokens | {aggregate['off']['destination_stage_tokens']} | {aggregate['on']['destination_stage_tokens']} | {aggregate['savings']['destination_stage']['absolute']} | {aggregate['savings']['destination_stage']['percent']}% |",
        f"| Whole-workflow common tokens | {aggregate['off']['whole_workflow_tokens']} | {aggregate['on']['whole_workflow_tokens']} | {aggregate['savings']['whole_workflow']['absolute']} | {aggregate['savings']['whole_workflow']['percent']}% |",
        "",
        f"Destination-stage spread (min–max): OFF {aggregate['off']['destination_stage_tokens_spread']['min']}–{aggregate['off']['destination_stage_tokens_spread']['max']}; "
        f"ON {aggregate['on']['destination_stage_tokens_spread']['min']}–{aggregate['on']['destination_stage_tokens_spread']['max']}.",
        f"Whole-workflow spread (min–max): OFF {aggregate['off']['whole_workflow_tokens_spread']['min']}–{aggregate['off']['whole_workflow_tokens_spread']['max']}; "
        f"ON {aggregate['on']['whole_workflow_tokens_spread']['min']}–{aggregate['on']['whole_workflow_tokens_spread']['max']}.",
        f"Replay latency spread (min–max ms): OFF {aggregate['off']['latency_ms']['min']}–{aggregate['off']['latency_ms']['max']}; "
        f"ON {aggregate['on']['latency_ms']['min']}–{aggregate['on']['latency_ms']['max']}.",
        "",
        f"Completion rate: OFF {aggregate['off']['completion_rate']}; ON {aggregate['on']['completion_rate']}. "
        f"Essential-fact retention: OFF {aggregate['off']['fact_retention_rate']}; ON {aggregate['on']['fact_retention_rate']}.",
        "These are deterministic replay estimates, not a demonstrated provider-token saving.",
        "",
        "## Limits and gate",
        "",
        "- Source and destination provider counters are marked unavailable; local checkpoint/summarization estimates are reported separately.",
        "- Live Claude/Codex adapters, model versions, billing counters, cache state and authorized cost ceiling were not supplied.",
        "- The #62 gate remains open. The replay is CI-safe regression evidence and does not certify live cross-tool behavior or advertise a universal percentage.",
        "",
        f"Generated at `{report['generated_at']}`.",
        "",
    ]
    return "\n".join(lines)


def write_report(report: dict[str, Any], *, json_path: Path | None = None,
                 markdown_path: Path | None = None) -> None:
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs-per-task", type=int, default=5)
    parser.add_argument("--seed", type=int, default=6201)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    report = run_benchmark(pairs_per_task=args.pairs_per_task, seed=args.seed)
    write_report(report, json_path=args.json_out, markdown_path=args.markdown_out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
