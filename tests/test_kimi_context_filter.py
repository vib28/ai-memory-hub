"""Regression test: noisy Kimi-style prompts must not match unrelated memories."""

from __future__ import annotations

import unittest

from memory_hub.context_packet import _related_rows


class KimiNoisyPromptTests(unittest.TestCase):
    """Kimi sends its full reasoning trace as the prompt. Short generic verbs
    like "run", "install", "check", "start" must not cause unrelated memories
    to be injected."""

    def _memory(self, memory_id, text, subject="s", path="/projects/demo.md",
                kind="project", tag="stated"):
        return {"memory_id": memory_id, "subject": subject, "text": text,
                "path": path, "kind": kind, "tag": tag, "date": "2026-09-09T00:00:00"}



    def test_kimi_reasoning_trace_no_false_matches(self):
        memories = [
            self._memory("m1", "Completed GitHub issue #40 by chunking each non-empty session Markdown section into its own embedding vector while preserving flattened MemoryRecord text, FTS, duplicate detection, and parent-memory retrieval IDs"),
            self._memory("m2", "Session summary: Evaluated public-data intelligence, bounties, crypto infrastructure, prediction markets. Local machine has 32 GB RAM and 8 GB VRAM. Created business-growth-skillchain skill."),
            self._memory("m3", "Decision: chose SQLite over Postgres for local index. Setup Ollama with qwen3:14b.", path="/projects/ai-memory-hub.md"),
        ]
        kimi_prompt = ("The user wants to run ollama. Let me check if ollama is installed and start it. "
                       "\"run ollama\" — likely they want to start the ollama server. "
                       "Let me check if it's installed first. Ollama isn't in PATH but I notice "
                       "it IS in the PATH list. Maybe the binary is ollama.exe in that directory. "
                       "Let me check the install directory directly.")
        related = _related_rows(memories, kimi_prompt, project="ai-memory-hub")
        # No memory about embeddings or business skillchains should match
        ids = {row["memory_id"] for row in related}
        assert "m1" not in ids, "embedding work memory matched on generic verbs"
        assert "m2" not in ids, "business direction memory matched on generic verbs"

    def test_legitimate_overlap_still_matches(self):
        memories = [
            self._memory("m1", "Decision: keep the date filter inclusive on both ends. Why: user expectation.", path="/projects/widget-app.md"),
            self._memory("m2", "Finding: git-bash mangles backslashes in PowerShell args. Fix: use forward slashes.", path="/projects/widget-app.md"),
        ]
        # A genuinely relevant prompt should still match
        prompt = "why does git-bash break my PowerShell backslashes and how do I fix the filter decision?"
        related = _related_rows(memories, prompt, project="widget-app")
        ids = {row["memory_id"] for row in related}
        assert "m2" in ids, "legitimate bash-backslash memory should match"
        assert "m1" in ids, "legitimate filter memory should match on 'filter'"

    def test_empty_prompt_returns_nothing(self):
        memories = [self._memory("m1", "some text")]
        assert _related_rows(memories, "", project=None) == []

    def test_only_stopwords_returns_nothing(self):
        memories = [self._memory("m1", "some text about installations and running")]
        assert _related_rows(memories, "run install check start", project=None) == []


if __name__ == "__main__":
    unittest.main()
