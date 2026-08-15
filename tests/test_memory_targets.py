#!/usr/bin/env python3
"""Tests for lib/memory_targets.py — the Codex owned-region adapter."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import memory_targets as mt
from lib.native_memory import learning_to_doc


def _learning(title="Use the org npm registry",
              description="npm install 401s against the public registry",
              fix="Point npm at the org registry before installing"):
    return {"title": title, "description": description, "fix": fix,
            "category": "npm", "source": "failure_resolution"}


# ---------------------------------------------------------------------------
# Region rendering
# ---------------------------------------------------------------------------

def test_region_is_fenced_and_carries_the_fix():
    region, truncated = mt.render_region([learning_to_doc(_learning())])
    assert region.startswith(mt.REGION_START)
    assert region.rstrip().endswith(mt.REGION_END)
    assert "Point npm at the org registry" in region
    assert truncated == 0


def test_region_is_empty_when_there_is_nothing_to_say():
    region, truncated = mt.render_region([])
    assert region == ""
    assert truncated == 0


def test_budget_drops_whole_entries_and_reports_them():
    """A half-written rule is worse than an absent one."""
    docs = [learning_to_doc(_learning(title=f"Rule number {i}")) for i in range(50)]
    region, truncated = mt.render_region(docs, budget=600)

    assert truncated > 0
    assert len(region) <= 600
    assert region.count("- **") == len(docs) - truncated


# ---------------------------------------------------------------------------
# Ownership: everything outside the fence is untouchable
# ---------------------------------------------------------------------------

class TestOwnedRegion:
    def test_user_content_is_preserved_byte_for_byte(self):
        existing = "# My project\n\nHand written rules.\n\n- never force push\n"
        region, _ = mt.render_region([learning_to_doc(_learning())])

        updated = mt.apply_region(existing, region)

        assert existing.rstrip("\n") in updated
        assert mt.REGION_START in updated

    def test_second_write_replaces_only_the_block(self):
        existing = "# Mine\n\nkeep me\n"
        first, _ = mt.render_region([learning_to_doc(_learning(title="First"))])
        once = mt.apply_region(existing, first)

        second, _ = mt.render_region([learning_to_doc(_learning(title="Second"))])
        twice = mt.apply_region(once, second)

        assert "keep me" in twice
        assert "Second" in twice
        assert "First" not in twice
        assert twice.count(mt.REGION_START) == 1

    def test_applying_the_same_region_is_idempotent(self):
        existing = "# Mine\n\nkeep me\n"
        region, _ = mt.render_region([learning_to_doc(_learning())])
        once = mt.apply_region(existing, region)
        twice = mt.apply_region(once, region)
        assert once == twice

    def test_empty_region_removes_the_block_and_keeps_the_rest(self):
        existing = "# Mine\n\nkeep me\n"
        region, _ = mt.render_region([learning_to_doc(_learning())])
        with_block = mt.apply_region(existing, region)

        cleared = mt.apply_region(with_block, "")

        assert "keep me" in cleared
        assert mt.REGION_START not in cleared

    def test_content_after_the_block_survives(self):
        """The user may move the fence; text below it must not be eaten."""
        region, _ = mt.render_region([learning_to_doc(_learning())])
        existing = mt.apply_region("# Top\n", region) + "\n## Below\n\nmy notes\n"

        updated = mt.apply_region(existing, region)

        assert "## Below" in updated
        assert "my notes" in updated
        assert updated.count(mt.REGION_START) == 1


# ---------------------------------------------------------------------------
# sync_region
# ---------------------------------------------------------------------------

class TestSyncRegion:
    def test_refuses_to_create_agents_md(self, tmp_path):
        result = mt.sync_region([_learning()], {}, project_root=str(tmp_path))

        assert not (tmp_path / "AGENTS.md").exists()
        assert not result.written
        assert any(s["reason"] == "absent" for s in result.skipped)

    def test_writes_into_an_existing_agents_md(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Project rules\n\n- use tabs\n")

        result = mt.sync_region([_learning()], {}, project_root=str(tmp_path))

        text = agents.read_text()
        assert result.written
        assert "- use tabs" in text
        assert "Point npm at the org registry" in text

    def test_sync_is_idempotent(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Project rules\n")

        mt.sync_region([_learning()], {}, project_root=str(tmp_path))
        first = agents.read_text()
        second_result = mt.sync_region([_learning()], {}, project_root=str(tmp_path))

        assert agents.read_text() == first
        assert not second_result.changed

    def test_clear_removes_only_recalls_block(self, tmp_path):
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Project rules\n\n- use tabs\n")
        mt.sync_region([_learning()], {}, project_root=str(tmp_path))

        mt.clear_region(project_root=str(tmp_path))

        text = agents.read_text()
        assert "- use tabs" in text
        assert mt.REGION_START not in text

    def test_non_durable_learnings_never_reach_agents_md(self, tmp_path):
        """The Codex target shares the promotion gate with the Claude target."""
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# Project rules\n")
        junk = {"title": "Fix for cd failure",
                "description": "Command `cd /a` failed with: nope",
                "solution": "Use instead: `cd /b`", "source": "failure_resolution"}

        mt.sync_region([junk], {}, project_root=str(tmp_path))

        assert mt.REGION_START not in agents.read_text()
