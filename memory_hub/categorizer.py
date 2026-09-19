"""Deterministic, model-free memory categorizer (#85).

Runs after each checkpoint on the batch's observations. Rules are conservative
(high precision, low recall). Candidates go through ``MemoryManager.queue`` /
``propose`` under the configured write mode and inherit exact-hash + lexical
dedup, so re-running on the same evidence is a no-op. MEMORY_LLM_* is never
consulted; if set, it would only be an optional enrichment stage on top.
"""

from __future__ import annotations

import re
from typing import Any

from .models import MemoryCandidate
from .security import check_text
from .utils import slugify

_PREFERENCE_RE = re.compile(
    r"\b(?:always|never|from now on|prefer(?:ably)?|don't|do not)\b.{0,160}",
    re.I,
)
_DECISION_RE = re.compile(
    r"\b(?:decided|decision|we'll go with|we will go with|chose|choosing)\b.{0,200}",
    re.I,
)
_GIT_RE = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(?P<verb>commit|push|checkout\s+-b|switch\s+-c|merge|rebase|tag)\b",
    re.I,
)
_TEST_RE = re.compile(
    r"\b(?P<passed>\d+)\s+passed\b.*?\b(?P<failed>\d+)\s+failed\b"
    r"|\b(?P<failed_only>\d+)\s+failed\b.*?\b(?P<passed_only>\d+)\s+passed\b"
    r"|\b(?P<tests>\d+)\s+(?:tests?|specs?)\s+(?:passed|failed)\b",
    re.I,
)
_ERROR_KEY_RE = re.compile(r"\b(?:error|exception|errno|exit(?:ed)?\s+(?:code\s+)?[1-9]\d*)\b", re.I)


def _text(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("prompt") or ""),
        str(row.get("input_summary") or ""),
        str(row.get("assistant") or ""),
        str(row.get("output_summary") or ""),
    ]
    return " ".join(part for part in parts if part)


def _ids(*rows: dict[str, Any]) -> list[str]:
    return [str(row.get("observation_id") or row.get("id") or "") for row in rows if row]


def _noun_slug(span: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", span.lower()).strip("-")
    tokens = [token for token in cleaned.split("-") if token and token not in {
        "always", "never", "from", "now", "on", "prefer", "preferably", "dont", "do", "not",
        "the", "a", "an", "to", "and", "or", "please", "just",
    }]
    return slugify("-".join(tokens[:6]) or fallback)


def extract_memory_candidates(observations: list[dict[str, Any]], *, project: str | None = None,
                              writer: str = "other") -> list[MemoryCandidate]:
    """Return typed candidates with ``evidence_ids`` on each (``provenance``)."""
    rows = [dict(row) for row in observations if isinstance(row, dict)]
    project = (project or "").strip() or None
    out: list[MemoryCandidate] = []

    for row in rows:
        blob = _text(row)
        event = str(row.get("event") or "")
        if event in {"user-prompt-submit", "before-agent"} or row.get("tool") == "prompt":
            match = _PREFERENCE_RE.search(blob)
            if match:
                span = match.group(0).strip()
                text = f"**Rule:** {span[:240]} **Reason:** stated in session prompt. **Applies to:** global"
                if project:
                    text += f" or [[{project}]]"
                out.append(_candidate(text, "preference", "preference",
                                      _noun_slug(span, "session-preference"), writer, _ids(row)))
        if event in {"stop", "after-agent", "user-prompt-submit", "before-agent"} or row.get("tool") in {"prompt", "assistant"}:
            match = _DECISION_RE.search(blob)
            if match and project:
                span = match.group(0).strip()
                text = (f"**Decision:** {span[:240]} **Context:** captured from {event or 'session'} "
                        f"in [[{project}]]. **Alternatives considered:** not stated. **Consequences:** not stated.")
                out.append(_candidate(text, "decision", "decided",
                                      _noun_slug(span, project), writer, _ids(row)))

        command = str(row.get("input_summary") or "")
        git = _GIT_RE.search(command)
        output = str(row.get("output_summary") or "")
        failed = event in {"post-tool-use-failure"} or bool(_ERROR_KEY_RE.search(output) and "exit" in output.lower())
        if git and project and not failed and event in {"post-tool-use", "after-tool", ""}:
            verb = re.sub(r"\s+", " ", git.group("verb")).strip()
            text = (f"**Fact:** ran `git {verb}` successfully in [[{project}]]. "
                    f"**Context:** captured from host tool {row.get('tool') or 'bash'}.")
            out.append(_candidate(text, "project", "stated", project, writer, _ids(row)))

        test = _TEST_RE.search(output) or _TEST_RE.search(command)
        if test and project and event in {"post-tool-use", "after-tool", "post-tool-use-failure", ""}:
            text = (f"**Fact:** test/build runner reported `{test.group(0)[:160]}` in [[{project}]]. "
                    f"**Context:** captured from host tool {row.get('tool') or 'unknown'}.")
            out.append(_candidate(text, "project", "stated", project, writer, _ids(row)))

    # Repeated failing command followed by a passing variant of the same tool.
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tool = str(row.get("tool") or "")
        if tool and tool not in {"prompt", "assistant", "unknown"}:
            by_tool.setdefault(tool, []).append(row)
    for tool, group in by_tool.items():
        events = [str(row.get("event") or "") for row in group]
        if "post-tool-use-failure" in events and "post-tool-use" in events:
            fail_row = next(row for row in group if row.get("event") == "post-tool-use-failure")
            pass_row = next(row for row in reversed(group) if row.get("event") == "post-tool-use")
            err = _ERROR_KEY_RE.search(_text(fail_row))
            key = slugify(f"{tool}-{err.group(0) if err else 'failure'}")
            text = (f"**Finding:** `{tool}` failed then succeeded in the same session. "
                    f"**Cause:** {(_text(fail_row) or 'command failure')[:200]}. "
                    f"**Fix:** {(_text(pass_row) or 'retry/variant')[:200]}.")
            out.append(_candidate(text, "topic", "stated", key, writer, _ids(fail_row, pass_row)))

    # Drop secrets and empty leftovers; preserve first evidence set per (kind, subject, text).
    unique: list[MemoryCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in out:
        security = check_text(candidate.text)
        if not security.safe:
            continue
        key = (candidate.kind, candidate.subject, candidate.text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _candidate(text: str, kind: str, tag: str, subject: str, writer: str,
               evidence_ids: list[str]) -> MemoryCandidate:
    return MemoryCandidate(text=text[:1500], kind=kind, tag=tag,
                           subject=slugify(subject) or "general", writer=writer or "other",
                           evidence_ids=[item for item in evidence_ids if item])


def apply_candidates(manager: Any, candidates: list[MemoryCandidate], *, write_mode: str) -> list[dict[str, Any]]:
    """Queue or store each candidate. Re-processing identical evidence is a no-op."""
    results = []
    for candidate in candidates:
        evidence_ids = list(getattr(candidate, "evidence_ids", []) or [])
        payload = {"type": "categorizer", "evidence_ids": evidence_ids}
        if write_mode == "review":
            result = manager.queue(candidate, payload=payload)
        else:
            result = manager.propose(candidate)
            if result.get("status") in {"possible_update"}:
                result = manager.queue(candidate, payload=payload)
        result = dict(result)
        result["evidence_ids"] = evidence_ids
        results.append(result)
    return results


def apply_from_observations(manager: Any, observations: list[dict[str, Any]], *,
                            write_mode: str, writer: str = "other",
                            project: str | None = None) -> list[dict[str, Any]]:
    project = project or next((str(row.get("project") or "") for row in observations if row.get("project")), None)
    return apply_candidates(
        manager,
        extract_memory_candidates(observations, project=project, writer=writer),
        write_mode=write_mode,
    )
