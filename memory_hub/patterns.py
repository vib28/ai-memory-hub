from __future__ import annotations

import re
from pathlib import Path

REQUIRED_FIELDS = ("trigger", "project fact", "preference rule")


def load_patterns(path: Path) -> dict[str, dict[str, str]]:
    """Load and validate the user-editable pattern configuration."""
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    found: dict[str, dict[str, str]] = {}
    matches = list(re.finditer(
        r"^## (?P<id>[a-zA-Z0-9_-]+)\s*$\n(?P<body>.*?)(?=^## |\Z)",
        content, re.M | re.S,
    ))
    for match in matches:
        pattern_id = match.group("id")
        fields: dict[str, str] = {}
        for line in match.group("body").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip().lower()] = value.strip()
        missing = [field for field in REQUIRED_FIELDS if not fields.get(field)]
        if missing:
            raise ValueError(
                f"pattern '{pattern_id}' is missing required field(s): {', '.join(missing)}"
            )
        found[pattern_id] = fields
    return found
