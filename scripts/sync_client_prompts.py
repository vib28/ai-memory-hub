"""Propagate generic.md instructions while preserving each client's writer identity."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "client-prompts"
CLIENTS = ("chatgpt", "claude", "codex", "gemini", "hermes", "kimi", "qwen", "generic")

body = (PROMPTS / "generic.md").read_text(encoding="utf-8")
for client in CLIENTS:
    identity = "<tool-name>" if client == "generic" else client
    content = re.sub(r"Writer identity for this client: `[^`]+`\.?", f"Writer identity for this client: `{identity}`.", body)
    (PROMPTS / f"{client}.md").write_text(content, encoding="utf-8")
