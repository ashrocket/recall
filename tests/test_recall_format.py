#!/usr/bin/env python3
"""
Tests for lib/recall_format.py — standalone validation that the library
module works independently (not just via recall-sessions.py re-exports).
"""

import io
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lib.recall_format import (
    _matches_terms,
    compile_regex_query,
    format_date,
    literal_search_terms,
    matches_search_query,
    normalize_search_query,
    show_stats,
    show_failures,
)


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        rv = fn(*args, **kwargs)
    return rv, buf.getvalue()


def _make_index(**kwargs):
    base = {
        "version": 2,
        "sessions": {},
        "failure_patterns": {},
        "learnings": [],
        "pending_learnings": [],
        "usage": {"skills": {}, "learnings_shown": {}},
    }
    base.update(kwargs)
    return base


def _write_index(proj_dir: Path, index: dict):
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "recall-index.json").write_text(json.dumps(index))


# ---------------------------------------------------------------------------
# format_date — direct import from lib
# ---------------------------------------------------------------------------

class TestFormatDate:
    def test_iso_string(self):
        assert format_date("2026-04-24T10:30:00") == "2026-04-24 10:30"

    def test_datetime_object(self):
        dt = datetime(2026, 4, 24, 10, 30)
        assert format_date(dt) == "2026-04-24 10:30"

    def test_z_suffix(self):
        result = format_date("2026-04-24T10:30:00Z")
        assert result == "2026-04-24 10:30"

    def test_fallback_on_non_parseable(self):
        result = format_date("not-a-date-string")
        assert isinstance(result, str)

    def test_non_string_non_datetime_converted_to_str(self):
        """Anything that is not str or datetime gets str() called on it."""
        result = format_date(12345)
        assert result == "12345"


# ---------------------------------------------------------------------------
# _matches_terms — direct import from lib
# ---------------------------------------------------------------------------

class TestMatchesTerms:
    def test_single_term_hit(self):
        assert _matches_terms("fix authentication", ["auth"]) is True

    def test_single_term_miss(self):
        assert _matches_terms("unrelated content", ["auth"]) is False

    def test_multi_term_all_present(self):
        assert _matches_terms("jwt authentication token", ["jwt", "auth"]) is True

    def test_multi_term_partial_miss(self):
        assert _matches_terms("jwt token only", ["jwt", "auth"]) is False

    def test_case_insensitive(self):
        assert _matches_terms("FIX PAYMENT BUG", ["payment"]) is True


# ---------------------------------------------------------------------------
# Search query helpers
# ---------------------------------------------------------------------------

class TestSearchQueryHelpers:
    def test_normalizes_outer_quotes_for_literal_search(self):
        assert normalize_search_query("'.p8'") == ".p8"

    def test_literal_terms_ignore_standalone_question_mark(self):
        assert literal_search_terms("sops ?") == ["sops"]

    def test_regex_query_matches_path_fragment(self):
        assert matches_search_query("keys/AuthKey_12345.p8", r"/.*\.p8/")

    def test_leading_bare_star_regex_is_forgiving(self):
        assert matches_search_query("keys/AuthKey_12345.p8", r"/*\.p8/")

    def test_invalid_regex_returns_error(self):
        regex, error = compile_regex_query("/[/")
        assert regex is None
        assert error

    def test_absolute_path_search_is_literal_not_regex(self):
        regex, error = compile_regex_query("/Users/exampleuser/AuthKey_12345.p8")
        assert regex is None
        assert error is None
        assert matches_search_query("open /Users/exampleuser/AuthKey_12345.p8", "/Users/exampleuser/AuthKey_12345.p8")


# ---------------------------------------------------------------------------
# show_stats — direct import from lib
# ---------------------------------------------------------------------------

class TestShowStats:
    def test_no_usage_shows_empty_message(self, tmp_path):
        _, output = _capture(show_stats, _make_index(), "proj")
        assert "No skill usage" in output
        assert "No learning displays" in output

    def test_shows_skill_counts(self, tmp_path):
        index = _make_index(usage={
            "skills": {"recall": {"count": 5, "sessions": ["s1"], "last_used": "2026-04-24"}},
            "learnings_shown": {},
        })
        _, output = _capture(show_stats, index, "proj")
        assert "recall" in output
        assert "5" in output

    def test_shows_learnings_display_counts(self, tmp_path):
        """When learnings_shown is non-empty, displays count and last-shown date."""
        index = _make_index(usage={
            "skills": {},
            "learnings_shown": {
                "git/SSH tip": {"count": 3, "last_shown": "2026-04-24T10:00:00"},
            },
        })
        _, output = _capture(show_stats, index, "proj")
        assert "git/SSH tip" in output
        assert "3" in output

    def test_shows_unused_learnings(self, tmp_path):
        index = _make_index(
            learnings=[{"category": "git", "title": "SSH tip"}],
            usage={"skills": {}, "learnings_shown": {}},
        )
        _, output = _capture(show_stats, index, "proj")
        assert "Unused Learnings" in output
        assert "git/SSH tip" in output

    def test_non_dict_learnings_skipped_in_stats(self, tmp_path):
        index = _make_index(
            learnings=["plain string learning", {"category": "git", "title": "SSH tip"}],
            usage={"skills": {}, "learnings_shown": {}},
        )
        _, output = _capture(show_stats, index, "proj")
        assert "Unused Learnings" in output
        assert "git/SSH tip" in output


# ---------------------------------------------------------------------------
# show_failures — direct import from lib
# ---------------------------------------------------------------------------

class TestShowFailures:
    def test_no_patterns_or_learnings(self, tmp_path):
        proj_dir = tmp_path / "proj"
        _write_index(proj_dir, _make_index())
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, _make_index(), "proj")
        assert "No failure patterns" in output

    def test_learnings_shown_without_failure_patterns(self, tmp_path):
        """When there are learnings but no failure_patterns, the message is not shown."""
        proj_dir = tmp_path / "proj"
        index = _make_index(
            failure_patterns={},
            learnings=[{"title": "Use SSH", "category": "git", "description": "prefer SSH", "solution": "git@"}],
        )
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "Use SSH" in output
        assert "No failure patterns or learnings recorded yet" not in output

    def test_shows_failure_category(self, tmp_path):
        proj_dir = tmp_path / "proj"
        index = _make_index(failure_patterns={
            "git_error": [{"command": "git push", "date": "2026-04-01", "error": "fatal: denied"}]
        })
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "Git Error" in output

    def test_shows_learnings_before_failures(self, tmp_path):
        proj_dir = tmp_path / "proj"
        index = _make_index(
            failure_patterns={"git_error": [{"command": "git push", "date": "2026-04-01", "error": "fatal"}]},
            learnings=[{"title": "Use SSH", "category": "git", "description": "prefer SSH", "solution": "git@"}],
        )
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert output.index("Use SSH") < output.index("git push")

    def test_shows_learning_examples_section(self, tmp_path):
        proj_dir = tmp_path / "proj"
        index = _make_index(
            learnings=[{
                "title": "rebase tip", "category": "git",
                "description": "", "solution": "",
                "examples": ["git rebase -i HEAD~3", "git rebase origin/main"],
            }]
        )
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "Examples" in output
        assert "rebase -i" in output

    def test_shows_non_dict_learning_as_plain_text(self, tmp_path):
        proj_dir = tmp_path / "proj"
        index = _make_index(learnings=["plain text learning"])
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "plain text learning" in output

    def test_failure_without_error_field_shows_command_only(self, tmp_path):
        proj_dir = tmp_path / "proj"
        index = _make_index(failure_patterns={
            "git_error": [{"command": "git push", "date": "2026-04-01"}]  # no 'error' key
        })
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "git push" in output
        assert "Error:" not in output

    def test_shows_tools_section_in_learning(self, tmp_path):
        proj_dir = tmp_path / "proj"
        index = _make_index(learnings=[{
            "title": "CI tool tip", "category": "ci",
            "description": "", "solution": "",
            "tools": {"pytest": "run with --tb=short for cleaner output"},
        }])
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "Tools" in output
        assert "pytest" in output

    def test_increments_existing_learning_display_count(self, tmp_path):
        """Learning already in learnings_shown gets count incremented, not reset."""
        proj_dir = tmp_path / "proj"
        index = {
            "version": 2, "sessions": {}, "failure_patterns": {},
            "learnings": [{"title": "SSH tip", "category": "git", "description": "", "solution": ""}],
            "pending_learnings": [],
            "usage": {"skills": {}, "learnings_shown": {"git/SSH tip": {"count": 3, "last_shown": "2026-04-01", "first_shown": "2026-03-01"}}},
        }
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, _ = _capture(show_failures, index, "proj")
        assert index["usage"]["learnings_shown"]["git/SSH tip"]["count"] == 4

    def test_creates_usage_key_when_missing(self, tmp_path):
        """show_failures creates index['usage'] when the key is absent."""
        proj_dir = tmp_path / "proj"
        # Build index WITHOUT 'usage' key
        index = {
            "version": 2, "sessions": {}, "failure_patterns": {},
            "learnings": [{"title": "tip", "category": "git", "description": "", "solution": ""}],
            "pending_learnings": [],
        }
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "usage" in index
        assert "git/tip" in index["usage"]["learnings_shown"]

    def test_creates_learnings_shown_when_usage_exists_but_key_missing(self, tmp_path):
        """show_failures adds learnings_shown when usage exists but lacks that key."""
        proj_dir = tmp_path / "proj"
        index = {
            "version": 2, "sessions": {}, "failure_patterns": {},
            "learnings": [{"title": "tip", "category": "git", "description": "", "solution": ""}],
            "pending_learnings": [],
            "usage": {"skills": {}},  # usage present, learnings_shown absent
        }
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, _ = _capture(show_failures, index, "proj")
        assert "learnings_shown" in index["usage"]
        assert "git/tip" in index["usage"]["learnings_shown"]

    def test_prefers_fix_over_solution(self, tmp_path):
        """When both 'fix' and 'solution' are present, 'fix' is shown."""
        proj_dir = tmp_path / "proj"
        index = _make_index(learnings=[{
            "title": "Use SSH", "category": "git",
            "description": "HTTPS tokens expire",
            "solution": "git remote set-url origin git@github.com:org/repo.git",
            "fix": "Always use SSH remotes — they don't expire like HTTPS tokens.",
        }])
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "Always use SSH remotes" in output
        assert "git remote set-url" not in output

    def test_falls_back_to_solution_when_no_fix(self, tmp_path):
        """Without a 'fix' field, 'solution' is shown as the fix guidance."""
        proj_dir = tmp_path / "proj"
        index = _make_index(learnings=[{
            "title": "Use SSH", "category": "git",
            "description": "HTTPS tokens expire",
            "solution": "git remote set-url origin git@github.com:org/repo.git",
        }])
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "git remote set-url" in output

    def test_truncates_multiline_guidance_to_first_line(self, tmp_path):
        """Multi-line 'fix' is truncated to the first line with '...' suffix."""
        proj_dir = tmp_path / "proj"
        index = _make_index(learnings=[{
            "title": "Multi-step fix", "category": "git",
            "description": "Complex issue",
            "solution": "step one\nstep two\nstep three",
        }])
        _write_index(proj_dir, index)
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _, output = _capture(show_failures, index, "proj")
        assert "step one..." in output
        assert "step two" not in output
