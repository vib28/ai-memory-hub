"""Local consolidation of buffered observations into the session contract."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any, Callable, Iterable

from .capture import Observation
from .utils import clean_list, one_line


class ConsolidationError(RuntimeError):
    pass


SYSTEM_PROMPT = """You are a conservative coding-session summarizer.
Return JSON only with this exact shape:
{"title":"...","project":"... or null","investigated":[],"learned":[],"completed":[],"next_steps":[]}

Rules:
- Use short factual bullet strings (one sentence each).
- Preserve explicit decisions and unresolved work.
- Do not invent facts or claim work was completed without evidence.
- Do not include secrets, credentials, tokens, or raw command output.
- Do not include raw file content, diffs, code snippets, or full tool outputs in any section.
- Summarize what was learned in your own words (e.g., "Fixed settings rendering bug" not the actual code).
- Ignore repetitive reads and temporary noise.
- Empty sections are allowed, but do not leave all sections empty when observations contain useful work.
"""


def _as_observation_dict(item: Observation | dict[str, Any]) -> dict[str, Any]:
    return item.to_dict() if isinstance(item, Observation) else dict(item)


def _prompt(observations: Iterable[Observation | dict[str, Any]]) -> str:
    rows = [_as_observation_dict(item) for item in observations]
    return json.dumps({"observations": rows}, ensure_ascii=False)


def _validate_payload(data: Any, *, fallback_project: str | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConsolidationError("model response must be a JSON object")
    payload = {
        "title": str(data.get("title", "Session summary")).strip()[:200] or "Session summary",
        "project": data.get("project") or fallback_project,
        "investigated": clean_list(data.get("investigated")),
        "learned": clean_list(data.get("learned")),
        "completed": clean_list(data.get("completed")),
        "next_steps": clean_list(data.get("next_steps")),
    }
    if not any(payload[key] for key in ("investigated", "learned", "completed", "next_steps")):
        raise ConsolidationError("model returned an empty session")
    if payload["project"] is not None:
        payload["project"] = str(payload["project"]).strip()[:200] or None
    return payload


_GIT_VERB_RE = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(?P<verb>commit|push|checkout\s+-b|switch\s+-c|merge|rebase|tag|revert|cherry-pick)\b",
    re.I,
)
_TEST_RE = re.compile(
    r"\b(?P<passed>\d+)\s+passed\b(?:.*?\b(?P<failed>\d+)\s+failed\b)?|\bTests?:\s*(?P<jest_pass>\d+)\s+passed",
    re.I | re.S,
)
_FAILURE_RE = re.compile(r"\b(\d+)\s+failed\b|\berror\b|\bTraceback\b|\bFAILED\b", re.I)





def _command_of(row: dict[str, Any]) -> str:
    raw = str(row.get("input_summary", "") or "")
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(data, dict):
            return str(data.get("command") or data.get("cmd") or data.get("description") or "")
    return raw


def fallback_session(observations: Iterable[Observation | dict[str, Any]]) -> dict[str, Any]:
    """Produce a conservative four-section summary without a local model.

    Since #82 the rows carry the user's prompts, the assistant's completed turns,
    the host's termination reason and real file/command evidence, so the fallback
    can state what was *asked*, what was *reported done*, which git/test evidence
    exists and what the host said about how the session ended -- instead of the
    old "Captured N local observations from: Bash" placeholder.  It still never
    infers completion the evidence does not show.
    """
    rows = [_as_observation_dict(item) for item in observations]
    if not rows:
        raise ConsolidationError("cannot consolidate an empty observation set")
    project = next((str(row.get("project", "")).strip() for row in rows if row.get("project")), None)
    files: list[str] = []
    for row in rows:
        for path in row.get("files", []) or []:
            if path and path not in files:
                files.append(str(path))
    tools = sorted({str(row.get("tool", "unknown")) for row in rows
                    if str(row.get("tool", "")) not in {"prompt", "assistant", "session", "unknown"}})

    prompts = [one_line(row.get("input_summary"), 300) for row in rows
               if row.get("event") == "user-prompt-submit" and one_line(row.get("input_summary"), 300)]

    def _is_raw_content(text: str) -> bool:
        """Check if text is raw file content, JSON blobs, or tool output rather than a summary."""
        if not text:
            return True
        return (text.startswith("{") or text.startswith('{"filePath"') or
                '"newString"' in text or '"oldString"' in text or
                text.startswith('"') or text.startswith("SYNTAX") or
                "SYNTAX OK" in text or len(text) > 500)

    answers = [one_line(row.get("output_summary"), 400) for row in rows
               if row.get("event") in {"stop", "subagent-stop"}
               and not _is_raw_content(one_line(row.get("output_summary"), 400))]
    git_actions: list[str] = []
    test_results: list[str] = []
    failures: list[str] = []
    for row in rows:
        if row.get("event") not in {"post-tool-use", "post-tool-use-failure"}:
            continue
        command = _command_of(row)
        output = str(row.get("output_summary", "") or "")
        match = _GIT_VERB_RE.search(command)
        if match and row.get("event") == "post-tool-use":
            verb = one_line(match.group("verb")).lower()
            git_actions.append(f"git {verb}: {one_line(command, 160)}")
        test_match = _TEST_RE.search(output)
        if test_match:
            passed = test_match.group("passed") or test_match.group("jest_pass")
            failed = test_match.group("failed")
            test_results.append(
                f"Test run: {passed} passed" + (f", {failed} failed" if failed else "")
                + f" ({one_line(command, 80)})"
            )
        if row.get("event") == "post-tool-use-failure":
            failures.append(f"{row.get('tool', 'tool')} failed: {one_line(command or output, 160)}")
    endings = [one_line(row.get("input_summary"), 120) for row in rows
               if row.get("event") in {"session-end", "stop-failure", "interrupt"}
               and one_line(row.get("input_summary"), 120)]

    def dedupe(items: list[str], limit: int) -> list[str]:
        seen: list[str] = []
        for item in items:
            if item and item not in seen:
                seen.append(item)
            if len(seen) >= limit:
                break
        return seen

    investigated: list[str] = []
    if prompts:
        investigated.extend(f"User asked: {text}" for text in dedupe(prompts, 6))
    if files:
        investigated.append(f"Files touched: {', '.join(files[:12])}" + (" ..." if len(files) > 12 else ""))
    learned: list[str] = []
    learned.extend(dedupe(failures, 4))
    learned.extend(dedupe(test_results, 4))
    if not learned and not answers:
        # Legacy rows (pre-#82) only have tool echoes; surface short human-readable
        # summaries only — never raw file content, JSON blobs, or tool output.
        for row in rows:
            text = one_line(row.get("output_summary"), 300)
            if _is_raw_content(text):
                continue
            if text not in learned:
                learned.append(text)
            if len(learned) >= 4:
                break
    completed: list[str] = []
    completed.extend(f"Assistant reported: {text}" for text in dedupe(answers, 4))
    completed.extend(dedupe(git_actions, 6))
    if not completed:
        completed.append(
            f"Captured {len(rows)} local observations"
            + (f" from: {', '.join(tools[:8])}" if tools else "") + "."
        )
    next_steps: list[str] = []
    if endings:
        next_steps.extend(f"Host session ended: {text}" for text in dedupe(endings, 2))
    if failures and not test_results:
        next_steps.append("Unresolved tool failures recorded above; re-check before continuing.")
    title = "Captured session"
    if prompts:
        title = one_line(prompts[0], 80)
    return _validate_payload({
        "title": title,
        "project": project,
        "investigated": investigated,
        "learned": learned,
        "completed": completed,
        "next_steps": next_steps,
    }, fallback_project=project)


def consolidate_session(
    observations: Iterable[Observation | dict[str, Any]],
    *,
    base_url: str | None = None,
    model: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Summarize observations with a local OpenAI-compatible server."""
    rows = list(observations)
    if not rows:
        raise ConsolidationError("cannot consolidate an empty observation set")
    endpoint = (base_url or os.environ.get("MEMORY_LLM_BASE_URL", "")).rstrip("/")
    model_name = (model or os.environ.get("MEMORY_LLM_MODEL", "")).strip()
    if not endpoint or not model_name:
        return fallback_session(rows)
    body = json.dumps({
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _prompt(rows)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint + "/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener(request, timeout=120) as response:
            payload = json.loads(response.read(16 * 1024 * 1024).decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        return _validate_payload(json.loads(content), fallback_project=rows[0].get("project"))
    except (json.JSONDecodeError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConsolidationError(f"local consolidation failed: {exc}") from exc
