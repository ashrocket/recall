#!/usr/bin/env python3
"""Tests for worktree resolution in lib/shared.py."""

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

# Ensure lib/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.shared import (
    _resolve_worktree_by_path,
    resolve_worktree_root,
    update_worktree_registry,
    get_project_folder,
    get_project_folders,
    WORKTREE_REGISTRY_PATH,
    _load_worktree_registry,
    _save_worktree_registry,
)


# ---------------------------------------------------------------------------
# resolve_worktree_root
# ---------------------------------------------------------------------------

class TestResolveWorktreeRoot:
    """Tests for resolve_worktree_root()."""

    def test_regular_git_dir_returns_none(self, tmp_path):
        """When .git is a directory (normal repo), returns None."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert resolve_worktree_root(str(tmp_path)) is None

    def test_no_git_at_all_returns_none(self, tmp_path):
        """When there is no .git at all, returns None."""
        assert resolve_worktree_root(str(tmp_path)) is None

    def test_worktree_git_file_triggers_resolution(self, tmp_path):
        """When .git is a file (worktree marker), subprocess is called and
        the first worktree path from --porcelain output is returned."""
        # Create a .git file like a real worktree has
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /main/repo/.git/worktrees/feature-branch\n")

        porcelain_output = (
            "worktree /main/repo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            f"worktree {tmp_path}\n"
            "HEAD def456\n"
            "branch refs/heads/feature-branch\n"
            "\n"
        )

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout=porcelain_output,
            )
            result = resolve_worktree_root(str(tmp_path))

        assert result == "/main/repo"
        mock_run.assert_called_once()

    def test_git_not_installed_returns_none(self, tmp_path):
        """When git is not installed (FileNotFoundError), returns None."""
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /somewhere/.git/worktrees/branch\n")

        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            result = resolve_worktree_root(str(tmp_path))

        assert result is None

    def test_git_command_fails_returns_none(self, tmp_path):
        """When git worktree list returns non-zero, returns None."""
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /somewhere/.git/worktrees/branch\n")

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            result = resolve_worktree_root(str(tmp_path))

        assert result is None

    def test_git_timeout_returns_none(self, tmp_path):
        """When git command times out (TimeoutExpired), returns None."""
        import subprocess
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /somewhere/.git/worktrees/branch\n")

        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            result = resolve_worktree_root(str(tmp_path))

        assert result is None


# ---------------------------------------------------------------------------
# Worktree registry helpers
# ---------------------------------------------------------------------------

class TestWorktreeRegistry:
    """Tests for _load_worktree_registry / _save_worktree_registry."""

    def test_load_missing_file_returns_empty(self, tmp_path):
        fake_path = tmp_path / "nonexistent.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", fake_path):
            reg = _load_worktree_registry()
        assert reg == {"projects": {}}

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{corrupt json!!")
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", bad_file):
            reg = _load_worktree_registry()
        assert reg == {"projects": {}}

    def test_save_and_load_roundtrip(self, tmp_path):
        reg_path = tmp_path / "sub" / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            data = {"projects": {"/main/repo": {"worktrees": {"/wt/path": {"branch": "feat"}}}}}
            _save_worktree_registry(data)
            loaded = _load_worktree_registry()
        assert loaded == data

    def test_update_worktree_registry_creates_entry(self, tmp_path):
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            update_worktree_registry("/main/repo", "/wt/feat-branch", branch="feat-branch")
            reg = _load_worktree_registry()

        assert "/main/repo" in reg["projects"]
        wt_entry = reg["projects"]["/main/repo"]["worktrees"]["/wt/feat-branch"]
        assert wt_entry["branch"] == "feat-branch"
        assert "created" in wt_entry
        assert "last_seen" in wt_entry

    def test_update_worktree_registry_updates_last_seen(self, tmp_path):
        reg_path = tmp_path / "registry.json"
        with mock.patch("lib.shared.WORKTREE_REGISTRY_PATH", reg_path):
            update_worktree_registry("/main/repo", "/wt/feat", branch="feat")
            reg1 = _load_worktree_registry()
            created = reg1["projects"]["/main/repo"]["worktrees"]["/wt/feat"]["created"]

            # Update again
            update_worktree_registry("/main/repo", "/wt/feat", branch="feat")
            reg2 = _load_worktree_registry()

        entry = reg2["projects"]["/main/repo"]["worktrees"]["/wt/feat"]
        assert entry["created"] == created  # created stays the same
        assert "last_seen" in entry


# ---------------------------------------------------------------------------
# get_project_folder integration with worktree resolution
# ---------------------------------------------------------------------------

class TestGetProjectFolderWorktree:
    """Tests for get_project_folder() with worktree resolution."""

    def test_worktree_resolves_to_main_repo(self, tmp_path):
        """When resolve_worktree_root returns a path, get_project_folder
        uses that path instead of the worktree cwd."""
        worktree_cwd = str(tmp_path / "worktrees" / "feature-x")

        with mock.patch("lib.shared.resolve_worktree_root", return_value="/home/user/main-repo") as mock_resolve, \
             mock.patch("lib.shared.update_worktree_registry") as mock_update:
            result = get_project_folder(worktree_cwd)

        assert result == "-home-user-main-repo"
        mock_resolve.assert_called_once_with(worktree_cwd)
        mock_update.assert_called_once()

    def test_normal_repo_unchanged(self, tmp_path):
        """When resolve_worktree_root returns None, get_project_folder
        behaves exactly as before (cwd.replace('/', '-'))."""
        normal_cwd = "/home/user/my-project"

        with mock.patch("lib.shared.resolve_worktree_root", return_value=None):
            result = get_project_folder(normal_cwd)

        assert result == "-home-user-my-project"

    def test_env_var_fallback_still_works(self):
        """CLAUDE_PROJECT_DIR env var is still respected when cwd is None."""
        with mock.patch("lib.shared.resolve_worktree_root", return_value=None), \
             mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/from/env"}):
            result = get_project_folder(None)

        assert result == "-from-env"

    def test_branch_extracted_from_git_file(self, tmp_path):
        """Branch name is parsed from the .git file content and passed
        to update_worktree_registry."""
        worktree_dir = tmp_path / "worktrees" / "my-feature"
        worktree_dir.mkdir(parents=True)
        git_file = worktree_dir / ".git"
        git_file.write_text("gitdir: /main/repo/.git/worktrees/my-feature\n")

        with mock.patch("lib.shared.resolve_worktree_root", return_value="/main/repo") as mock_resolve, \
             mock.patch("lib.shared.update_worktree_registry") as mock_update:
            result = get_project_folder(str(worktree_dir))

        assert result == "-main-repo"
        mock_update.assert_called_once_with("/main/repo", str(worktree_dir), "my-feature")


# ---------------------------------------------------------------------------
# _resolve_worktree_by_path (path-based fallback)
# ---------------------------------------------------------------------------

class TestResolveWorktreeByPath:
    """Tests for _resolve_worktree_by_path() — fallback when .git is gone."""

    def test_dot_worktrees_pattern(self, tmp_path):
        """Matches /.worktrees/ in path and returns parent."""
        parent = tmp_path / "my-repo"
        parent.mkdir()
        wt_path = str(parent / ".worktrees" / "feature-x")
        assert _resolve_worktree_by_path(wt_path) == str(parent)

    def test_claude_worktrees_pattern(self, tmp_path):
        """Matches /.claude-worktrees/ in path."""
        parent = tmp_path / "my-repo"
        parent.mkdir()
        wt_path = str(parent / ".claude-worktrees" / "gdrive-connector")
        assert _resolve_worktree_by_path(wt_path) == str(parent)

    def test_trailing_slash(self, tmp_path):
        """Handles trailing slash in path."""
        parent = tmp_path / "repo"
        parent.mkdir()
        wt_path = str(parent / ".worktrees" / "feat") + "/"
        assert _resolve_worktree_by_path(wt_path) == str(parent)

    def test_normal_path_returns_none(self):
        """Non-worktree paths return None."""
        assert _resolve_worktree_by_path("/home/user/repo") is None
        assert _resolve_worktree_by_path("/home/user/repo/src") is None

    def test_parent_must_exist(self, tmp_path):
        """Returns None when parent dir doesn't exist."""
        wt_path = str(tmp_path / "nonexistent-repo" / ".worktrees" / "feat")
        assert _resolve_worktree_by_path(wt_path) is None


class TestResolveWorktreeRootFallback:
    """Tests that resolve_worktree_root uses path fallback."""

    def test_cleaned_up_worktree_uses_path_fallback(self, tmp_path):
        """When .git is gone (worktree cleaned up), path fallback kicks in."""
        parent = tmp_path / "my-repo"
        parent.mkdir()
        # No .git file — worktree was cleaned up
        wt_path = str(parent / ".worktrees" / "feature-x")
        result = resolve_worktree_root(wt_path)
        assert result == str(parent)

    def test_live_worktree_prefers_git_detection(self, tmp_path):
        """When .git file exists, git-based detection is preferred."""
        parent = tmp_path / "repo"
        parent.mkdir()
        wt_dir = parent / ".worktrees" / "feat"
        wt_dir.mkdir(parents=True)
        git_file = wt_dir / ".git"
        git_file.write_text("gitdir: /actual/repo/.git/worktrees/feat\n")

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="worktree /actual/repo\nHEAD abc\n",
            )
            result = resolve_worktree_root(str(wt_dir))

        # Should use git result, not path pattern
        assert result == "/actual/repo"


# ---------------------------------------------------------------------------
# get_project_folders (dual return)
# ---------------------------------------------------------------------------

class TestGetProjectFolders:
    """Tests for get_project_folders() returning (resolved, raw) tuple."""

    def test_worktree_returns_different_folders(self):
        """For a worktree, resolved != raw."""
        wt_cwd = "/Users/ash/repo/.worktrees/feat-x"

        with mock.patch("lib.shared.resolve_worktree_root", return_value="/Users/ash/repo"), \
             mock.patch("lib.shared.update_worktree_registry"):
            resolved, raw = get_project_folders(wt_cwd)

        assert resolved == "-Users-ash-repo"
        assert raw == "-Users-ash-repo-.worktrees-feat-x"

    def test_normal_repo_returns_identical_folders(self):
        """For a normal repo, resolved == raw."""
        cwd = "/Users/ash/repo"

        with mock.patch("lib.shared.resolve_worktree_root", return_value=None):
            resolved, raw = get_project_folders(cwd)

        assert resolved == raw == "-Users-ash-repo"
