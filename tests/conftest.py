#!/usr/bin/env python3
"""Shared pytest fixtures.

The native memory bridge writes into Claude Code's config tree
(``~/.claude/projects/<slug>/memory``). Any test that exercises a code path
which promotes learnings would otherwise edit the *developer's own* memory
directory — including the ``MEMORY.md`` that loads into every one of their
sessions. Redirecting ``CLAUDE_CONFIG_DIR`` for the whole suite makes that
impossible, whether or not an individual test remembered to isolate itself.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalogue


@pytest.fixture(autouse=True)
def isolate_claude_config_dir(tmp_path_factory, monkeypatch):
    """Point ``CLAUDE_CONFIG_DIR`` at a throwaway tree for every test."""
    config_dir = tmp_path_factory.mktemp("claude-config")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    return config_dir


def pytest_configure(config):
    """Register the surface markers named in ``tests/CATALOGUE.md``."""
    for surface in catalogue.declared_surfaces():
        config.addinivalue_line(
            "markers",
            f"{surface}: tests for the '{surface}' surface (see tests/CATALOGUE.md)",
        )


def pytest_collection_modifyitems(items):
    """Apply each module's surface marker, driven by the catalogue.

    Tagging in the document rather than in 37 modules means the map and the
    selector can never disagree — ``pytest -m memory`` runs exactly what the
    catalogue says is in that surface.
    """
    owners = catalogue.surface_of()
    for item in items:
        for surface in owners.get(Path(str(item.fspath)).name, []):
            item.add_marker(getattr(pytest.mark, surface))
