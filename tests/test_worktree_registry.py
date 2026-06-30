#!/usr/bin/env python3
"""Tests for worktree registry I/O helpers in lib/shared.py."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import pytest

# Ensure lib/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.shared import (
    _load_worktree_registry,
    _save_worktree_registry,
    lookup_worktree_project,
    list_project_worktrees,
    prune_stale_worktrees,
    _normalize_path,
    _resolve_cwd,
    WORKTREE_REGISTRY_PATH,
)


# ---------------------------------------------------------------------------
# Helper to build a registry dict for tests
# ---------------------------------------------------------------------------

def _make_registry(projects: dict = None) -> dict:
    return {"projects": projects or {}}


def _make_project(project_folder: str, worktrees: dict) -> dict:
    return {"project_folder": project_folder, "worktrees": worktrees}


def _make_worktree(branch: str, last_seen: datetime, created: datetime = None) -> dict:
    if created is None:
        created = last_seen
    return {
        "branch": branch,
        "created": created.isoformat(),
        "last_seen": last_seen.isoformat(),
    }


# ---------------------------------------------------------------------------
# _load / _save basics (complements Task 1 tests)
# ---------------------------------------------------------------------------

class TestRegistryIO:
    """Basic load/save for the registry file."""

    def test_load_empty_registry(self, tmp_path):
        """Nonexistent file returns {"projects": {}}."""
        fake_path = tmp_path / "does-not-exist.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", fake_path):
            reg = _load_worktree_registry()
        assert reg == {"projects": {}}

    def test_save_and_load_roundtrip(self, tmp_path):
        """Data survives a save/load cycle."""
        reg_path = tmp_path / "registry.json"
        data = _make_registry({
            "/Users/ash/repo": _make_project(
                "-Users-ash-repo",
                {"/tmp/wt1": {"branch": "feat-x", "created": "2026-03-13T10:00:00+00:00", "last_seen": "2026-03-13T10:00:00+00:00"}},
            )
        })
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(data)
            loaded = _load_worktree_registry()
        assert loaded == data

    def test_corrupt_json_returns_empty_registry(self, tmp_path):
        """Corrupt JSON file returns {'projects': {}}."""
        reg_path = tmp_path / "registry.json"
        reg_path.write_text("{not valid json {{{")
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            reg = _load_worktree_registry()
        assert reg == {"projects": {}}

    def test_non_dict_content_returns_empty_registry(self, tmp_path):
        """When file contains a list instead of dict, returns {'projects': {}}."""
        reg_path = tmp_path / "registry.json"
        reg_path.write_text("[1, 2, 3]")
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            reg = _load_worktree_registry()
        assert reg == {"projects": {}}


# ---------------------------------------------------------------------------
# lookup_worktree_project
# ---------------------------------------------------------------------------

class TestLookupWorktreeProject:
    """Tests for lookup_worktree_project()."""

    def test_lookup_worktree_project_found(self, tmp_path):
        """Returns project_folder for a known worktree path."""
        now = datetime.now(timezone.utc)
        reg = _make_registry({
            "/Users/ash/repo": _make_project(
                "-Users-ash-repo",
                {"/tmp/wt1": _make_worktree("feat-x", now)},
            ),
            "/Users/ash/other": _make_project(
                "-Users-ash-other",
                {"/tmp/wt2": _make_worktree("fix-y", now)},
            ),
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            result = lookup_worktree_project("/tmp/wt2")
        assert result == "-Users-ash-other"

    def test_lookup_worktree_project_not_found(self, tmp_path):
        """Returns None for an unknown worktree path."""
        now = datetime.now(timezone.utc)
        reg = _make_registry({
            "/Users/ash/repo": _make_project(
                "-Users-ash-repo",
                {"/tmp/wt1": _make_worktree("feat-x", now)},
            ),
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            result = lookup_worktree_project("/tmp/unknown")
        assert result is None

    def test_lookup_empty_registry(self, tmp_path):
        """Returns None when the registry file does not exist."""
        fake_path = tmp_path / "nonexistent.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", fake_path):
            result = lookup_worktree_project("/tmp/wt1")
        assert result is None


# ---------------------------------------------------------------------------
# list_project_worktrees
# ---------------------------------------------------------------------------

class TestListProjectWorktrees:
    """Tests for list_project_worktrees()."""

    def test_list_project_worktrees(self, tmp_path):
        """Returns the worktrees dict for a known project."""
        now = datetime.now(timezone.utc)
        wt_dict = {
            "/tmp/wt1": _make_worktree("feat-x", now),
            "/tmp/wt2": _make_worktree("fix-y", now),
        }
        reg = _make_registry({
            "/Users/ash/repo": _make_project("-Users-ash-repo", wt_dict),
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            result = list_project_worktrees("/Users/ash/repo")
        assert result == wt_dict

    def test_list_project_worktrees_unknown(self, tmp_path):
        """Returns empty dict for an unknown project."""
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(_make_registry())
            result = list_project_worktrees("/no/such/repo")
        assert result == {}


# ---------------------------------------------------------------------------
# prune_stale_worktrees
# ---------------------------------------------------------------------------

class TestPruneStaleWorktrees:
    """Tests for prune_stale_worktrees()."""

    def test_prune_stale_worktrees(self, tmp_path):
        """Old entries removed, fresh ones kept."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=60)
        fresh_time = now - timedelta(days=5)

        reg = _make_registry({
            "/Users/ash/repo": _make_project(
                "-Users-ash-repo",
                {
                    "/tmp/old-wt": _make_worktree("old-branch", old_time),
                    "/tmp/fresh-wt": _make_worktree("fresh-branch", fresh_time),
                },
            ),
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            removed = prune_stale_worktrees(max_age_days=30)
            loaded = _load_worktree_registry()

        assert removed == 1
        project = loaded["projects"]["/Users/ash/repo"]
        assert "/tmp/old-wt" not in project["worktrees"]
        assert "/tmp/fresh-wt" in project["worktrees"]

    def test_prune_removes_empty_project(self, tmp_path):
        """Project entry removed when all its worktrees are pruned."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=60)

        reg = _make_registry({
            "/Users/ash/repo": _make_project(
                "-Users-ash-repo",
                {"/tmp/old-wt": _make_worktree("old-branch", old_time)},
            ),
            "/Users/ash/other": _make_project(
                "-Users-ash-other",
                {"/tmp/fresh-wt": _make_worktree("fresh-branch", now)},
            ),
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            removed = prune_stale_worktrees(max_age_days=30)
            loaded = _load_worktree_registry()

        assert removed == 1
        assert "/Users/ash/repo" not in loaded["projects"]
        assert "/Users/ash/other" in loaded["projects"]

    def test_prune_no_changes_does_not_save(self, tmp_path):
        """When nothing is stale, the registry is not re-saved (no-op)."""
        now = datetime.now(timezone.utc)
        reg = _make_registry({
            "/Users/ash/repo": _make_project(
                "-Users-ash-repo",
                {"/tmp/fresh-wt": _make_worktree("fresh-branch", now)},
            ),
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            removed = prune_stale_worktrees(max_age_days=30)

        assert removed == 0

    def test_prune_empty_registry(self, tmp_path):
        """Pruning an empty registry returns 0 and doesn't error."""
        fake_path = tmp_path / "nonexistent.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", fake_path):
            removed = prune_stale_worktrees(max_age_days=30)
        assert removed == 0

    def test_prune_unparseable_last_seen_treated_as_stale(self, tmp_path):
        """Entries with corrupt timestamps are pruned as stale."""
        reg = _make_registry({
            "/Users/ash/repo": {
                "project_folder": "-Users-ash-repo",
                "worktrees": {
                    "/tmp/bad-wt": {"branch": "feat-x", "created": "2026-01-01", "last_seen": "not-a-date"},
                },
            },
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            removed = prune_stale_worktrees(max_age_days=30)
        assert removed == 1

    def test_prune_naive_datetime_treated_as_stale_when_old(self, tmp_path):
        """Naive datetime (no tzinfo) is assumed UTC and pruned when old enough."""
        reg = _make_registry({
            "/Users/ash/repo": {
                "project_folder": "-Users-ash-repo",
                "worktrees": {
                    "/tmp/old-naive": {"branch": "feat", "created": "2020-01-01", "last_seen": "2020-01-01T00:00:00"},
                },
            },
        })
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            _save_worktree_registry(reg)
            removed = prune_stale_worktrees(max_age_days=30)
        assert removed == 1


# ---------------------------------------------------------------------------
# _normalize_path — pure function, no I/O
# ---------------------------------------------------------------------------

class TestNormalizePath:
    def test_replaces_slashes_with_dashes(self):
        assert _normalize_path("/Users/alice/myapp") == "-Users-alice-myapp"

    def test_root_slash_becomes_leading_dash(self):
        result = _normalize_path("/")
        assert result == "-"

    def test_nested_path(self):
        assert _normalize_path("/home/user/projects/foo") == "-home-user-projects-foo"

    def test_empty_string(self):
        assert _normalize_path("") == ""

    def test_no_slashes_unchanged(self):
        assert _normalize_path("relative-path") == "relative-path"


# ---------------------------------------------------------------------------
# _resolve_cwd — reads env vars or cwd
# ---------------------------------------------------------------------------

class TestResolveCwd:
    def test_returns_explicit_cwd(self):
        assert _resolve_cwd("/my/explicit/path") == "/my/explicit/path"

    def test_uses_env_when_cwd_is_none(self):
        with mock.patch("os.environ.get", return_value="/from/env"):
            result = _resolve_cwd(None)
        # Should use CLAUDE_PROJECT_DIR from env
        assert result == "/from/env"

    def test_falls_back_to_getcwd(self, tmp_path):
        import os
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("os.getcwd", return_value=str(tmp_path)):
            result = _resolve_cwd(None)
        assert result == str(tmp_path)


# ---------------------------------------------------------------------------
# update_worktree_registry
# ---------------------------------------------------------------------------

from lib.shared import update_worktree_registry


class TestUpdateWorktreeRegistry:
    def test_creates_new_project_and_worktree(self, tmp_path):
        """Registry gains a new project + worktree when both are absent."""
        reg_file = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_file):
            update_worktree_registry("/main/repo", "/main/repo/feat", branch="feat")
        data = json.loads(reg_file.read_text())
        assert "/main/repo" in data["projects"]
        assert "/main/repo/feat" in data["projects"]["/main/repo"]["worktrees"]
        assert data["projects"]["/main/repo"]["worktrees"]["/main/repo/feat"]["branch"] == "feat"

    def test_updates_existing_worktree_last_seen(self, tmp_path):
        """Existing worktree entry gets last_seen updated."""
        reg_file = tmp_path / "registry.json"
        reg_file.write_text(json.dumps({
            "projects": {
                "/main/repo": {
                    "project_folder": "-main-repo",
                    "worktrees": {
                        "/main/repo/feat": {"branch": "feat", "created": "2026-01-01T00:00:00+00:00", "last_seen": "2026-01-01T00:00:00+00:00"},
                    },
                },
            },
        }))
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_file):
            update_worktree_registry("/main/repo", "/main/repo/feat")
        data = json.loads(reg_file.read_text())
        last_seen = data["projects"]["/main/repo"]["worktrees"]["/main/repo/feat"]["last_seen"]
        assert last_seen != "2026-01-01T00:00:00+00:00"  # updated

    def test_new_worktree_without_branch_has_no_branch_key(self, tmp_path):
        """When branch=None, the new worktree entry has no 'branch' key."""
        reg_file = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_file):
            update_worktree_registry("/main/repo", "/main/repo/feat", branch=None)
        data = json.loads(reg_file.read_text())
        wt = data["projects"]["/main/repo"]["worktrees"]["/main/repo/feat"]
        assert "branch" not in wt

    def test_updates_branch_on_existing_worktree(self, tmp_path):
        """Existing worktree entry gets branch updated when branch is provided."""
        reg_file = tmp_path / "registry.json"
        reg_file.write_text(json.dumps({
            "projects": {
                "/main/repo": {
                    "project_folder": "-main-repo",
                    "worktrees": {
                        "/main/repo/feat": {"branch": "old-branch", "created": "2026-01-01T00:00:00+00:00", "last_seen": "2026-01-01T00:00:00+00:00"},
                    },
                },
            },
        }))
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_file):
            update_worktree_registry("/main/repo", "/main/repo/feat", branch="new-branch")
        data = json.loads(reg_file.read_text())
        wt = data["projects"]["/main/repo"]["worktrees"]["/main/repo/feat"]
        assert wt["branch"] == "new-branch"
