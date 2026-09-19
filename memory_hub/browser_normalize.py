"""Browser tool payload normalization.

Hermes browser tool emits results as a JSON array of ``{"text": ..., "type": "text"}``
objects.  Storing the raw array verbatim pollutes the vault with unsummarizable
garbage.  This module detects that shape, extracts the actual browser action, and
produces a single human-readable line that the downstream pipeline (worker,
consolidator, categorizer, handoff) can actually use.

Examples
--------
>>> _normalize_browser_payload('[{"text": "Successfully captured screenshot (1568x709, jpeg) - ID: ss_3327qm095", "type": "text"}]')
'Screenshot captured (1568x709, jpeg)'

>>> _normalize_browser_payload('[{"text": "Clicked at (1178, 39)", "type": "text"}]')
'Clicked at (1178, 39)'

>>> _normalize_browser_payload('[{"text": "Typed \\"llama3.1:8b\\"", "type": "text"}]')
'Typed llama3.1:8b'
"""
from __future__ import annotations

import json
import re
from typing import Any

# --------------------------------------------------------------------------- patterns

_SCREENSHOT_RE = re.compile(r"Successfully captured screenshot \((?P<w>\d+)x(?P<h>\d+),\s*(?P<fmt>\w+)\)", re.I)
_ZOOMED_SCREENSHOT_RE = re.compile(r"Successfully captured zoomed screenshot of region \((?P<x1>\d+),(?P<y1>\d+)\) to \((?P<x2>\d+),(?P<y2>\d+)\)", re.I)
_CLICK_AT_RE = re.compile(r"Clicked at \((?P<x>\d+),\s*(?P<y>\d+)\)", re.I)
_CLICK_ELEMENT_RE = re.compile(r"Clicked on element (?P<ref>\w+)", re.I)
_TYPED_RE = re.compile(r"Typed [\"'](?P<text>.+?)[\"']", re.I)
_NAVIGATED_RE = re.compile(r"Navigated to (?P<url>\S+)", re.I)
_SCROLL_RE = re.compile(r"Scrolled (?P<dir>up|down|left|right) by (?P<ticks>\d+) ticks", re.I)
_FOUND_ELEMENT_RE = re.compile(r"Found (?P<count>\d+) matching element", re.I)
_CONSOLE_NO_MESSAGES_RE = re.compile(r"No console messages found", re.I)
_ELEMENT_DESC_RE = re.compile(r"(?P<ref>ref_\w+):\s*(?P<tag>\w+)\s*[\"'](?P<name>[^\"']+?)[\"']\s*\((?P<type>\w+)\)")


# --------------------------------------------------------------------------- public API

def is_browser_tool_payload(value: Any) -> bool:
    """Return True when value is a browser-tool payload array."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[{") and '"type": "text"' in stripped:
            return True
    if isinstance(value, list):
        if value and isinstance(value[0], dict) and value[0].get("type") == "text":
            return True
    return False


def normalize_browser_tool_payload(value: Any) -> str:
    """Parse a browser-tool payload and return a human-readable summary."""
    items: list[dict[str, Any]] = []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                items = parsed
        except (json.JSONDecodeError, ValueError):
            return value[:200] if len(value) > 200 else value
    elif isinstance(value, list):
        items = value

    if not items:
        return ""

    summaries: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        summary = _normalize_browser_text(text)
        if summary:
            summaries.append(summary)

    if not summaries:
        return ""

    result = "; ".join(summaries)
    if len(result) > 500:
        result = result[:497] + "..."
    return result


# --------------------------------------------------------------------------- internals

def _normalize_browser_text(text: str) -> str | None:
    """Normalize a single browser action text into a human-readable summary."""
    if not text or not text.strip():
        return None

    text = text.strip()

    # Try each pattern in order
    if m := _SCREENSHOT_RE.search(text):
        return f"Screenshot captured ({m.group('w')}x{m.group('h')}, {m.group('fmt')})"
    if m := _ZOOMED_SCREENSHOT_RE.search(text):
        return f"Zoomed screenshot captured (region {m.group('x1')},{m.group('y1')} to {m.group('x2')},{m.group('y2')})"
    if m := _CLICK_AT_RE.search(text):
        return f"Clicked at ({m.group('x')}, {m.group('y')})"
    if m := _CLICK_ELEMENT_RE.search(text):
        return f"Clicked element {m.group('ref')}"
    if m := _TYPED_RE.search(text):
        return f"Typed {m.group('text')}"
    if m := _NAVIGATED_RE.search(text):
        return f"Navigated to {m.group('url')}"
    if m := _SCROLL_RE.search(text):
        return f"Scrolled {m.group('dir')} {m.group('ticks')} ticks"
    if m := _FOUND_ELEMENT_RE.search(text):
        # Look for element description in the text
        desc_m = _ELEMENT_DESC_RE.search(text)
        if desc_m:
            return f"Found element: {desc_m.group('name')} ({desc_m.group('tag')}, {desc_m.group('type')})"
        return f"Found {m.group('count')} matching element(s)"
    if m := _CONSOLE_NO_MESSAGES_RE.search(text):
        return "Console checked (no messages)"

    # Fallback: strip trailing tab context / technical noise
    for delimiter in ("\n\nTab Context:", "\n\nNote:", "\n\nExecuted on tabId:"):
        if delimiter in text:
            text = text[: text.index(delimiter)]

    text = text.strip()
    if len(text) > 200:
        text = text[:197] + "..."
    return text if text else None
