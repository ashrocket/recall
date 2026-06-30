#!/usr/bin/env python3
"""Tests for bin/recall-learn.py display and action functions."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_recall_learn():
    spec = importlib.util.spec_from_file_location(
        "recall_learn",
        Path(__file__).resolve().parent.parent / "bin" / "recall-learn.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        rv = fn(*args, **kwargs)
    return rv, buf.getvalue()


def _make_learning(title="SSH fix", category="git", bucket="personal",
                   description="use SSH", solution="git@github.com", source="failure_resolution"):
    return {
        "title": title,
        "category": category,
        "bucket": bucket,
        "description": description,
        "solution": solution,
        "source": source,
    }


def _write_index(proj_dir: Path, pending=None, approved=None):
    proj_dir.mkdir(parents=True, exist_ok=True)
    index = {
        "version": 2,
        "sessions": {},
        "failure_patterns": {},
        "learnings": approved or [],
        "pending_learnings": pending or [],
        "usage": {"skills": {}, "learnings_shown": {}},
    }
    (proj_dir / "recall-index.json").write_text(json.dumps(index))
    return index


# ---------------------------------------------------------------------------
# format_learning
# ---------------------------------------------------------------------------

class TestFormatLearning:
    def test_includes_index_and_category(self):
        mod = _import_recall_learn()
        result = mod.format_learning(_make_learning(title="My fix", category="git"), 3)
        assert "[3]" in result
        assert "git" in result
        assert "My fix" in result

    def test_includes_description(self):
        mod = _import_recall_learn()
        result = mod.format_learning(_make_learning(description="Always use SSH keys"), 0)
        assert "Always use SSH keys" in result

    def test_includes_solution(self):
        mod = _import_recall_learn()
        result = mod.format_learning(_make_learning(solution="git@github.com"), 0)
        assert "git@github.com" in result

    def test_includes_source(self):
        mod = _import_recall_learn()
        result = mod.format_learning(_make_learning(source="failure_resolution"), 0)
        assert "failure_resolution" in result

    def test_bucket_label_is_first_letter_uppercase(self):
        mod = _import_recall_learn()
        result = mod.format_learning(_make_learning(bucket="personal"), 0)
        assert "[P:" in result

    def test_empty_description_and_solution_omitted(self):
        mod = _import_recall_learn()
        learning = _make_learning(description="", solution="")
        result = mod.format_learning(learning, 0)
        assert "Fix:" not in result
        # Should still have title and source
        assert "SSH fix" in result

    def test_fix_field_takes_precedence_over_solution(self):
        mod = _import_recall_learn()
        learning = {**_make_learning(), "fix": "Always use SSH — tokens expire.", "solution": "git remote set-url origin git@..."}
        result = mod.format_learning(learning, 0)
        assert "Always use SSH" in result
        assert "git remote set-url" not in result

    def test_falls_back_to_solution_when_no_fix(self):
        mod = _import_recall_learn()
        result = mod.format_learning(_make_learning(solution="git remote set-url origin git@github.com:org/repo.git"), 0)
        assert "git remote set-url" in result

    def test_truncates_multiline_description(self):
        mod = _import_recall_learn()
        learning = _make_learning(description="First line\nSecond line\nThird line")
        result = mod.format_learning(learning, 0)
        assert "First line..." in result
        assert "Second line" not in result

    def test_truncates_multiline_fix(self):
        mod = _import_recall_learn()
        learning = {**_make_learning(), "fix": "First fix line\nSecond fix line"}
        result = mod.format_learning(learning, 0)
        assert "First fix line..." in result
        assert "Second fix line" not in result


# ---------------------------------------------------------------------------
# show_pending
# ---------------------------------------------------------------------------

class TestShowPending:
    def test_shows_no_pending_message_when_empty(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "No pending learnings" in output

    def test_shows_pending_count(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning("Fix 1"), _make_learning("Fix 2")])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "2" in output

    def test_shows_each_pending_learning(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[
            _make_learning("SSH authentication fix"),
            _make_learning("npm cache clear"),
        ])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "SSH authentication fix" in output
        assert "npm cache clear" in output

    def test_shows_approved_count(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, approved=[_make_learning()])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "1" in output  # approved count

    def test_shows_actions_when_pending_exist(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning()])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "--batch" in output
        assert "--approve" in output
        assert "--reject" in output

    def test_groups_by_bucket(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[
            _make_learning("personal thing", bucket="personal"),
            _make_learning("claude thing", bucket="claude"),
        ])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        # Both should appear; bucket labels from BUCKETS config
        assert "personal thing" in output
        assert "claude thing" in output

    def test_unknown_bucket_still_displayed(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[
            _make_learning("experimental thing", bucket="experimental"),
        ])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "experimental thing" in output

    def test_recall_failures_hint_when_approved_and_no_pending(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, approved=[_make_learning("an approved learning")])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.show_pending, "proj")
        assert "/recall failures" in output


# ---------------------------------------------------------------------------
# approve_one
# ---------------------------------------------------------------------------

class TestApproveOne:
    def test_approves_valid_index(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning("SSH fix", category="git")])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.approve_one, "proj", "0")
        assert "Approved" in output
        assert "SSH fix" in output

    def test_rejects_invalid_string_index(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.approve_one, "proj", "notanumber")
        assert "Invalid index" in output

    def test_handles_out_of_range_index(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning()])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.approve_one, "proj", "99")
        assert "No pending learning" in output or "99" in output


# ---------------------------------------------------------------------------
# reject_one
# ---------------------------------------------------------------------------

class TestRejectOne:
    def test_rejects_valid_index(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning("Bad pattern", category="shell")])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.reject_one, "proj", "0")
        assert "Rejected" in output
        assert "Bad pattern" in output

    def test_rejects_invalid_string_index(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.reject_one, "proj", "abc")
        assert "Invalid index" in output

    def test_handles_out_of_range(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning()])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.reject_one, "proj", "50")
        assert "No pending learning" in output or "50" in output


# ---------------------------------------------------------------------------
# batch_approve
# ---------------------------------------------------------------------------

class TestBatchApprove:
    def test_approves_all_pending(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning("python", "PEP8 style"), _make_learning("git", "Rebase tip")])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.batch_approve, "proj")
        assert "2" in output
        assert "Approved" in output

    def test_prints_nothing_when_no_pending(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(mod.batch_approve, "proj")
        assert "No pending" in output

    def test_pending_moved_to_learnings(self, tmp_path):
        mod = _import_recall_learn()
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, pending=[_make_learning("shell", "Tip")], approved=[])
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            mod.batch_approve("proj")
        # Load the index and verify learnings now contains the approved item
        import json
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["learnings"]) == 1
        assert index["pending_learnings"] == []
