from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

SYSTEM_PROMPT = """You are a conservative persistent-memory extractor.

Return JSON only with this exact top-level shape:
{"memories":[{"text":"...","kind":"...","tag":"...","subject":"..."}]}

Allowed kind: profile, preference, person, project, topic, decision
Allowed tag: stated, decided, preference, constraint, open

Extract only high-confidence durable facts that are likely to improve future conversations weeks or months later.

Include:
- stable identity/role/technology stack/timezone
- durable preferences
- important purchases relevant to future recommendations
- long-running project objective/constraints/current durable state
- explicit decisions
- recurring interests/preferences
- unresolved questions that materially affect an ongoing project

Exclude:
- passwords, secrets, keys, tokens, account/ID numbers
- health, political, religious, sexuality or similarly sensitive personal attributes
- current prices/search results/news
- generated code or assistant suggestions
- temporary bugs/errors/tasks
- one-off reactions and temporary moods
- uncertain guesses/inferences
- facts spoken by the assistant unless the user explicitly adopted them

Use one atomic fact per item. Do not invent facts. If nothing qualifies, return {"memories":[]}.
"""

class ExtractionError(RuntimeError):
    pass

def _extract_json_text(payload: dict[str, Any]) -> str:
    try:
        return payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ExtractionError(f"unexpected chat-completions response: {payload}") from exc

def extract_candidates(transcript: str) -> list[dict]:
    base_url = os.environ.get("MEMORY_LLM_BASE_URL", "").rstrip("/")
    model = os.environ.get("MEMORY_LLM_MODEL", "").strip()
    api_key = os.environ.get("MEMORY_LLM_API_KEY", "")

    if not base_url or not model:
        raise ExtractionError(
            "Set MEMORY_LLM_BASE_URL and MEMORY_LLM_MODEL to use transcript ingestion."
        )

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ExtractionError(f"extractor request failed: {exc}") from exc

    raw = _extract_json_text(payload).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"model did not return valid JSON: {raw[:500]}") from exc

    memories = data.get("memories", [])
    if not isinstance(memories, list):
        raise ExtractionError("'memories' must be a list")
    return [m for m in memories if isinstance(m, dict)]
