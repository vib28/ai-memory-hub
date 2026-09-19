"""Shared test isolation.

The suite must behave identically on a clean CI runner and on a developer machine
where the product is actually installed.  An installed machine carries real
``MEMORY_*`` / ``AI_MEMORY_*`` values in the user environment (the Windows setup
scripts write them to ``HKCU\\Environment``), and code under test reads
``os.environ`` directly at the point of use.  Without isolation two families of
tests fail on such a machine, and every worker test leaves a health file in the
real ``~/.ai-memory-hub`` directory (#88).

Every test therefore runs with:

* every ``MEMORY_*`` and ``AI_MEMORY_*`` variable removed from ``os.environ``;
* ``HOME`` / ``USERPROFILE`` pointed at a per-test scratch directory, so any code
  path that still defaults to ``Path.home()`` writes under ``tmp_path`` instead of
  the developer's real home.

Tests that want a specific variable set it explicitly (``patch.dict`` or
``monkeypatch.setenv``) on top of this clean baseline.
"""

from __future__ import annotations

import os

import pytest

_PREFIXES = ("MEMORY_", "AI_MEMORY_")


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return
