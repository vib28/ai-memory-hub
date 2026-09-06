"""Local consolidation of buffered observations into the session contract."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable, Iterable

from .capture import Observation


class ConsolidationError(RuntimeError):
    pass


SYSTEM_PROMPT = """You are a conservative coding-session summarizer.
Return JSON only with this exact shape:
{"title":"...","project":"... or null","investigated":[],"learned":[],"completed":[],"next_steps":[]}

Rules:
- Use short factual bullet strings.
- Preserve explicit decisions and unresolved work.
- Do not invent facts or claim work was completed without evidence.
- Do not include secrets, credentials, tokens, or raw command output.
- Ignore repetitive reads and temporary noise.
- Empty sections are allowed, but do not leave all sections empty when observations contain useful work.
"""


def _as_observation_dict(item: Observation | dict[str, Any]) -> dict[str, Any]:
    return item.to_dict() if isinstance(item, Observation) else dict(item)


def _prompt(observations: Iterable[Observation | dict[str, Any]]) -> str:
    rows = [_as_observation_dict(item) for item in observations]
    return json.dumps({"observations": rows}, ensure_ascii=False)


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:1000] for item in value if str(item).strip()][:30]


def _validate_payload(data: Any, *, fallback_project: str | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConsolidationError("model response must be a JSON object")
    payload = {
        "title": str(data.get("title", "Session summary")).strip()[:200] or "Session summary",
        "project": data.get("project") or fallback_project,
        "investigated": _clean_list(data.get("investigated")),
        "learned": _clean_list(data.get("learned")),
        "completed": _clean_list(data.get("completed")),
        "next_steps": _clean_list(data.get("next_steps")),
    }
    if not any(payload[key] for key in ("investigated", "learned", "completed", "next_steps")):
        raise ConsolidationError("model returned an empty session")
    if payload["project"] is not None:
        payload["project"] = str(payload["project"]).strip()[:200] or None
    return payload


def fallback_session(observations: Iterable[Observation | dict[str, Any]]) -> dict[str, Any]:
    """Produce a conservative summary without a local model."""
    rows = [_as_observation_dict(item) for item in observations]
    if not rows:
        raise ConsolidationError("cannot consolidate an empty observation set")
    project = next((str(row.get("project", "")).strip() for row in rows if row.get("project")), None)
    files: list[str] = []
    for row in rows:
        for path in row.get("files", []) or []:
            if path and path not in files:
                files.append(str(path))
    tools = sorted({str(row.get("tool", "unknown")) for row in rows})
    completed = [f"Captured {len(rows)} local observations from: {', '.join(tools[:8])}."]
    investigated = [f"Observed work involving {', '.join(files[:12])}." ] if files else []
    learned = []
    next_steps = []
    for row in rows:
        text = str(row.get("output_summary", "")).strip()
        if text and text not in learned:
            learned.append(text[:500])
        if len(learned) >= 8:
            break
    return _validate_payload({
        "title": "Captured session",
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
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        return _validate_payload(json.loads(content), fallback_project=rows[0].get("project"))
    except Exception as exc:
        raise ConsolidationError(f"local consolidation failed: {exc}") from exc
