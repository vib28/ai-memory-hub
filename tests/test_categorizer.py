"""#85: deterministic categorizer — no model, evidence-linked, high precision."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from memory_hub.categorizer import apply_from_observations, extract_memory_candidates
from memory_hub.manager import MemoryManager
from memory_hub.project_resolver import clear_cache


def _row(**kwargs):
    base = {
        "observation_id": kwargs.pop("observation_id", "obs-1"),
        "event": "post-tool-use",
        "tool": "Bash",
        "project": "widget-app",
        "input_summary": "",
        "output_summary": "",
        "prompt": "",
        "assistant": "",
    }
    base.update(kwargs)
    return base


# Twenty labelled sessions. Gold is the set of (kind, tag) pairs that MUST be
# proposed; extra proposals count against precision. Sessions 16-20 are negatives.
LABELED = [
    {"gold": {("preference", "preference")}, "rows": [
        _row(observation_id="s01", event="user-prompt-submit", tool="prompt",
             prompt="always use tables for status reports from now on")]},
    {"gold": {("decision", "decided")}, "rows": [
        _row(observation_id="s02", event="stop", tool="assistant",
             assistant="We decided to untrack the personal trade journal; the repo ships code only.")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s03", input_summary="git commit -m 'init'", output_summary="[master 1a] init")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s04", input_summary="git push origin master", output_summary="ok")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s05", input_summary="git checkout -b feat/x", output_summary="switched")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s06", output_summary="12 passed, 0 failed in 0.40s")]},
    {"gold": {("topic", "stated")}, "rows": [
        _row(observation_id="s07a", event="post-tool-use-failure", tool="Bash",
             input_summary="pytest", output_summary="error: exit 1"),
        _row(observation_id="s07b", event="post-tool-use", tool="Bash",
             input_summary="pytest -q", output_summary="ok")]},
    {"gold": {("preference", "preference")}, "rows": [
        _row(observation_id="s08", event="user-prompt-submit", tool="prompt",
             prompt="never write comments that just narrate the code")]},
    {"gold": {("decision", "decided")}, "rows": [
        _row(observation_id="s09", event="user-prompt-submit", tool="prompt",
             prompt="we'll go with sqlite instead of postgres for the local index")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s10", input_summary="git merge main", output_summary="fast-forward")]},
    {"gold": {("preference", "preference")}, "rows": [
        _row(observation_id="s11", event="user-prompt-submit", tool="prompt",
             prompt="prefer English for all assistant replies")]},
    {"gold": {("decision", "decided")}, "rows": [
        _row(observation_id="s12", event="stop", tool="assistant",
             assistant="Chose pytest over unittest for the new suite.")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s13", output_summary="3 failed 9 passed")]},
    {"gold": {("topic", "stated")}, "rows": [
        _row(observation_id="s14a", event="post-tool-use-failure", tool="Edit",
             output_summary="error: file locked"),
        _row(observation_id="s14b", event="post-tool-use", tool="Edit",
             output_summary="updated")]},
    {"gold": {("project", "stated")}, "rows": [
        _row(observation_id="s15", input_summary="git push --set-upstream origin feat", output_summary="done")]},
    {"gold": set(), "rows": [
        _row(observation_id="s16", event="pre-tool-use", tool="Read", input_summary="path=foo.py")]},
    {"gold": set(), "rows": [
        _row(observation_id="s17", event="session-start", tool="unknown", input_summary="startup")]},
    {"gold": set(), "rows": [
        _row(observation_id="s18", event="user-prompt-submit", tool="prompt", prompt="what time is it")]},
    {"gold": set(), "rows": [
        _row(observation_id="s19", event="session-heartbeat", tool="unknown")]},
    {"gold": set(), "rows": [
        _row(observation_id="s20", event="post-tool-use", tool="Bash",
             input_summary="ls", output_summary="a b c")]},
]


class CategorizerTests(unittest.TestCase):
    def test_no_llm_env_required(self):
        for key in list(os.environ):
            if key.startswith("MEMORY_LLM"):
                os.environ.pop(key)
        candidates = extract_memory_candidates(LABELED[0]["rows"], project="widget-app", writer="claude")
        assert candidates
        assert candidates[0].kind == "preference"

    def test_precision_on_labeled_fixture_set(self):
        true_pos = false_pos = false_neg = 0
        for session in LABELED:
            kinds = {(c.kind, c.tag) for c in extract_memory_candidates(
                session["rows"], project="widget-app", writer="claude")}
            gold = session["gold"]
            true_pos += len(kinds & gold)
            false_pos += len(kinds - gold)
            false_neg += len(gold - kinds)
        precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 1.0
        recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else 1.0
        assert len(LABELED) >= 20
        assert precision >= 0.9, f"precision={precision:.3f} recall={recall:.3f}"
        print(f"categorizer precision={precision:.3f} recall={recall:.3f} "
              f"tp={true_pos} fp={false_pos} fn={false_neg}")

    def test_secrets_never_pass(self):
        rows = [_row(observation_id="sec", event="user-prompt-submit", tool="prompt",
                     prompt="always store the api_key=sk-abcdefghijklmnopqrstuvwxyz123456")]
        candidates = extract_memory_candidates(rows, project="widget-app", writer="claude")
        assert candidates == []

    def test_evidence_ids_and_idempotent_queue(self):
        clear_cache()
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            manager = MemoryManager(vault)
            manager.initialize(Path(__file__).resolve().parents[1] / "vault_template")
            rows = LABELED[0]["rows"]
            first = apply_from_observations(manager, rows, write_mode="review", writer="claude",
                                            project="widget-app")
            second = apply_from_observations(manager, rows, write_mode="review", writer="claude",
                                             project="widget-app")
            assert first
            assert first[0]["status"] in {"queued", "queued_as_update"}
            assert first[0]["evidence_ids"]
            proposal = first[0]["proposal"]
            assert proposal.get("kind") == "preference"
            blob = str(proposal.get("provenance") or proposal.get("payload") or "")
            assert any(item in blob for item in first[0]["evidence_ids"])
            assert all(item["status"] in {"already_pending", "duplicate", "queued"} for item in second)
            assert any(item["status"] in {"already_pending", "duplicate"} for item in second)
            manager.close()


if __name__ == "__main__":
    unittest.main()
