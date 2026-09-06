"""Propagate generic.md instructions while preserving each client's writer identity."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "client-prompts"
CLIENTS = ("chatgpt", "claude", "codex", "gemini", "hermes", "kimi", "qwen", "generic")

def sync_prompts(prompts_dir: Path = PROMPTS) -> list[Path]:
    """Synchronize all client files and return the files written."""
    body = (prompts_dir / "generic.md").read_text(encoding="utf-8")
    written = []
    for client in CLIENTS:
        identity = "<tool-name>" if client == "generic" else client
        content = re.sub(
            r"Writer identity for this client: `[^`]+`\.?",
            f"Writer identity for this client: `{identity}`.",
            body,
        )
        destination = prompts_dir / f"{client}.md"
        destination.write_text(content, encoding="utf-8")
        written.append(destination)
    return written


if __name__ == "__main__":
    sync_prompts()
