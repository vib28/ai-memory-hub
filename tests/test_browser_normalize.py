"""Tests for browser_tool normalization."""
from __future__ import annotations

import json
import pytest

from memory_hub.browser_normalize import (
    is_browser_tool_payload,
    normalize_browser_tool_payload,
    _normalize_browser_text,
)


class TestIsBrowserToolPayload:
    def test_string_payload(self):
        payload = '[{"text": "Successfully captured screenshot (1568x709, jpeg) - ID: ss_3327qm095", "type": "text"}]'
        assert is_browser_tool_payload(payload) is True

    def test_list_payload(self):
        payload = [{"text": "test", "type": "text"}]
        assert is_browser_tool_payload(payload) is True

    def test_non_payload(self):
        assert is_browser_tool_payload('{"key": "value"}') is False
        assert is_browser_tool_payload("plain text") is False

    def test_non_text_type(self):
        payload = '[{"text": "test", "type": "markdown"}]'
        assert is_browser_tool_payload(payload) is False


class TestNormalizeBrowserText:
    def test_screenshot(self):
        text = '[{"text": "Successfully captured screenshot (1568x709, jpeg) - ID: ss_3327qm095", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Screenshot captured (1568x709, jpeg)"

    def test_zoomed_screenshot(self):
        text = '[{"text": "Successfully captured zoomed screenshot of region (1280,20) to (1568,60) - 353x48 pixels", "type": "text"}]'
        result = normalize_browser_tool_payload(text)
        assert "Zoomed screenshot" in result

    def test_click(self):
        text = '[{"text": "Clicked at (1178, 39)", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Clicked at (1178, 39)"

    def test_click_element(self):
        text = '[{"text": "Clicked on element ref_23", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Clicked element ref_23"

    def test_type(self):
        text = '[{"text": "Typed \\"llama3.1:8b\\"", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Typed llama3.1:8b"

    def test_navigate(self):
        text = '[{"text": "Navigated to http://127.0.0.1:18765/", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Navigated to http://127.0.0.1:18765/"

    def test_scroll(self):
        text = '[{"text": "Scrolled down by 10 ticks at (700, 400)", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Scrolled down 10 ticks"

    def test_find_element(self):
        text = '[{"text": "Found 1 matching element\\n\\n- ref_23: switch \\"Dark mode\\" (checkbox)", "type": "text"}]'
        result = normalize_browser_tool_payload(text)
        assert "Found element" in result or "Dark mode" in result

    def test_console(self):
        text = '[{"text": "No console messages found for this tab.", "type": "text"}]'
        assert normalize_browser_tool_payload(text) == "Console checked (no messages)"

    def test_multiple_actions(self):
        payload = json.dumps([
            {"text": "Clicked at (100, 200)", "type": "text"},
            {"text": "Typed \"hello\"", "type": "text"},
            {"text": "Scrolled down by 5 ticks", "type": "text"},
        ])
        result = normalize_browser_tool_payload(payload)
        assert "Clicked" in result
        assert "Typed" in result
        assert "Scrolled" in result

    def test_strips_tab_context(self):
        text = '[{"text": "Clicked at (50, 320)\\n\\nTab Context:\\n- Executed on tabId: 1711153129", "type": "text"}]'
        result = normalize_browser_tool_payload(text)
        assert "Tab Context" not in result

    def test_truncates_long_text(self):
        text = "A" * 300
        result = normalize_browser_tool_payload(text)
        assert len(result) <= 203  # 200 + "..."

    def test_empty_payload(self):
        assert normalize_browser_tool_payload("[]") == ""
        assert normalize_browser_tool_payload("") == ""

    def test_non_json_fallback(self):
        assert normalize_browser_tool_payload("plain text that is not JSON") == "plain text that is not JSON"
