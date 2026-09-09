"""Shared, never-raising environment-variable parsing.

Startup and hook entry points must degrade gracefully on a malformed configuration
value rather than crash (see #75) — a bad ``MEMORY_*`` integer must never turn into
an uncaught ``ValueError`` from ``argparse``'s default-evaluation. Every module that
reads an integer environment variable for a CLI default should use ``int_env`` here
instead of reimplementing the same clamp-and-fallback logic.
"""

from __future__ import annotations

import os


def int_env(name: str, default: int, minimum: int = 1) -> int:
    """Read an integer environment variable, clamped to ``minimum``.

    Falls back to ``default`` on any missing, non-numeric, or out-of-range value —
    never raises. Safe to call directly inside an ``argparse.add_argument(default=...)``
    expression, which is evaluated eagerly at parser-construction time, outside any
    surrounding ``try``/``except``.
    """
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default
