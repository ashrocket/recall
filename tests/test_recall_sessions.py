#!/usr/bin/env python3
"""Tests for bin/recall-sessions.py."""

import importlib.util
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_recall_sessions():
    spec = importlib.util.spec_from_file_location(
        "recall_sessions",
        Path(__file__).resolve().parent.parent / "bin" / "recall-sessions.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_index(sessions=None, failure_patterns=None, learnings=None, usage=None):
    return {
        "version": 2,
        "sessions": sessions or {},
        "failure_patterns": failure_patterns or {},
        "learnings": learnings or [],
        "pending_learnings": [],
        "usage": usage or {"skills": {}, "learnings_shown": {}},
    }


def _capture(fn, *args, **kwargs):
    """Call fn and capture stdout, return (return_value, printed_text)."""
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        rv = fn(*args, **kwargs)
    return rv, buf.getvalue()


def _write_index(project_dir: Path, data: dict):
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "recall-index.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

class TestFormatDate:
    def test_formats_iso_string(self):
        mod = _import_recall_sessions()
        result = mod.format_date("2026-04-24T10:30:00")
        assert result == "2026-04-24 10:30"

    def test_formats_datetime_object(self):
        mod = _import_recall_sessions()
        dt = datetime(2026, 4, 24, 10, 30)
        result = mod.format_date(dt)
        assert result == "2026-04-24 10:30"

    def test_truncates_unrecognized_string(self):
        mod = _import_recall_sessions()
        result = mod.format_date("2026-04-24 10:30:00.123456+00:00 extra stuff")
        assert len(result) == 16

    def test_handles_z_suffix(self):
        mod = _import_recall_sessions()
        result = mod.format_date("2026-04-24T10:30:00Z")
        assert result == "2026-04-24 10:30"


# ---------------------------------------------------------------------------
# cleanup_noise_sessions
# ---------------------------------------------------------------------------

class TestCleanupNoiseSessions:
    def test_removes_low_message_sessions(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "noise1": {"message_count": 1, "failure_count": 0, "summary": "test"},
            "noise2": {"message_count": 2, "failure_count": 0, "summary": "short"},
            "good1": {"message_count": 5, "failure_count": 0, "summary": "real work"},
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.shared.get_session_details_dir", return_value=proj_dir / "recall-sessions"):
                _write_index(proj_dir, index)
                _, output = _capture(mod.cleanup_noise_sessions, index, "proj")
        assert "good1" in index["sessions"]
        assert "noise1" not in index["sessions"]
        assert "noise2" not in index["sessions"]
        assert "Removed 2" in output

    def test_keeps_sessions_with_failures(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "fail_session": {"message_count": 1, "failure_count": 2, "summary": "had failures"},
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.shared.get_session_details_dir", return_value=proj_dir / "recall-sessions"):
                _write_index(proj_dir, index)
                _, output = _capture(mod.cleanup_noise_sessions, index, "proj")
        assert "fail_session" in index["sessions"]
        assert "No low-value" in output

    def test_noop_when_all_sessions_useful(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "s1": {"message_count": 10, "failure_count": 0, "summary": "good"},
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.shared.get_session_details_dir", return_value=proj_dir / "recall-sessions"):
                _write_index(proj_dir, index)
                _, output = _capture(mod.cleanup_noise_sessions, index, "proj")
        assert "No low-value" in output


# ---------------------------------------------------------------------------
# cleanup_sensitive_sessions
# ---------------------------------------------------------------------------

class TestCleanupSensitiveSessions:
    def test_removes_session_with_sensitive_summary(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "safe1": {"message_count": 5, "failure_count": 0, "summary": "Add payment feature"},
            "sens1": {"message_count": 3, "failure_count": 0, "summary": "Set API_KEY= in env file"},
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.shared.get_session_details_dir", return_value=proj_dir / "recall-sessions"):
                with mock.patch("lib.shared.load_session_details", return_value=None):
                    _write_index(proj_dir, index)
                    _, output = _capture(mod.cleanup_sensitive_sessions, index, "proj")
        assert "safe1" in index["sessions"]
        assert "sens1" not in index["sessions"]
        assert "Removed 1" in output

    def test_noop_when_no_sensitive_data(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "s1": {"message_count": 5, "failure_count": 0, "summary": "Added login page"},
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.shared.get_session_details_dir", return_value=proj_dir / "recall-sessions"):
                with mock.patch("lib.shared.load_session_details", return_value=None):
                    _write_index(proj_dir, index)
                    _, output = _capture(mod.cleanup_sensitive_sessions, index, "proj")
        assert "No sessions with sensitive" in output


# ---------------------------------------------------------------------------
# cleanup_dedup_failures
# ---------------------------------------------------------------------------

class TestCleanupDedupFailures:
    def test_merges_duplicate_command_entries(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(failure_patterns={
            "git_error": [
                {"command": "git push origin main", "date": "2026-04-01", "count": 1},
                {"command": "git push origin main", "date": "2026-04-02", "count": 1},
                {"command": "git push origin feature", "date": "2026-04-03", "count": 1},
            ]
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _write_index(proj_dir, index)
            _, output = _capture(mod.cleanup_dedup_failures, index, "proj")
        remaining = index["failure_patterns"]["git_error"]
        # git push origin main should be merged into 1 entry
        commands = [e["command"] for e in remaining]
        assert commands.count("git push origin main") == 1
        assert "Deduplicated" in output

    def test_noop_when_no_duplicates(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(failure_patterns={
            "git_error": [
                {"command": "git push", "date": "2026-04-01"},
                {"command": "git pull", "date": "2026-04-02"},
            ]
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _write_index(proj_dir, index)
            _, output = _capture(mod.cleanup_dedup_failures, index, "proj")
        assert "No duplicate" in output

    def test_noop_with_empty_patterns(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index()
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _write_index(proj_dir, index)
            _, output = _capture(mod.cleanup_dedup_failures, index, "proj")
        assert "No duplicate" in output


# ---------------------------------------------------------------------------
# show_failures
# ---------------------------------------------------------------------------

class TestShowFailures:
    def test_shows_failure_patterns(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(failure_patterns={
            "git_error": [
                {"command": "git push", "date": "2026-04-01", "error": "fatal: denied"},
                {"command": "git push", "date": "2026-04-02", "error": "fatal: denied"},
            ],
        })
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _write_index(proj_dir, index)
            _, output = _capture(mod.show_failures, index, "proj")
        assert "Git Error" in output
        assert "git push" in output

    def test_shows_no_patterns_message_when_empty(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index()
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _write_index(proj_dir, index)
            _, output = _capture(mod.show_failures, index, "proj")
        assert "No failure patterns" in output

    def test_shows_learnings_before_patterns(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(
            failure_patterns={"git_error": [{"command": "git push", "date": "2026-04-01", "error": "fatal"}]},
            learnings=[{"title": "SSH tip", "category": "git", "description": "use SSH", "solution": "git@"}],
        )
        proj_dir = tmp_path / "proj"
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            _write_index(proj_dir, index)
            _, output = _capture(mod.show_failures, index, "proj")
        # Learnings section should appear
        assert "SSH tip" in output
        # Failures should also appear
        assert "git push" in output
        # Learnings should appear before failures in output
        assert output.index("SSH tip") < output.index("git push")


# ---------------------------------------------------------------------------
# show_knowledge
# ---------------------------------------------------------------------------

class TestShowKnowledge:
    def _mock_knowledge(self, learnings, global_path="/home/.claude/CLAUDE.md", project_path=None):
        """Build a sys.modules mock for the knowledge module."""
        import unittest.mock as m
        mk = m.MagicMock()
        mk.get_learnings.return_value = learnings
        mk.GLOBAL_CLAUDE_MD = global_path
        mk.get_project_claude_md.return_value = project_path
        return mk

    def test_shows_header_and_paths(self):
        mod = _import_recall_sessions()
        mk = self._mock_knowledge([])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _, output = _capture(mod.show_knowledge, "proj")
        assert "## Current Knowledge" in output
        assert "Global" in output

    def test_empty_learnings_shows_empty_message(self):
        mod = _import_recall_sessions()
        mk = self._mock_knowledge([])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _, output = _capture(mod.show_knowledge, "proj")
        assert "No knowledge loaded yet" in output

    def test_groups_learnings_by_category(self):
        mod = _import_recall_sessions()
        mk = self._mock_knowledge([
            {"category": "git", "title": "SSH tip", "solution": "git@github.com"},
            {"category": "python", "title": "venv tip", "solution": "python -m venv"},
        ])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _, output = _capture(mod.show_knowledge, "proj")
        assert "### git" in output
        assert "SSH tip" in output
        assert "### python" in output
        assert "venv tip" in output

    def test_prefers_fix_over_solution(self):
        mod = _import_recall_sessions()
        mk = self._mock_knowledge([{
            "category": "git", "title": "Use SSH",
            "solution": "git remote set-url origin git@github.com:org/repo.git",
            "fix": "Always use SSH remotes — they don't expire.",
        }])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _, output = _capture(mod.show_knowledge, "proj")
        assert "Always use SSH remotes" in output
        assert "git remote set-url" not in output

    def test_truncates_multiline_guidance(self):
        mod = _import_recall_sessions()
        mk = self._mock_knowledge([{
            "category": "ci", "title": "Multi-step fix",
            "solution": "step one\nstep two\nstep three",
        }])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _, output = _capture(mod.show_knowledge, "proj")
        assert "step one..." in output
        assert "step two" not in output

    def test_passes_project_folder_to_get_learnings(self):
        """show_knowledge must pass its project_folder arg to get_learnings."""
        mod = _import_recall_sessions()
        mk = self._mock_knowledge([])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _capture(mod.show_knowledge, "-Users-test-myproject")
        mk.get_learnings.assert_called_once_with("-Users-test-myproject")

    def test_non_dict_learnings_skipped(self):
        mod = _import_recall_sessions()
        mk = self._mock_knowledge(["plain string learning"])
        with mock.patch.dict("sys.modules", {"knowledge": mk}):
            _, output = _capture(mod.show_knowledge, "proj")
        # Non-dict learnings don't crash and the empty message shows
        assert "No knowledge loaded yet" in output


# ---------------------------------------------------------------------------
# show_stats
# ---------------------------------------------------------------------------

class TestShowStats:
    def test_shows_skill_usage(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(usage={
            "skills": {
                "recall": {"count": 5, "sessions": ["s1", "s2"], "last_used": "2026-04-01"},
            },
            "learnings_shown": {}
        })
        proj_dir = tmp_path / "proj"
        _, output = _capture(mod.show_stats, index, "proj")
        assert "recall" in output
        assert "5 uses" in output

    def test_shows_no_skills_message(self):
        mod = _import_recall_sessions()
        index = _make_index()
        _, output = _capture(mod.show_stats, index, "proj")
        assert "No skill usage" in output

    def test_shows_unused_learnings(self):
        mod = _import_recall_sessions()
        index = _make_index(
            learnings=[{"category": "git", "title": "SSH tip"}],
            usage={"skills": {}, "learnings_shown": {}}  # SSH tip never shown
        )
        _, output = _capture(mod.show_stats, index, "proj")
        assert "Unused Learnings" in output
        assert "git/SSH tip" in output


# ---------------------------------------------------------------------------
# export_index / import_index (roundtrip)
# ---------------------------------------------------------------------------

class TestExportImportIndex:
    def test_export_creates_file_with_metadata(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={"s1": {"date": "2026-04-01", "summary": "test"}})
        export_file = tmp_path / "backup.json"
        with mock.patch("sys.stdout", io.StringIO()):
            mod.export_index(index, "proj", str(export_file))
        assert export_file.exists()
        data = json.loads(export_file.read_text())
        assert "exported_at" in data
        assert "index" in data
        assert "sessions" in data["index"]

    def test_export_reports_counts(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(
            sessions={"s1": {}, "s2": {}},
            learnings=[{"title": "a"}],
        )
        export_file = tmp_path / "backup.json"
        _, output = _capture(mod.export_index, index, "proj", str(export_file))
        assert "2 sessions" in output
        assert "1 learnings" in output

    def test_import_restores_wrapped_export(self, tmp_path):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        original_index = _make_index(sessions={"s1": {"date": "2026-04-01", "summary": "test"}})
        export_file = tmp_path / "backup.json"
        export_file.write_text(json.dumps({
            "exported_at": "2026-04-24T12:00:00",
            "project_folder": "proj",
            "index": original_index
        }))
        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir):
            with mock.patch("lib.shared.get_index_path", return_value=proj_dir / "recall-index.json"):
                _write_index(proj_dir, _make_index())
                with mock.patch("sys.stdout", io.StringIO()):
                    mod.import_index("proj", str(export_file))
        saved = json.loads((proj_dir / "recall-index.json").read_text())
        assert "s1" in saved["sessions"]

    def test_import_reports_error_for_missing_file(self, tmp_path):
        mod = _import_recall_sessions()
        _, output = _capture(mod.import_index, "proj", str(tmp_path / "nonexistent.json"))
        assert "Error" in output or "not found" in output.lower()

    def test_export_noop_with_empty_index(self):
        mod = _import_recall_sessions()
        _, output = _capture(mod.export_index, {}, "proj")
        assert "No index to export" in output

    def test_export_uses_relative_path_from_cwd(self, tmp_path):
        mod = _import_recall_sessions()
        index = _make_index(sessions={"s1": {}})
        with mock.patch.object(mod.Path, "cwd", return_value=tmp_path):
            _, _ = _capture(mod.export_index, index, "proj", "backup.json")
        assert (tmp_path / "backup.json").exists()

    def test_export_generates_default_timestamped_filename(self, tmp_path):
        """export_index with no export_path writes a recall-backup-*.json in cwd."""
        mod = _import_recall_sessions()
        index = _make_index(sessions={"s1": {}})
        with mock.patch.object(mod.Path, "cwd", return_value=tmp_path):
            _, output = _capture(mod.export_index, index, "proj")
        backups = list(tmp_path.glob("recall-backup-*.json"))
        assert len(backups) == 1


# ---------------------------------------------------------------------------
# parse_session (fallback JSONL parser)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _matches_terms (multi-term AND search helper)
# ---------------------------------------------------------------------------

class TestMatchesTerms:
    def test_single_term_matches(self):
        mod = _import_recall_sessions()
        assert mod._matches_terms("fix authentication middleware", ["auth"]) is True

    def test_single_term_no_match(self):
        mod = _import_recall_sessions()
        assert mod._matches_terms("unrelated content here", ["auth"]) is False

    def test_multi_term_all_present(self):
        mod = _import_recall_sessions()
        assert mod._matches_terms("fix JWT authentication token", ["jwt", "auth"]) is True

    def test_multi_term_partial_match_returns_false(self):
        mod = _import_recall_sessions()
        assert mod._matches_terms("fix JWT token", ["jwt", "auth"]) is False

    def test_case_insensitive(self):
        mod = _import_recall_sessions()
        assert mod._matches_terms("Fix AuthService bug", ["authservice"]) is True

    def test_empty_terms_always_matches(self):
        mod = _import_recall_sessions()
        # split("") gives [""] in Python, but split() on empty string gives []
        # _matches_terms with empty list = all() on empty = True
        assert mod._matches_terms("anything", []) is True


class TestParseSession:
    def test_extracts_user_messages(self, tmp_path):
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        session.write_text(json.dumps(
            {"type": "user", "message": {"content": "fix the payment bug"}}
        ))
        result = mod.parse_session(session)
        assert len(result["user_messages"]) == 1
        assert "payment" in result["user_messages"][0]

    def test_finds_search_matches(self, tmp_path):
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"content": "fix auth"}}),
            json.dumps({"type": "user", "message": {"content": "update authentication middleware"}}),
        ]
        session.write_text("\n".join(lines))
        result = mod.parse_session(session, search_term="authentication")
        assert len(result["matches"]) == 1
        assert "authentication" in result["matches"][0]

    def test_no_matches_when_term_absent(self, tmp_path):
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        session.write_text(json.dumps({"type": "user", "message": {"content": "fix the bug"}}))
        result = mod.parse_session(session, search_term="authentication")
        assert result["matches"] == []

    def test_multi_term_and_search_requires_all_terms(self, tmp_path):
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"content": "fix JWT token validation"}}),
            json.dumps({"type": "user", "message": {"content": "update the auth middleware"}}),
        ]
        session.write_text("\n".join(lines))
        # Both terms must be present in same message
        result = mod.parse_session(session, search_term="jwt validation")
        assert len(result["matches"]) == 1
        assert "JWT" in result["matches"][0]
        # "jwt" appears in first message but "middleware" only in second → no match
        result2 = mod.parse_session(session, search_term="jwt middleware")
        assert result2["matches"] == []

    def test_skips_angle_bracket_messages(self, tmp_path):
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        lines = [
            json.dumps({"type": "user", "message": {"content": "<system>injected context</system>"}}),
            json.dumps({"type": "user", "message": {"content": "real message"}}),
        ]
        session.write_text("\n".join(lines))
        result = mod.parse_session(session)
        assert len(result["user_messages"]) == 1
        assert result["user_messages"][0] == "real message"

    def test_stores_error_when_file_cannot_be_read(self, tmp_path):
        """Outer except stores error string in result['error'] without crashing."""
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        session.write_text("")  # exists so stat() succeeds
        with mock.patch("builtins.open", side_effect=IOError("permission denied")):
            result = mod.parse_session(session)
        assert "permission denied" in result.get("error", "")


# ---------------------------------------------------------------------------
# --json flag output
# ---------------------------------------------------------------------------

class TestJsonFlag:
    def test_list_json_returns_sessions_array(self, tmp_path):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        index = {
            "version": 2,
            "sessions": {
                "s1": {"date": "2026-04-24T10:00:00", "summary": "session one",
                       "message_count": 3, "failure_count": 0, "topics": []},
            },
            "failure_patterns": {},
            "learnings": [],
            "pending_learnings": [],
            "usage": {"skills": {}, "learnings_shown": {}},
        }
        _write_index(proj_dir, index)

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("sys.argv", ["recall-sessions.py", str(proj_dir.parent), "--json"]):
            _, output = _capture(mod.main)

        data = json.loads(output.strip())
        assert "sessions" in data
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "s1"
        assert data["sessions"][0]["summary"] == "session one"

    def test_list_subcommand_json_returns_sessions_array(self, tmp_path):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        index = {
            "version": 2,
            "sessions": {
                "s1": {"date": "2026-04-24T10:00:00", "summary": "session one",
                       "message_count": 3, "failure_count": 0, "topics": []},
            },
            "failure_patterns": {},
            "learnings": [],
            "pending_learnings": [],
            "usage": {"skills": {}, "learnings_shown": {}},
        }
        _write_index(proj_dir, index)

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("sys.argv", ["recall-sessions.py", str(proj_dir.parent), "list", "--json"]):
            _, output = _capture(mod.main)

        data = json.loads(output.strip())
        assert "sessions" in data
        assert data["sessions"][0]["id"] == "s1"

    def test_failures_json_returns_patterns(self, tmp_path):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        index = {
            "version": 2,
            "sessions": {},
            "failure_patterns": {"git_error": [{"command": "git push", "error": "denied"}]},
            "learnings": [],
            "pending_learnings": [],
            "usage": {"skills": {}, "learnings_shown": {}},
        }
        _write_index(proj_dir, index)

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("sys.argv", ["recall-sessions.py", str(proj_dir.parent), "failures", "--json"]):
            _, output = _capture(mod.main)

        data = json.loads(output.strip())
        assert "failure_patterns" in data
        assert "git_error" in data["failure_patterns"]

    def test_search_json_returns_matches(self, tmp_path):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        index = {
            "version": 2,
            "sessions": {
                "s1": {"date": "2026-04-24T10:00:00", "summary": "fix payment gateway",
                       "message_count": 3, "failure_count": 0, "topics": []},
                "s2": {"date": "2026-04-23T10:00:00", "summary": "update login page",
                       "message_count": 2, "failure_count": 0, "topics": []},
            },
            "failure_patterns": {},
            "learnings": [],
            "pending_learnings": [],
            "usage": {"skills": {}, "learnings_shown": {}},
        }
        _write_index(proj_dir, index)

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("sys.argv", ["recall-sessions.py", str(proj_dir.parent), "payment", "--json"]):
            _, output = _capture(mod.main)

        data = json.loads(output.strip())
        assert "matches" in data
        assert data["search_term"] == "payment"
        assert len(data["matches"]) == 1
        assert "payment" in data["matches"][0]["summary"]


# ---------------------------------------------------------------------------
# find_session_files
# ---------------------------------------------------------------------------

class TestFindSessionFiles:
    def test_returns_jsonl_files_excluding_agent_prefix(self, tmp_path):
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        session = project_dir / "session-abc.jsonl"
        agent = project_dir / "agent-xyz.jsonl"
        session.write_text("{}")
        agent.write_text("{}")

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_session_files("proj")

        assert session in result
        assert agent not in result

    def test_sorted_newest_first(self, tmp_path):
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        import os
        f1 = project_dir / "session1.jsonl"
        f2 = project_dir / "session2.jsonl"
        f1.write_text("{}")
        f2.write_text("{}")
        os.utime(f1, (1000, 1000))
        os.utime(f2, (2000, 2000))

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_session_files("proj")

        assert result[0] == f2  # newest first

    def test_returns_empty_when_dir_missing(self, tmp_path):
        mod = _import_recall_sessions()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_session_files("nonexistent")
        assert result == []


# ---------------------------------------------------------------------------
# cleanup_jsonl_files
# ---------------------------------------------------------------------------

class TestCleanupJsonlFiles:
    def _touch_old(self, path: Path, days_old: int):
        path.write_text("{}")
        import os, time
        from datetime import timedelta
        ts = time.time() - timedelta(days=days_old).total_seconds()
        os.utime(path, (ts, ts))

    def test_keeps_5_most_recent_sessions(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        import os, time
        from datetime import timedelta
        for i in range(8):
            f = project_dir / f"session{i:02d}.jsonl"
            self._touch_old(f, days_old=40)
            ts = time.time() - timedelta(days=40).total_seconds() + i * 100
            os.utime(f, (ts, ts))

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_jsonl_files("proj")

        remaining = list(project_dir.glob("session*.jsonl"))
        assert len(remaining) == 5

    def test_removes_old_agent_files(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        agent_file = project_dir / "agent-old.jsonl"
        self._touch_old(agent_file, days_old=10)

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_jsonl_files("proj")

        assert not agent_file.exists()

    def test_keeps_recent_agent_files(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        agent_file = project_dir / "agent-new.jsonl"
        self._touch_old(agent_file, days_old=2)  # under 7-day limit

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_jsonl_files("proj")

        assert agent_file.exists()

    def test_prints_no_old_files_message_when_nothing_freed(self, tmp_path, capsys):
        """When no files are removed, prints 'No old .jsonl files to remove'."""
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        # Create a recent session file (1 day old — well within 30-day limit)
        recent = project_dir / "session.jsonl"
        self._touch_old(recent, days_old=1)

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_jsonl_files("proj")

        out = capsys.readouterr().out
        assert "No old" in out

    def test_stat_exception_on_old_session_file_is_swallowed(self, tmp_path, capsys):
        """OSError on f.stat() inside cleanup loop is caught and skipped."""
        mod = _import_recall_sessions()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)

        # 5 real session files (kept), plus a bad mock that will raise on stat
        real_files = []
        for i in range(5):
            f = project_dir / f"session{i:02d}.jsonl"
            f.write_text("{}")
            real_files.append(f)

        bad_path = mock.MagicMock(spec=Path)
        bad_path.stat.side_effect = OSError("file gone")
        bad_path.name = "old-session.jsonl"

        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "find_session_files", return_value=real_files + [bad_path]):
            mod.cleanup_jsonl_files("proj")

        out = capsys.readouterr().out
        assert "No old" in out


# ---------------------------------------------------------------------------
# list_all_project_indices
# ---------------------------------------------------------------------------

class TestListAllProjectIndices:
    def test_finds_projects_with_index(self, tmp_path):
        mod = _import_recall_sessions()
        projects_dir = tmp_path / ".claude" / "projects"
        proj_a = projects_dir / "proj-a"
        proj_b = projects_dir / "proj-b"
        proj_a.mkdir(parents=True)
        proj_b.mkdir(parents=True)
        (proj_a / "recall-index.json").write_text("{}")
        # proj_b has no index — should be excluded

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.list_all_project_indices()

        assert "proj-a" in result
        assert "proj-b" not in result

    def test_returns_empty_when_no_projects_dir(self, tmp_path):
        mod = _import_recall_sessions()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.list_all_project_indices()
        assert result == []

    def test_ignores_non_directory_entries(self, tmp_path):
        mod = _import_recall_sessions()
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)
        # A plain file, not a directory
        (projects_dir / "not-a-dir.json").write_text("{}")

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.list_all_project_indices()

        assert result == []


# ---------------------------------------------------------------------------
# search_sessions
# ---------------------------------------------------------------------------

class TestSearchSessions:
    def test_finds_match_in_index_summary(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "fixed the payment gateway timeout", "date": "2026-04-24T10:00:00"},
        })

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.search_sessions("payment", index, [], "proj")

        out = capsys.readouterr().out
        assert "payment" in out.lower()

    def test_literal_search_strips_outer_quotes(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "rotated App Store Connect AuthKey_12345.p8", "date": "2026-04-24T10:00:00"},
        })

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.search_sessions("'.p8'", index, [], "proj")

        out = capsys.readouterr().out
        assert "AuthKey_12345.p8" in out

    def test_literal_search_ignores_question_mark_term(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "fixed sops config loading", "date": "2026-04-24T10:00:00"},
        })

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.search_sessions("sops ?", index, [], "proj")

        out = capsys.readouterr().out
        assert "sops" in out.lower()

    def test_regex_search_matches_session_details(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [],
            "commands": [{"command": "ls keys/AuthKey_12345.p8"}],
            "failures": [],
            "skills_used": [],
        }

        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions(r"/.*\.p8/", index, [], "proj")

        out = capsys.readouterr().out
        assert "cmd:" in out
        assert "AuthKey_12345.p8" in out

    def test_bare_star_regex_search_matches_session_details(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [],
            "commands": [{"command": "ls keys/AuthKey_12345.p8"}],
            "failures": [],
            "skills_used": [],
        }

        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions(r"/*\.p8/", index, [], "proj")

        out = capsys.readouterr().out
        assert "cmd:" in out
        assert "AuthKey_12345.p8" in out

    def test_invalid_regex_search_does_not_crash_or_global_fallback(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={})

        with mock.patch.object(mod, "list_all_project_indices") as mock_projects:
            mod.search_sessions("/[/", index, [], "proj")

        out = capsys.readouterr().out
        assert "Invalid regex search" in out
        mock_projects.assert_not_called()

    def test_no_matches_produces_output(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "refactor auth module", "date": "2026-04-24T10:00:00"},
        })

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.search_sessions("kubernetes", index, [], "proj")

        out = capsys.readouterr().out
        assert "kubernetes" in out  # search term echoed

    def test_finds_match_in_session_details(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [{"content": "debug the database migration failure"}],
            "commands": [],
            "failures": [],
            "skills_used": [],
        }

        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions("database migration", index, [], "proj")

        out = capsys.readouterr().out
        assert "msg:" in out

    def test_collect_search_results_ranks_matching_details(self):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-old": {"summary": "misc", "date": "2026-04-23T10:00:00"},
            "sess-new": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })

        def _details(_project, session_id):
            if session_id == "sess-old":
                return {"user_messages": [{"content": "payment"}], "commands": [], "failures": [], "skills_used": []}
            return {"user_messages": [{"content": "fix payment gateway timeout"}], "commands": [], "failures": [], "skills_used": []}

        with mock.patch.object(mod, "load_session_details", side_effect=_details):
            results = mod.collect_search_results("payment gateway", index, "proj")

        assert results[0]["id"] == "sess-new"
        assert results[0]["source"] == "msg"
        assert "score" in results[0]

    def test_finds_match_in_failure_patterns(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(
            sessions={},
            failure_patterns={
                "permission_denied": [
                    {"command": "docker run --privileged", "error": "permission denied"},
                ]
            }
        )

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.search_sessions("docker", index, [], "proj")

        out = capsys.readouterr().out
        assert "docker" in out

    def test_empty_index_produces_no_crash(self, capsys):
        mod = _import_recall_sessions()
        mod.search_sessions("anything", {}, [], "proj")
        out = capsys.readouterr().out
        assert "anything" in out

    def test_finds_match_in_commands(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [],
            "commands": [{"command": "pytest --cov tests/"}],
            "failures": [],
            "skills_used": [],
        }
        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions("pytest", index, [], "proj")
        out = capsys.readouterr().out
        assert "cmd:" in out

    def test_finds_match_in_failures(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [],
            "commands": [],
            "failures": [{"command": "git rebase", "error": "merge conflict in README"}],
            "skills_used": [],
        }
        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions("merge conflict", index, [], "proj")
        out = capsys.readouterr().out
        assert "fail:" in out

    def test_finds_match_in_skills(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [],
            "commands": [],
            "failures": [],
            "skills_used": [{"skill": "plugin:recall-failures"}],
        }
        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions("recall", index, [], "proj")
        out = capsys.readouterr().out
        assert "skill:" in out

    def test_truncates_at_five_matches(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "misc", "date": "2026-04-24T10:00:00"},
        })
        details = {
            "user_messages": [{"content": f"fix auth bug number {i}"} for i in range(8)],
            "commands": [],
            "failures": [],
            "skills_used": [],
        }
        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.search_sessions("auth", index, [], "proj")
        out = capsys.readouterr().out
        assert out.count("msg:") <= mod.SEARCH_RESULT_LIMIT

    def test_no_other_projects_message(self, capsys):
        """When no local match and no other projects, prints 'No other projects'."""
        mod = _import_recall_sessions()
        # index with no session matching
        index = _make_index(sessions={
            "s1": {"summary": "unrelated", "date": "2026-04-24T10:00:00"},
        })
        with mock.patch.object(mod, "load_session_details", return_value=None), \
             mock.patch.object(mod, "list_all_project_indices", return_value=["proj"]):
            mod.search_sessions("kubernetes", index, [], "proj")
        out = capsys.readouterr().out
        assert "No other projects" in out

    def test_failure_pattern_match_shows_header_when_no_session_match(self, capsys):
        """'In Failure Patterns:' header appears only when no session match precedes it."""
        mod = _import_recall_sessions()
        index = _make_index(
            sessions={"s1": {"summary": "unrelated", "date": "2026-04-24T10:00:00"}},
            failure_patterns={"git_error": [{"command": "git rebase", "error": "merge conflict"}]},
        )
        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.search_sessions("merge conflict", index, [], "proj")
        out = capsys.readouterr().out
        assert "Failure Patterns" in out
        assert "git rebase" in out

    def test_cross_project_match_displayed(self, capsys):
        """Matches found in other projects are displayed."""
        mod = _import_recall_sessions()
        index = _make_index(sessions={})
        other_index = _make_index(sessions={
            "s99": {"summary": "fix kubernetes deployment", "date": "2026-04-24T09:00:00"},
        })
        with mock.patch.object(mod, "load_session_details", return_value=None), \
             mock.patch.object(mod, "list_all_project_indices", return_value=["proj", "other-proj"]), \
             mock.patch.object(mod, "load_index", return_value=other_index):
            mod.search_sessions("kubernetes", index, [], "proj")
        out = capsys.readouterr().out
        assert "other project" in out.lower() or "kubernetes" in out

    def test_cross_project_nodash_name_shown_as_is(self, capsys):
        """Cross-project match with no-dash project name uses the name as-is."""
        mod = _import_recall_sessions()
        index = _make_index(sessions={})
        other_index = _make_index(sessions={
            "s1": {"summary": "deploy kubernetes", "date": "2026-04-24T09:00:00"},
        })
        with mock.patch.object(mod, "load_session_details", return_value=None), \
             mock.patch.object(mod, "list_all_project_indices", return_value=["proj", "nodashname"]), \
             mock.patch.object(mod, "load_index", return_value=other_index):
            mod.search_sessions("kubernetes", index, [], "proj")
        out = capsys.readouterr().out
        assert "nodashname" in out

    def test_cross_project_shows_and_more_when_over_three_matches(self, capsys):
        """When a project has > 3 matches, '... and N more' is shown."""
        mod = _import_recall_sessions()
        index = _make_index(sessions={})
        other_index = _make_index(sessions={
            f"s{i}": {"summary": f"kubernetes deploy {i}", "date": f"2026-04-24T0{i}:00:00"}
            for i in range(5)
        })
        with mock.patch.object(mod, "load_session_details", return_value=None), \
             mock.patch.object(mod, "list_all_project_indices", return_value=["proj", "other-proj"]), \
             mock.patch.object(mod, "load_index", return_value=other_index):
            mod.search_sessions("kubernetes", index, [], "proj")
        out = capsys.readouterr().out
        assert "more" in out


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_lists_from_index_newest_first(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-old": {"summary": "old task", "date": "2026-04-20T10:00:00", "message_count": 5, "failure_count": 0},
            "sess-new": {"summary": "new task", "date": "2026-04-24T10:00:00", "message_count": 3, "failure_count": 1},
        })
        mod.list_sessions(index, [], "proj")
        out = capsys.readouterr().out
        assert "new task" in out
        # (current) should be next to the newest session
        assert "(current)" in out

    def test_marks_first_entry_as_current(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-001": {"summary": "latest", "date": "2026-04-24T12:00:00", "message_count": 1, "failure_count": 0},
        })
        mod.list_sessions(index, [], "proj")
        out = capsys.readouterr().out
        assert "(current)" in out

    def test_empty_index_produces_header(self, capsys):
        mod = _import_recall_sessions()
        mod.list_sessions({}, [], "proj")
        out = capsys.readouterr().out
        assert "Recent Sessions" in out

    def test_falls_back_to_jsonl_when_no_index(self, capsys, tmp_path):
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        import json as _json
        session.write_text(_json.dumps({"type": "user", "message": {"content": "fix the login redirect"}}))
        mod.list_sessions({}, [session], "proj")
        out = capsys.readouterr().out
        assert "login redirect" in out

    def test_jsonl_long_message_truncated_with_ellipsis(self, capsys, tmp_path):
        """JSONL fallback truncates messages longer than 150 chars with '...'."""
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        import json as _json
        long_msg = "x" * 200
        session.write_text(_json.dumps({"type": "user", "message": {"content": long_msg}}))
        mod.list_sessions({}, [session], "proj")
        out = capsys.readouterr().out
        assert "..." in out

    def test_jsonl_short_messages_show_no_user_messages_found(self, capsys, tmp_path):
        """JSONL fallback uses 'No user messages found' when all messages are <= 20 chars."""
        mod = _import_recall_sessions()
        session = tmp_path / "abc123.jsonl"
        import json as _json
        session.write_text(_json.dumps({"type": "user", "message": {"content": "short"}}) + "\n")
        mod.list_sessions({}, [session], "proj")
        out = capsys.readouterr().out
        assert "No user messages found" in out


# ---------------------------------------------------------------------------
# show_last_session
# ---------------------------------------------------------------------------

class TestShowLastSession:
    def test_shows_previous_session_from_index(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-current": {"summary": "current work", "date": "2026-04-24T12:00:00", "message_count": 3, "command_count": 2, "failure_count": 0},
            "sess-prev": {"summary": "previous work", "date": "2026-04-23T10:00:00", "message_count": 5, "command_count": 3, "failure_count": 1},
        })

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.show_last_session(index, [], "proj")

        out = capsys.readouterr().out
        assert "Previous Session" in out
        assert "previous work" in out  # the index summary fallback

    def test_shows_details_when_available(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-a": {"summary": "current", "date": "2026-04-24T12:00:00", "message_count": 1, "command_count": 0, "failure_count": 0},
            "sess-b": {"summary": "prev", "date": "2026-04-23T10:00:00", "message_count": 2, "command_count": 0, "failure_count": 0},
        })
        details = {
            "user_messages": [{"content": "implement oauth2 flow"}],
            "failures": [],
        }

        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.show_last_session(index, [], "proj")

        out = capsys.readouterr().out
        assert "oauth2" in out

    def test_shows_failures_from_details(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-a": {"summary": "current", "date": "2026-04-24T12:00:00", "message_count": 1, "command_count": 0, "failure_count": 1},
            "sess-b": {"summary": "prev", "date": "2026-04-23T10:00:00", "message_count": 2, "command_count": 0, "failure_count": 1},
        })
        details = {
            "user_messages": [],
            "failures": [{"command": "pytest tests/", "error": "ModuleNotFoundError: no module named foo"}],
        }

        with mock.patch.object(mod, "load_session_details", return_value=details):
            mod.show_last_session(index, [], "proj")

        out = capsys.readouterr().out
        assert "Failures" in out
        assert "ModuleNotFoundError" in out

    def test_prints_not_found_when_only_one_session(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={
            "sess-only": {"summary": "only session", "date": "2026-04-24T12:00:00", "message_count": 1, "command_count": 0, "failure_count": 0},
        })

        with mock.patch.object(mod, "load_session_details", return_value=None):
            mod.show_last_session(index, [], "proj")

        out = capsys.readouterr().out
        assert "No previous session" in out

    def test_falls_back_to_jsonl_when_no_index(self, capsys, tmp_path):
        """show_last_session parses JSONL when index is empty and 2+ session files exist."""
        import json as _json
        mod = _import_recall_sessions()

        s1 = tmp_path / "current.jsonl"
        s2 = tmp_path / "prev.jsonl"
        s1.write_text(_json.dumps({"type": "user", "message": {"content": "current work"}}) + "\n")
        s2.write_text(_json.dumps({"type": "user", "message": {"content": "previous work recover the database"}}) + "\n")

        mod.show_last_session({}, [s1, s2], "proj")
        out = capsys.readouterr().out
        assert "Previous Session" in out


# ---------------------------------------------------------------------------
# reset_index
# ---------------------------------------------------------------------------

class TestResetIndex:
    def test_saves_empty_index(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        index = _make_index(sessions={"s1": {"summary": "old work"}})
        # get_index_path returns a path that doesn't exist (so backup is skipped)
        with mock.patch.object(mod, "get_index_path", return_value=tmp_path / "recall-index.json"), \
             mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            mod.reset_index(index, "proj")

        import json
        saved = json.loads((tmp_path / "recall-index.json").read_text())
        assert saved["sessions"] == {}
        assert saved["version"] == 2

    def test_prints_confirmation(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        with mock.patch.object(mod, "get_index_path", return_value=tmp_path / "recall-index.json"), \
             mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            mod.reset_index({}, "proj")
        out = capsys.readouterr().out
        assert "Reset" in out

    def test_skips_backup_when_no_existing_file(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        non_existent = tmp_path / "missing-index.json"
        with mock.patch.object(mod, "get_index_path", return_value=non_existent), \
             mock.patch("lib.shared.get_project_dir", return_value=tmp_path), \
             mock.patch.object(mod, "export_index") as mock_export:
            mod.reset_index({"sessions": {"x": {}}}, "proj")
        # export_index should NOT be called because the file doesn't exist
        mock_export.assert_not_called()


# ---------------------------------------------------------------------------
# show_cleanup_analysis — dispatch logic
# ---------------------------------------------------------------------------

class TestShowCleanupAnalysis:
    def test_noise_action_calls_cleanup_noise(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        with mock.patch.object(mod, "cleanup_noise_sessions") as mock_noise:
            mod.show_cleanup_analysis(index, [], "proj", action="noise")
        mock_noise.assert_called_once()

    def test_sensitive_action_calls_cleanup_sensitive(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        with mock.patch.object(mod, "cleanup_sensitive_sessions") as mock_sens:
            mod.show_cleanup_analysis(index, [], "proj", action="sensitive")
        mock_sens.assert_called_once()

    def test_dedup_action_calls_cleanup_dedup(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        with mock.patch.object(mod, "cleanup_dedup_failures") as mock_dedup:
            mod.show_cleanup_analysis(index, [], "proj", action="dedup")
        mock_dedup.assert_called_once()

    def test_execute_action_calls_all_cleanups(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        with mock.patch.object(mod, "cleanup_sensitive_sessions") as mock_sens, \
             mock.patch.object(mod, "cleanup_noise_sessions") as mock_noise, \
             mock.patch.object(mod, "cleanup_dedup_failures") as mock_dedup, \
             mock.patch.object(mod, "cleanup_jsonl_files") as mock_jsonl:
            mod.show_cleanup_analysis(index, [], "proj", action="execute")
        mock_sens.assert_called_once()
        mock_noise.assert_called_once()
        mock_dedup.assert_called_once()
        mock_jsonl.assert_called_once()

    def test_all_alias_for_execute(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        with mock.patch.object(mod, "cleanup_sensitive_sessions"), \
             mock.patch.object(mod, "cleanup_noise_sessions"), \
             mock.patch.object(mod, "cleanup_dedup_failures"), \
             mock.patch.object(mod, "cleanup_jsonl_files"):
            mod.show_cleanup_analysis(index, [], "proj", action="all")
        out = capsys.readouterr().out
        assert "Running all cleanup actions" in out

    def test_dry_run_shows_analysis(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        mod.show_cleanup_analysis(index, [], "proj", action="dry-run")
        out = capsys.readouterr().out
        assert "Analysis" in out

    def test_no_action_shows_analysis(self, capsys):
        mod = _import_recall_sessions()
        index = _make_index()
        mod.show_cleanup_analysis(index, [], "proj")
        out = capsys.readouterr().out
        assert "Analysis" in out

    def test_empty_index_shows_nothing_to_clean(self, capsys):
        mod = _import_recall_sessions()
        mod.show_cleanup_analysis({}, [], "proj")
        out = capsys.readouterr().out
        assert "Nothing to clean" in out

    def test_more_than_five_noise_sessions_truncated(self, capsys):
        mod = _import_recall_sessions()
        sessions = {f"s{i:02d}": {"message_count": 1, "failure_count": 0, "summary": f"noise {i}"} for i in range(8)}
        index = _make_index(sessions=sessions)
        mod.show_cleanup_analysis(index, [], "proj")
        out = capsys.readouterr().out
        assert "more" in out

    def test_shows_sensitive_sessions(self, capsys):
        """Sessions with sensitive keywords appear in the sensitive data section."""
        mod = _import_recall_sessions()
        sessions = {
            "sensitive-abc": {"message_count": 5, "failure_count": 0, "summary": "API_KEY= was leaked", "date": "2026-04-24T10:00:00"},
        }
        index = _make_index(sessions=sessions)
        mod.show_cleanup_analysis(index, [], "proj")
        out = capsys.readouterr().out
        assert "sensitive data" in out.lower()
        assert "sensitiv" in out  # sid[:8] of "sensitive-abc"

    def test_shows_duplicate_failure_count(self, capsys):
        """Duplicate failure entries are counted and reported."""
        mod = _import_recall_sessions()
        dup_cmd = "git push"
        index = _make_index(failure_patterns={
            "git_error": [
                {"command": dup_cmd, "error": "denied"},
                {"command": dup_cmd, "error": "denied again"},  # same command = duplicate
            ]
        })
        mod.show_cleanup_analysis(index, [], "proj")
        out = capsys.readouterr().out
        assert "duplicate" in out.lower()

    def test_jsonl_action_calls_cleanup_jsonl(self, capsys):
        """action='jsonl' dispatches only to cleanup_jsonl_files."""
        mod = _import_recall_sessions()
        index = _make_index()
        with mock.patch.object(mod, "cleanup_jsonl_files") as mock_jsonl:
            mod.show_cleanup_analysis(index, [], "proj", action="jsonl")
        mock_jsonl.assert_called_once()


# ---------------------------------------------------------------------------
# import_index — additional edge cases
# ---------------------------------------------------------------------------

class TestImportIndexEdgeCases:
    def test_import_direct_format_index(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        # Direct index (no 'exported_at' wrapper)
        direct_index = _make_index(sessions={"sess-direct": {"date": "2026-04-24", "summary": "direct"}})
        import_file = tmp_path / "direct.json"
        import_file.write_text(json.dumps(direct_index))

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("lib.shared.get_index_path", return_value=proj_dir / "recall-index.json"):
            proj_dir.mkdir(parents=True)
            mod.import_index("proj", str(import_file))

        saved = json.loads((proj_dir / "recall-index.json").read_text())
        assert "sess-direct" in saved["sessions"]

    def test_import_handles_corrupt_json(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{not valid json{{")

        mod.import_index("proj", str(bad_file))
        out = capsys.readouterr().out
        assert "Error" in out or "Invalid" in out

    def test_import_backs_up_existing_index(self, tmp_path, capsys):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True)
        existing_index = _make_index(sessions={"old": {"summary": "old"}})
        index_path = proj_dir / "recall-index.json"
        index_path.write_text(json.dumps(existing_index))

        new_index = _make_index(sessions={"new": {"summary": "new"}})
        import_file = tmp_path / "new.json"
        import_file.write_text(json.dumps({
            "exported_at": "2026-04-24T12:00:00",
            "project_folder": "proj",
            "index": new_index,
        }))

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("lib.shared.get_index_path", return_value=index_path):
            mod.import_index("proj", str(import_file))

        # Backup file should exist
        bak_file = proj_dir / "recall-index.json.bak"
        assert bak_file.exists()
        bak_data = json.loads(bak_file.read_text())
        assert "old" in bak_data["sessions"]

    def test_import_resolves_relative_path(self, tmp_path, capsys):
        """import_index converts a relative path to absolute via Path.cwd()."""
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True)
        index_data = _make_index(sessions={"s1": {"summary": "test"}})
        import_file = tmp_path / "myexport.json"
        import_file.write_text(json.dumps(index_data))

        with mock.patch("pathlib.Path.cwd", return_value=tmp_path), \
             mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("lib.shared.get_index_path", return_value=proj_dir / "recall-index.json"):
            mod.import_index("proj", "myexport.json")

        out = capsys.readouterr().out
        assert "Imported" in out


# ---------------------------------------------------------------------------
# cleanup_sensitive_sessions — detail file path
# ---------------------------------------------------------------------------

class TestCleanupSensitiveSessionsDetails:
    def test_removes_session_with_sensitive_detail_content(self, tmp_path):
        mod = _import_recall_sessions()
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir(parents=True)

        index = _make_index(sessions={
            "sess-clean": {"summary": "normal session"},
            "sess-secret": {"summary": "normal summary but secret in details"},
        })
        _write_index(proj_dir, index)

        # Write a detail file with sensitive content
        details_dir = proj_dir / "recall-sessions"
        details_dir.mkdir()
        (details_dir / "sess-secret.json").write_text(json.dumps({
            "user_messages": [{"content": "my TOKEN=abc123 for auth"}],
        }))

        with mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch.object(mod, "get_session_details_dir", return_value=details_dir), \
             mock.patch.object(mod, "load_session_details", side_effect=lambda pf, sid: (
                 {"user_messages": [{"content": "my TOKEN=abc123"}]} if sid == "sess-secret" else None
             )):
            mod.cleanup_sensitive_sessions(index, "proj")

        assert "sess-secret" not in index["sessions"]
        assert "sess-clean" in index["sessions"]


# ---------------------------------------------------------------------------
# main() command dispatch — no-index branches
# ---------------------------------------------------------------------------

class TestMainDispatchNoIndex:
    def test_help_prints_without_sessions_or_index(self, tmp_path):
        """'help' prints command help before trying to load session state."""
        mod = _import_recall_sessions()
        with mock.patch.object(mod, "get_project_folder") as mock_project, \
             mock.patch("sys.argv", ["recall-sessions.py", str(tmp_path), "help"]):
            _, output = _capture(mod.main)
        assert "/recall save" in output
        assert "/recall /*\\.p8/" in output
        mock_project.assert_not_called()

    def _run_main_command(self, mod, tmp_path, command):
        """Helper: run main() with no index and a fake session file."""
        fake_session = tmp_path / "fake.jsonl"
        fake_session.write_text("")
        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "find_session_files", return_value=[fake_session]), \
             mock.patch.object(mod, "load_index", return_value=None), \
             mock.patch("sys.argv", ["recall-sessions.py", str(tmp_path), command]):
            _, output = _capture(mod.main)
        return output

    def test_stats_no_index_prints_message(self, tmp_path, capsys):
        """'stats' with no index prints 'No index available'."""
        mod = _import_recall_sessions()
        output = self._run_main_command(mod, tmp_path, "stats")
        assert "No index" in output

    def test_export_no_index_prints_message(self, tmp_path, capsys):
        """'export' with no index prints 'No index available to export'."""
        mod = _import_recall_sessions()
        output = self._run_main_command(mod, tmp_path, "export")
        assert "No index" in output

    def test_import_no_arg_prints_usage(self, tmp_path, capsys):
        """'import' with no filename prints usage hint."""
        mod = _import_recall_sessions()
        output = self._run_main_command(mod, tmp_path, "import")
        assert "Usage" in output

    def test_failures_no_index_prints_message(self, tmp_path, capsys):
        """'failures' with no index prints 'No index available'."""
        mod = _import_recall_sessions()
        output = self._run_main_command(mod, tmp_path, "failures")
        assert "No index" in output

    def test_learn_script_not_found_prints_message(self, tmp_path, capsys):
        """'learn' command when recall-learn.py doesn't exist prints not-found message."""
        mod = _import_recall_sessions()
        fake_session = tmp_path / "fake.jsonl"
        fake_session.write_text("")
        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "find_session_files", return_value=[fake_session]), \
             mock.patch.object(mod, "load_index", return_value=None), \
             mock.patch("sys.argv", ["recall-sessions.py", str(tmp_path), "learn"]), \
             mock.patch("pathlib.Path.exists", return_value=False):
            _, output = _capture(mod.main)
        assert "not found" in output.lower() or "Learn script" in output

    def test_learn_script_found_with_cmd_arg_passes_arg_to_subprocess(self, tmp_path, capsys):
        """'learn --approve 0' passes approve flag and index separately."""
        mod = _import_recall_sessions()
        fake_session = tmp_path / "fake.jsonl"
        fake_session.write_text("")
        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "find_session_files", return_value=[fake_session]), \
             mock.patch.object(mod, "load_index", return_value=None), \
             mock.patch("sys.argv", ["recall-sessions.py", str(tmp_path), "learn", "--approve", "0"]), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("subprocess.run") as mock_run:
            mod.main()
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert called_args[-2:] == ["--approve", "0"]
        assert mock_run.call_args.kwargs["env"]["CLAUDE_PROJECT_DIR"] == str(tmp_path)
