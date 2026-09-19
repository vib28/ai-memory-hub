# Fix: Browser Tool Payload Normalization + Context Capture Quality

## Problem

1. **Browser tool payloads leak into vault** — Hermes browser tool emits raw JSON arrays:
   `[{"text": "Successfully captured screenshot...", "type": "text"}]`
   These get stored verbatim in session files, polluting the vault with unsummarizable garbage.

2. **No structured context** — The capture pipeline stores flat strings, not structured summaries. The consolidator can't produce good memories from raw JSON.

3. **Context injection is noisy** — The Kimi issue from earlier: three unrelated old contexts were inserted because the scoring was done on raw text that matched generic verbs.

## Solution

### 1. Browser Tool Normalizer (`browser_normalize.py`)
- Detect the `[{"text": ..., "type": "text"}]` shape via `is_browser_tool_payload()`
- Parse each item, extract the browser action (screenshot, click, type, navigate, scroll, element-find, console)
- Produce a single human-readable summary line:
  - `"Screenshot captured (1568x709, jpeg)"`
  - `"Clicked element ref_23"`
  - `"Typed llama3.1:8b"`
  - `"Navigated to http://127.0.0.1:18765/"`
  - `"Scrolled down 10 ticks"`
  - `"Found element: Dark mode (switch, checkbox)"`
- Strip trailing technical noise (`Tab Context:`, `Executed on tabId:`, etc.)
- Multiple actions joined with `; `

### 2. Integration into Capture Pipeline
- `_sanitize_text()` now calls `normalize_browser_tool_payload()` first when the value matches the browser payload shape
- This means browser-tool evidence reaches the vault as clean summaries, not raw JSON

### 3. Context Capture Quality (already implemented in earlier cycles)
- `_related_rows()` now filters on content tokens (>= `_MIN_CONTENT_TOKEN_LEN = 6`)
- Score normalized by query length to prevent long memories from dominating
- Minimum overlap threshold of 2 tokens and score >= 0.3
- Foreign projects never leak on word overlap alone

## Files Modified
- `memory_hub/browser_normalize.py` — New module
- `memory_hub/capture.py` — Integrated normalizer into `_sanitize_text()`
- `tests/test_browser_normalize.py` — 18 tests covering all action types
