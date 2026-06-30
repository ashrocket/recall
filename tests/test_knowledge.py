#!/usr/bin/env python3
"""Tests for lib/knowledge.py — bucket config, learnings, and formatting."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _make_index(learnings=None, pending=None):
    return {
        "version": 2,
        "sessions": {},
        "failure_patterns": {},
        "learnings": learnings or [],
        "pending_learnings": pending or [],
        "usage": {"skills": {}, "learnings_shown": {}},
    }


def _write_index(project_dir: Path, data: dict):
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "recall-index.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# _load_buckets_config
# ---------------------------------------------------------------------------

class TestLoadBucketsConfig:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        from lib.knowledge import _load_buckets_config
        missing = tmp_path / "nope.json"
        with mock.patch("lib.knowledge.BUCKETS_CONFIG_PATH", missing):
            result = _load_buckets_config()
        assert result == {}

    def test_returns_empty_dict_on_corrupt_json(self, tmp_path):
        from lib.knowledge import _load_buckets_config
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        with mock.patch("lib.knowledge.BUCKETS_CONFIG_PATH", bad):
            result = _load_buckets_config()
        assert result == {}

    def test_loads_valid_config(self, tmp_path):
        from lib.knowledge import _load_buckets_config
        cfg = tmp_path / "buckets.json"
        data = {"default_bucket": "work", "buckets": {"work": "Work stuff"}, "project_map": {"-x": "work"}}
        _write_config(cfg, data)
        with mock.patch("lib.knowledge.BUCKETS_CONFIG_PATH", cfg):
            result = _load_buckets_config()
        assert result == data

    def test_returns_empty_dict_when_file_is_not_a_dict(self, tmp_path):
        from lib.knowledge import _load_buckets_config
        bad = tmp_path / "list.json"
        bad.write_text("[1, 2, 3]")
        with mock.patch("lib.knowledge.BUCKETS_CONFIG_PATH", bad):
            result = _load_buckets_config()
        assert result == {}


# ---------------------------------------------------------------------------
# get_bucket_for_project
# ---------------------------------------------------------------------------

class TestGetBucketForProject:
    def test_returns_mapped_bucket(self):
        from lib.knowledge import get_bucket_for_project
        with mock.patch("lib.knowledge.PROJECT_BUCKET_MAP", {"-Users-alice-work": "business"}):
            with mock.patch("lib.knowledge.DEFAULT_BUCKET", "personal"):
                result = get_bucket_for_project("-Users-alice-work")
        assert result == "business"

    def test_returns_default_for_unknown_project(self):
        from lib.knowledge import get_bucket_for_project
        with mock.patch("lib.knowledge.PROJECT_BUCKET_MAP", {}):
            with mock.patch("lib.knowledge.DEFAULT_BUCKET", "personal"):
                result = get_bucket_for_project("-Users-alice-unknown")
        assert result == "personal"

    def test_calls_get_project_folder_when_none_given(self):
        from lib.knowledge import get_bucket_for_project
        with mock.patch("lib.knowledge.PROJECT_BUCKET_MAP", {"-derived": "claude"}):
            with mock.patch("lib.knowledge.DEFAULT_BUCKET", "personal"):
                with mock.patch("lib.knowledge.get_project_folder", return_value="-derived"):
                    result = get_bucket_for_project(None)
        assert result == "claude"


# ---------------------------------------------------------------------------
# BUILTIN_BUCKETS is always present
# ---------------------------------------------------------------------------

class TestBuiltinBuckets:
    def test_personal_bucket_exists(self):
        from lib.knowledge import BUILTIN_BUCKETS
        assert "personal" in BUILTIN_BUCKETS

    def test_claude_bucket_exists(self):
        from lib.knowledge import BUILTIN_BUCKETS
        assert "claude" in BUILTIN_BUCKETS


# ---------------------------------------------------------------------------
# add_pending_learning
# ---------------------------------------------------------------------------

class TestAddPendingLearning:
    def test_adds_new_learning_to_pending(self, tmp_path):
        from lib.knowledge import add_pending_learning
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index())
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = add_pending_learning({"title": "SSH keys", "category": "git"}, "proj")
        assert result is True
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["pending_learnings"]) == 1
        assert index["pending_learnings"][0]["title"] == "SSH keys"

    def test_rejects_duplicate_pending_title(self, tmp_path):
        from lib.knowledge import add_pending_learning
        proj_dir = tmp_path / "proj"
        existing = _make_index(pending=[{"title": "SSH keys", "category": "git"}])
        _write_index(proj_dir, existing)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = add_pending_learning({"title": "SSH keys", "category": "git"}, "proj")
        assert result is False
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["pending_learnings"]) == 1

    def test_rejects_title_already_in_approved(self, tmp_path):
        from lib.knowledge import add_pending_learning
        proj_dir = tmp_path / "proj"
        existing = _make_index(learnings=[{"title": "SSH keys", "category": "git"}])
        _write_index(proj_dir, existing)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = add_pending_learning({"title": "SSH keys", "category": "git"}, "proj")
        assert result is False

    def test_creates_pending_learnings_key_when_missing_from_index(self, tmp_path):
        """Legacy index without pending_learnings key gets the key created."""
        from lib.knowledge import add_pending_learning
        proj_dir = tmp_path / "proj"
        legacy_index = {
            "version": 1, "sessions": {}, "failure_patterns": {},
            "learnings": [],
            # no 'pending_learnings' key
        }
        _write_index(proj_dir, legacy_index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = add_pending_learning({"title": "New tip", "category": "git"}, "proj")
        assert result is True
        saved = json.loads((proj_dir / "recall-index.json").read_text())
        assert "pending_learnings" in saved
        assert saved["pending_learnings"][0]["title"] == "New tip"


# ---------------------------------------------------------------------------
# approve_learning
# ---------------------------------------------------------------------------

class TestApproveLearning:
    def test_moves_pending_to_approved(self, tmp_path):
        from lib.knowledge import approve_learning
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(pending=[
            {"title": "A", "category": "git"},
            {"title": "B", "category": "npm"},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            learning = approve_learning(0, "proj")
        assert learning["title"] == "A"
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["learnings"]) == 1
        assert index["learnings"][0]["title"] == "A"
        assert len(index["pending_learnings"]) == 1
        assert index["pending_learnings"][0]["title"] == "B"

    def test_returns_none_for_out_of_range_index(self, tmp_path):
        from lib.knowledge import approve_learning
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(pending=[{"title": "A"}]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = approve_learning(5, "proj")
        assert result is None

    def test_returns_none_for_empty_pending(self, tmp_path):
        from lib.knowledge import approve_learning
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index())
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = approve_learning(0, "proj")
        assert result is None

    def test_creates_learnings_key_when_missing(self, tmp_path):
        from lib.knowledge import approve_learning
        proj_dir = tmp_path / "proj"
        # Simulate an older index that lacks the 'learnings' key
        old_index = {"version": 2, "sessions": {}, "failure_patterns": {}, "pending_learnings": [{"title": "X"}], "usage": {}}
        _write_index(proj_dir, old_index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            learning = approve_learning(0, "proj")
        assert learning is not None
        assert learning["title"] == "X"


# ---------------------------------------------------------------------------
# reject_learning
# ---------------------------------------------------------------------------

class TestRejectLearning:
    def test_removes_from_pending(self, tmp_path):
        from lib.knowledge import reject_learning
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(pending=[
            {"title": "A"},
            {"title": "B"},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            removed = reject_learning(0, "proj")
        assert removed["title"] == "A"
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["pending_learnings"]) == 1
        assert index["pending_learnings"][0]["title"] == "B"
        assert index["learnings"] == []

    def test_returns_none_for_out_of_range(self, tmp_path):
        from lib.knowledge import reject_learning
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(pending=[{"title": "A"}]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = reject_learning(99, "proj")
        assert result is None


# ---------------------------------------------------------------------------
# approve_all_pending
# ---------------------------------------------------------------------------

class TestApproveAllPending:
    def test_approves_all(self, tmp_path):
        from lib.knowledge import approve_all_pending
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(pending=[
            {"title": "A"}, {"title": "B"}, {"title": "C"},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            count = approve_all_pending("proj")
        assert count == 3
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["learnings"]) == 3
        assert index["pending_learnings"] == []

    def test_returns_zero_when_nothing_pending(self, tmp_path):
        from lib.knowledge import approve_all_pending
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index())
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            count = approve_all_pending("proj")
        assert count == 0

    def test_appends_to_existing_approved(self, tmp_path):
        from lib.knowledge import approve_all_pending
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(
            learnings=[{"title": "Already approved"}],
            pending=[{"title": "New one"}],
        ))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            count = approve_all_pending("proj")
        assert count == 1
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["learnings"]) == 2

    def test_creates_learnings_key_when_missing(self, tmp_path):
        """Legacy index without learnings key gets the key created on approve_all."""
        from lib.knowledge import approve_all_pending
        proj_dir = tmp_path / "proj"
        legacy = {
            "version": 1, "sessions": {}, "failure_patterns": {},
            "pending_learnings": [{"title": "From pending"}],
            # no 'learnings' key
        }
        _write_index(proj_dir, legacy)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            count = approve_all_pending("proj")
        assert count == 1
        saved = json.loads((proj_dir / "recall-index.json").read_text())
        assert saved["learnings"][0]["title"] == "From pending"


# ---------------------------------------------------------------------------
# get_all_knowledge
# ---------------------------------------------------------------------------

class TestGetAllKnowledge:
    def test_groups_by_category(self, tmp_path):
        from lib.knowledge import get_all_knowledge
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(learnings=[
            {"title": "SSH keys", "category": "git", "solution": "use SSH"},
            {"title": "PYTHONPATH", "category": "python", "solution": "export it"},
            {"title": "rebase tip", "category": "git", "solution": "rebase -i"},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = get_all_knowledge("proj")
        assert sorted(result.keys()) == ["git", "python"]
        assert len(result["git"]) == 2
        assert len(result["python"]) == 1

    def test_empty_learnings_returns_empty_dict(self, tmp_path):
        from lib.knowledge import get_all_knowledge
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index())
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = get_all_knowledge("proj")
        assert result == {}

    def test_learning_without_solution_uses_title_only(self, tmp_path):
        from lib.knowledge import get_all_knowledge
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(learnings=[
            {"title": "No solution here", "category": "misc"},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = get_all_knowledge("proj")
        assert result["misc"] == ["No solution here"]

    def test_skips_non_dict_learnings(self, tmp_path):
        from lib.knowledge import get_all_knowledge
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(learnings=[
            "plain string learning",
            {"title": "Dict learning", "category": "git"},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = get_all_knowledge("proj")
        assert list(result.keys()) == ["git"]


# ---------------------------------------------------------------------------
# get_knowledge_by_bucket
# ---------------------------------------------------------------------------

class TestGetKnowledgeByBucket:
    def test_groups_by_bucket_then_category(self, tmp_path):
        from lib.knowledge import get_knowledge_by_bucket
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(learnings=[
            {"title": "SSH", "category": "git", "bucket": "work", "solution": ""},
            {"title": "pytest", "category": "python", "bucket": "personal", "solution": ""},
            {"title": "rebase", "category": "git", "bucket": "work", "solution": ""},
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = get_knowledge_by_bucket("proj")
        assert sorted(result.keys()) == ["personal", "work"]
        assert "git" in result["work"]
        assert len(result["work"]["git"]) == 2
        assert "python" in result["personal"]

    def test_uses_default_bucket_when_missing(self, tmp_path):
        from lib.knowledge import get_knowledge_by_bucket
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index(learnings=[
            {"title": "X", "category": "misc"},  # no bucket field
        ]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.knowledge.DEFAULT_BUCKET", "personal"):
                result = get_knowledge_by_bucket("proj")
        assert "personal" in result


# ---------------------------------------------------------------------------
# format_knowledge_summary
# ---------------------------------------------------------------------------

class TestFormatKnowledgeSummary:
    def test_lists_categories_with_counts(self):
        from lib.knowledge import format_knowledge_summary
        knowledge = {"git": ["a", "b"], "python": ["c"]}
        result = format_knowledge_summary(knowledge)
        assert "[git] 2 learnings" in result
        assert "[python] 1 learnings" in result

    def test_empty_returns_no_learnings_message(self):
        from lib.knowledge import format_knowledge_summary
        result = format_knowledge_summary({})
        assert "No learnings" in result

    def test_categories_sorted_alphabetically(self):
        from lib.knowledge import format_knowledge_summary
        knowledge = {"python": ["x"], "git": ["y"], "npm": ["z"]}
        result = format_knowledge_summary(knowledge)
        lines = result.splitlines()
        cats = [line.strip().split("]")[0].lstrip("[") for line in lines]
        assert cats == sorted(cats)


# ---------------------------------------------------------------------------
# format_bucketed_summary
# ---------------------------------------------------------------------------

class TestFormatBucketedSummary:
    def test_shows_buckets_with_totals(self):
        from lib.knowledge import format_bucketed_summary, BUILTIN_BUCKETS
        buckets = {
            "work": {"git": ["a", "b"], "npm": ["c"]},
            "personal": {"python": ["d"]},
        }
        result = format_bucketed_summary(buckets)
        assert "Work" in result
        assert "Personal" in result
        assert "3 learnings" in result
        assert "1 learnings" in result

    def test_empty_returns_no_learnings_message(self):
        from lib.knowledge import format_bucketed_summary
        result = format_bucketed_summary({})
        assert "No learnings" in result

    def test_builtin_buckets_sort_last(self):
        from lib.knowledge import format_bucketed_summary, BUILTIN_BUCKETS
        buckets = {
            "personal": {"x": ["a"]},   # builtin
            "work": {"y": ["b"]},        # custom
        }
        result = format_bucketed_summary(buckets)
        lines = [l for l in result.splitlines() if l.strip()]
        # "work" (custom) should appear before "personal" (builtin) in sorted order
        work_idx = next(i for i, l in enumerate(lines) if "Work" in l)
        personal_idx = next(i for i, l in enumerate(lines) if "Personal" in l)
        assert work_idx < personal_idx


# ---------------------------------------------------------------------------
# get_project_claude_md
# ---------------------------------------------------------------------------

class TestGetProjectClaudeMd:
    def test_finds_claude_md_in_cwd(self, tmp_path):
        from lib.knowledge import get_project_claude_md
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Guidance")
        with mock.patch("lib.knowledge.Path") as MockPath:
            MockPath.cwd.return_value = tmp_path
            # Make the instance returned by Path(cwd) / "CLAUDE.md" resolve correctly
            # Instead, directly patch at the call site
            pass
        # Use monkeypatch-style: change cwd
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = get_project_claude_md()
        finally:
            os.chdir(old_cwd)
        assert result == claude_md

    def test_returns_none_when_not_found(self, tmp_path):
        from lib.knowledge import get_project_claude_md
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = get_project_claude_md()
        finally:
            os.chdir(old_cwd)
        assert result is None


# ---------------------------------------------------------------------------
# get_learnings / get_pending_learnings
# ---------------------------------------------------------------------------

class TestGetLearningsAndPending:
    def test_get_learnings_returns_approved(self, tmp_path):
        from lib.knowledge import get_learnings
        learning = {"bucket": "personal", "category": "python", "title": "Use pathlib"}
        index = {"version": 2, "sessions": {}, "failure_patterns": {}, "learnings": [learning], "pending_learnings": [], "usage": {}}
        import json
        (tmp_path / "recall-index.json").write_text(json.dumps(index))
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = get_learnings("proj")
        assert len(result) == 1
        assert result[0]["title"] == "Use pathlib"

    def test_get_learnings_returns_empty_when_none(self, tmp_path):
        from lib.knowledge import get_learnings
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = get_learnings("proj")
        assert result == []

    def test_get_pending_learnings_returns_pending(self, tmp_path):
        from lib.knowledge import get_pending_learnings
        pending = {"bucket": "personal", "category": "git", "title": "Rebase tip"}
        index = {"version": 2, "sessions": {}, "failure_patterns": {}, "learnings": [], "pending_learnings": [pending], "usage": {}}
        import json
        (tmp_path / "recall-index.json").write_text(json.dumps(index))
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = get_pending_learnings("proj")
        assert len(result) == 1
        assert result[0]["title"] == "Rebase tip"


# ---------------------------------------------------------------------------
# rejection tombstones — rejected learnings must not be re-proposed
# ---------------------------------------------------------------------------

class TestRejectionTombstones:
    def test_reject_learning_records_tombstone(self, tmp_path):
        from lib.knowledge import reject_learning
        proj_dir = tmp_path / "proj"
        learning = {"title": "Fix for cat failure", "description": "Command `cat X` failed with: ..."}
        _write_index(proj_dir, _make_index(pending=[learning]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            removed = reject_learning(0, "proj")
        assert removed["title"] == "Fix for cat failure"
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert index["pending_learnings"] == []
        assert len(index.get("rejected_learnings", [])) == 1

    def test_rejected_learning_not_reproposed(self, tmp_path):
        from lib.knowledge import add_pending_learning, reject_learning
        proj_dir = tmp_path / "proj"
        learning = {"title": "Fix for cat failure", "description": "Command `cat X` failed with: ..."}
        _write_index(proj_dir, _make_index(pending=[learning]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            reject_learning(0, "proj")
            result = add_pending_learning(dict(learning), "proj")
        assert result is False
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert index["pending_learnings"] == []

    def test_different_failure_with_same_title_still_proposed(self, tmp_path):
        """Tombstones key on title+description, not bare title — a NEW cat
        failure (different description) must still be proposable."""
        from lib.knowledge import add_pending_learning, reject_learning
        proj_dir = tmp_path / "proj"
        old = {"title": "Fix for cat failure", "description": "Command `cat X` failed with: ..."}
        _write_index(proj_dir, _make_index(pending=[old]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            reject_learning(0, "proj")
            new = {"title": "Fix for cat failure", "description": "Command `cat Y` failed with: different error"}
            result = add_pending_learning(new, "proj")
        assert result is True

    def test_tombstone_list_capped(self, tmp_path):
        from lib.knowledge import reject_learning, MAX_REJECTED_TOMBSTONES
        proj_dir = tmp_path / "proj"
        idx = _make_index(pending=[{"title": "t", "description": "d"}])
        idx["rejected_learnings"] = [f"old|{i}" for i in range(MAX_REJECTED_TOMBSTONES)]
        _write_index(proj_dir, idx)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            reject_learning(0, "proj")
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert len(index["rejected_learnings"]) == MAX_REJECTED_TOMBSTONES
        # newest tombstone kept, oldest dropped
        assert "old|0" not in index["rejected_learnings"]

    def test_rejected_learning_count_variant_not_reproposed(self, tmp_path):
        """Rejecting 'Recurring general errors (5x ...)' must also suppress
        the same pattern re-proposed later as '(7x ...)' — the occurrence
        count is not part of the learning's identity."""
        from lib.knowledge import add_pending_learning, reject_learning
        proj_dir = tmp_path / "proj"
        old = {
            "title": "Recurring general errors (5x in session)",
            "description": "Hit 5 general errors. Example: `git diff`",
        }
        _write_index(proj_dir, _make_index(pending=[old]))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            reject_learning(0, "proj")
            new = {
                "title": "Recurring general errors (7x in session)",
                "description": "Hit 7 general errors. Example: `git diff`",
            }
            result = add_pending_learning(new, "proj")
        assert result is False
        index = json.loads((proj_dir / "recall-index.json").read_text())
        assert index["pending_learnings"] == []

    def test_legacy_raw_tombstones_still_suppress(self, tmp_path):
        """Tombstones written before key normalization (raw title|description
        strings, digits intact) must still suppress their proposal."""
        from lib.knowledge import add_pending_learning
        proj_dir = tmp_path / "proj"
        learning = {
            "title": "Recurring general errors (5x in session)",
            "description": "Hit 5 general errors. Example: `git diff`",
        }
        idx = _make_index()
        idx["rejected_learnings"] = [
            f"{learning['title']}|{learning['description'][:80]}"
        ]
        _write_index(proj_dir, idx)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            result = add_pending_learning(dict(learning), "proj")
        assert result is False
