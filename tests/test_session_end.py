#!/usr/bin/env python3
"""Tests for hooks/scripts/session-end.py."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_session_end():
    spec = importlib.util.spec_from_file_location(
        "session_end",
        Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "session-end.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_jsonl(path: Path, lines: list):
    path.write_text("\n".join(json.dumps(obj) for obj in lines))


def _make_index(sessions=None):
    return {
        "version": 2,
        "sessions": sessions or {},
        "failure_patterns": {},
        "learnings": [],
        "pending_learnings": [],
        "usage": {"skills": {}, "learnings_shown": {}},
    }


# ---------------------------------------------------------------------------
# categorize_error
# ---------------------------------------------------------------------------

class TestCategorizeError:
    def test_permission_denied(self):
        mod = _import_session_end()
        assert mod.categorize_error("permission denied: /etc/hosts") == "permission_denied"

    def test_not_found(self):
        mod = _import_session_end()
        assert mod.categorize_error("No such file or directory: ENOENT") == "not_found"

    def test_git_error(self):
        mod = _import_session_end()
        # "not found" triggers not_found first; use a git error without that phrase
        assert mod.categorize_error("fatal: unable to access 'https://github.com/'") == "git_error"

    def test_import_error(self):
        mod = _import_session_end()
        assert mod.categorize_error("ModuleNotFoundError: No module named 'foo'") == "import_error"

    def test_connection_error(self):
        mod = _import_session_end()
        assert mod.categorize_error("Connection refused: ECONNREFUSED") == "connection_error"

    def test_syntax_error(self):
        mod = _import_session_end()
        assert mod.categorize_error("SyntaxError: unexpected token '}'") == "syntax_error"

    def test_python_error(self):
        mod = _import_session_end()
        assert mod.categorize_error("Traceback (most recent call last):") == "python_error"

    def test_npm_error(self):
        mod = _import_session_end()
        # "ENOENT" triggers not_found first; use npm error without that keyword
        assert mod.categorize_error("npm ERR! version mismatch") == "npm_error"

    def test_unknown_returns_other_error(self):
        mod = _import_session_end()
        assert mod.categorize_error("some completely random error message zyx") == "other_error"

    def test_case_insensitive(self):
        mod = _import_session_end()
        assert mod.categorize_error("PERMISSION DENIED for root") == "permission_denied"


# ---------------------------------------------------------------------------
# parse_session_full — user messages and topics
# ---------------------------------------------------------------------------

class TestParseSessionFullMessages:
    def test_extracts_user_messages(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "fix the authentication bug in auth.py"}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["user_messages"]) == 1
        assert "authentication" in result["user_messages"][0]["content"]

    def test_skips_messages_starting_with_angle_bracket(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "<system>internal context</system>"}},
            {"type": "user", "message": {"content": "real user message here"}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["user_messages"]) == 1
        assert result["user_messages"][0]["content"] == "real user message here"

    def test_extracts_topics_from_messages(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "Fix the PaymentService class in payment_service.py"}},
        ])
        result = mod.parse_session_full(session)
        # PaymentService is a CamelCase term, payment_service.py is a path
        assert any("Payment" in t or "payment_service.py" in t for t in result["topics"])

    def test_filters_topic_stop_words(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "This should not add stop words like The And But"}},
        ])
        result = mod.parse_session_full(session)
        assert "The" not in result["topics"]
        assert "And" not in result["topics"]

    def test_summary_from_first_meaningful_message(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "yes"}},  # trivial
            {"type": "user", "message": {"content": "Fix the login redirect loop in auth/middleware.py"}},
        ])
        result = mod.parse_session_full(session)
        assert "login redirect" in result["summary"].lower() or "Fix" in result["summary"]

    def test_summary_appends_second_short_message(self, tmp_path):
        """Second meaningful message is appended when summary < 120 chars."""
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "Fix the login bug in auth module"}},
            {"type": "user", "message": {"content": "Also update the test fixtures"}},
        ])
        result = mod.parse_session_full(session)
        assert "|" in result["summary"]

    def test_summary_empty_when_all_messages_trivial(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "yes"}},
            {"type": "user", "message": {"content": "ok"}},
        ])
        result = mod.parse_session_full(session)
        # Falls back to joining messages
        assert isinstance(result["summary"], str)

    def test_handles_empty_jsonl(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        session.write_text("")
        result = mod.parse_session_full(session)
        assert result["user_messages"] == []
        assert result["commands"] == []
        assert result["failures"] == []

    def test_handles_corrupt_lines_gracefully(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        session.write_text("{not json}\n" + json.dumps(
            {"type": "user", "message": {"content": "good message"}}
        ))
        result = mod.parse_session_full(session)
        assert len(result["user_messages"]) == 1

    def test_outer_io_error_stored_in_result(self, tmp_path):
        """Unreadable file (directory path) triggers outer exception handler."""
        mod = _import_session_end()
        # On POSIX, opening a directory as a file raises IsADirectoryError
        not_a_file = tmp_path / "mydir.jsonl"
        not_a_file.mkdir()
        result = mod.parse_session_full(not_a_file)
        assert "error" in result


# ---------------------------------------------------------------------------
# parse_session_full — commands and failures
# ---------------------------------------------------------------------------

class TestParseSessionFullCommands:
    def test_extracts_bash_commands(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "pytest tests/"}}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["commands"]) == 1
        assert result["commands"][0]["command"] == "pytest tests/"

    def test_ignores_non_bash_tools(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "id": "t1", "input": {"file_path": "/etc/hosts"}}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert result["commands"] == []

    def test_detects_skill_invocations(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Skill", "id": "t1", "input": {"skill": "recall"}}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["skills_used"]) == 1
        assert result["skills_used"][0]["skill"] == "recall"

    def test_detects_tool_result_failure(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "git push"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "fatal: Permission denied", "is_error": True}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["command"] == "git push"
        assert "fatal" in result["failures"][0]["error"].lower()

    def test_failure_pattern_categorized(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "cat /etc/shadow"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "Permission denied", "is_error": True}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert "permission_denied" in result["failure_patterns"]

    def test_topics_is_list_in_result(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "Fix AuthService and UserProfile"}},
        ])
        result = mod.parse_session_full(session)
        assert isinstance(result["topics"], list)

    def test_summary_includes_skill_tag(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "Refactor the auth module"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Skill", "id": "s1", "input": {"skill": "plugin:recall"}}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert result["summary"].startswith("[recall]")

    def test_keyword_failure_detection_without_is_error(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "npm install"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "error: Could not resolve dependency"}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["failures"]) == 1

    def test_diff_output_mentioning_errors_not_a_failure(self, tmp_path):
        """Successful `git diff` output quoting code that contains words like
        'failed' or 'not found' mid-line must not be recorded as a failure."""
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        diff_output = (
            "diff --git a/tests/test_x.py b/tests/test_x.py\n"
            "index c11241c..91f13a8 100755\n"
            "--- a/tests/test_x.py\n"
            "+++ b/tests/test_x.py\n"
            '+        assert "not found" in output.lower()\n'
            "+        # the command failed earlier\n"
        )
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "git diff"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": diff_output, "is_error": False}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert result["failures"] == []

    def test_cat_of_script_with_error_strings_not_a_failure(self, tmp_path):
        """Successful `cat` of a script whose source mentions errors inside
        echo strings must not be recorded as a failure."""
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        script_output = (
            "#!/usr/bin/env bash\n"
            "set -e\n"
            'if [[ -z "$INSTALL_PATH" ]]; then\n'
            '    echo "Error: recall not found in $PLUGIN_JSON"\n'
            "    exit 1\n"
            "fi\n"
        )
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "cat bin/sync-dev.sh"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": script_output, "is_error": False}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert result["failures"] == []

    def test_masked_pytest_failure_still_detected(self, tmp_path):
        """A real test failure whose exit code was masked by a pipe (is_error
        False) must still be detected from line-start failure markers."""
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        pytest_output = (
            "FAILED tests/test_plugin_packaging.py::test_codex_manifest\n"
            "1 failed, 683 passed in 2.60s\n"
        )
        _write_jsonl(session, [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1",
                 "input": {"command": "python3 -m pytest tests/ -q 2>&1 | tail -2"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": pytest_output, "is_error": False}
            ]}},
        ])
        result = mod.parse_session_full(session)
        assert len(result["failures"]) == 1

    def test_file_path_extracted_into_topics(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "Update lib/shared.py and tests/test_shared.py"}},
        ])
        result = mod.parse_session_full(session)
        topic_names = [t for t in result["topics"]]
        assert any("shared.py" in t for t in topic_names)

    def test_xml_prefixed_user_message_is_skipped(self, tmp_path):
        mod = _import_session_end()
        session = tmp_path / "abc123.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "<system>context injected</system>"}},
            {"type": "user", "message": {"content": "Fix the bug in router"}},
        ])
        result = mod.parse_session_full(session)
        assert all("<system>" not in m["content"] for m in result["user_messages"])


# ---------------------------------------------------------------------------
# create_session_summary
# ---------------------------------------------------------------------------

class TestCreateSessionSummary:
    def test_includes_essential_fields(self):
        mod = _import_session_end()
        session_data = {
            "date": "2026-04-24T10:00:00",
            "summary": "Fix login redirect",
            "user_messages": [{"content": "msg"}],
            "commands": [{"command": "pytest"}, {"command": "git"}],
            "failures": [],
            "skills_used": [],
            "topics": ["auth", "login"],
        }
        result = mod.create_session_summary(session_data)
        assert result["date"] == "2026-04-24T10:00:00"
        assert result["summary"] == "Fix login redirect"
        assert result["message_count"] == 1
        assert result["command_count"] == 2
        assert result["failure_count"] == 0
        assert result["has_details"] is True

    def test_falls_back_when_summary_empty(self):
        mod = _import_session_end()
        session_data = {
            "date": "2026-04-24",
            "summary": "",
            "user_messages": [{"content": "first message here"}, {"content": "second"}],
            "commands": [],
            "failures": [],
            "skills_used": [],
            "topics": [],
        }
        result = mod.create_session_summary(session_data)
        assert "first message" in result["summary"]

    def test_truncates_summary_at_200_chars(self):
        mod = _import_session_end()
        session_data = {
            "date": "2026-04-24",
            "summary": "x" * 300,
            "user_messages": [],
            "commands": [],
            "failures": [],
            "skills_used": [],
            "topics": [],
        }
        result = mod.create_session_summary(session_data)
        assert len(result["summary"]) <= 200

    def test_limits_topics_to_ten(self):
        mod = _import_session_end()
        session_data = {
            "date": "2026-04-24",
            "summary": "test",
            "user_messages": [],
            "commands": [],
            "failures": [],
            "skills_used": [],
            "topics": [f"topic{i}" for i in range(25)],
        }
        result = mod.create_session_summary(session_data)
        assert len(result["topics"]) <= 10


# ---------------------------------------------------------------------------
# prune_index
# ---------------------------------------------------------------------------

class TestPruneIndex:
    def test_keeps_most_recent_sessions(self):
        mod = _import_session_end()
        sessions = {f"s{i:03d}": {"date": f"2026-04-{i:02d}T00:00:00"} for i in range(1, 61)}
        index = _make_index(sessions=sessions)
        pruned = mod.prune_index(index, max_sessions=50, max_index_size_kb=9999)
        assert len(pruned["sessions"]) == 50
        # Newest 50 should remain
        assert "s060" in pruned["sessions"]
        assert "s001" not in pruned["sessions"]

    def test_returns_unchanged_when_under_limits(self):
        mod = _import_session_end()
        sessions = {"s001": {"date": "2026-04-01T00:00:00"}}
        index = _make_index(sessions=sessions)
        pruned = mod.prune_index(index, max_sessions=50, max_index_size_kb=9999)
        assert len(pruned["sessions"]) == 1

    def test_empty_sessions_returns_unchanged(self):
        mod = _import_session_end()
        index = _make_index()
        pruned = mod.prune_index(index, max_sessions=50, max_index_size_kb=9999)
        assert pruned["sessions"] == {}

    def test_prunes_further_when_over_size_limit(self):
        mod = _import_session_end()
        # Create sessions with large summaries to trigger size-based pruning
        big_summary = "x" * 1000
        sessions = {f"s{i:03d}": {"date": f"2026-04-{i:02d}T00:00:00", "summary": big_summary}
                    for i in range(1, 21)}
        index = _make_index(sessions=sessions)
        pruned = mod.prune_index(index, max_sessions=50, max_index_size_kb=1)  # 1 KB limit
        # Should have pruned some to get under size limit, but always keeps ≥ 10
        assert len(pruned["sessions"]) >= 10


# ---------------------------------------------------------------------------
# cleanup_old_detail_files
# ---------------------------------------------------------------------------

class TestCleanupOldDetailFiles:
    def test_removes_excess_files_keeping_newest(self, tmp_path):
        mod = _import_session_end()
        details_dir = tmp_path / "proj" / "recall-sessions"
        details_dir.mkdir(parents=True)
        # Create 15 files
        for i in range(15):
            f = details_dir / f"session{i:02d}.json"
            f.write_text("{}")
            import os, time
            os.utime(f, (i * 100, i * 100))  # older = lower mtime

        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path / "proj"):
            mod.cleanup_old_detail_files("proj", keep_count=10)

        remaining = list(details_dir.glob("*.json"))
        assert len(remaining) == 10

    def test_noop_when_dir_missing(self, tmp_path):
        mod = _import_session_end()
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path / "nonexistent"):
            mod.cleanup_old_detail_files("nonexistent", keep_count=10)
        # No exception raised


# ---------------------------------------------------------------------------
# find_current_session
# ---------------------------------------------------------------------------

class TestFindCurrentSession:
    def test_returns_most_recent_session(self, tmp_path):
        mod = _import_session_end()
        # _find_sessions_in_folder scans Path.home()/.claude/projects/<folder>
        project_dir = tmp_path / ".claude" / "projects" / "myapp"
        project_dir.mkdir(parents=True)
        f1 = project_dir / "session1.jsonl"
        f2 = project_dir / "session2.jsonl"
        f1.write_text("{}")
        f2.write_text("{}")
        import os, time
        os.utime(f1, (1000, 1000))
        os.utime(f2, (2000, 2000))  # newer

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_current_session("myapp")
        assert result == f2

    def test_returns_none_when_no_sessions(self, tmp_path):
        mod = _import_session_end()
        project_dir = tmp_path / ".claude" / "projects" / "empty"
        project_dir.mkdir(parents=True)

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_current_session("empty")
        assert result is None

    def test_falls_back_to_also_check_folder(self, tmp_path):
        mod = _import_session_end()
        # Primary folder is empty; secondary has a session file
        (tmp_path / ".claude" / "projects" / "primary").mkdir(parents=True)
        secondary_dir = tmp_path / ".claude" / "projects" / "secondary"
        secondary_dir.mkdir(parents=True)
        fallback_file = secondary_dir / "session.jsonl"
        fallback_file.write_text("{}")

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_current_session("primary", also_check_folder="secondary")
        assert result == fallback_file

    def test_skips_fallback_when_same_as_primary(self, tmp_path):
        mod = _import_session_end()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        session = project_dir / "session.jsonl"
        session.write_text("{}")

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_current_session("proj", also_check_folder="proj")
        assert result == session  # found in primary, doesn't try secondary

    def test_skips_agent_prefix_files(self, tmp_path):
        mod = _import_session_end()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        agent_file = project_dir / "agent-abc.jsonl"
        agent_file.write_text("{}")  # should be excluded by _find_sessions_in_folder

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_current_session("proj")
        assert result is None


# ---------------------------------------------------------------------------
# cleanup_old_jsonl_files
# ---------------------------------------------------------------------------

class TestCleanupOldJsonlFiles:
    def _touch_old(self, path: Path, days_old: int):
        """Create a file and backdate its mtime."""
        path.write_text("{}")
        import os, time
        from datetime import timedelta
        ts = (time.time() - timedelta(days=days_old).total_seconds())
        os.utime(path, (ts, ts))

    def test_keeps_5_most_recent_session_files(self, tmp_path):
        mod = _import_session_end()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        # Create 8 session files older than 30 days
        import os, time
        from datetime import timedelta
        for i in range(8):
            f = project_dir / f"session{i:02d}.jsonl"
            self._touch_old(f, days_old=40)
            # Make mtime sequential so newest=7 oldest=0
            ts = time.time() - timedelta(days=40).total_seconds() + i * 100
            os.utime(f, (ts, ts))

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_old_jsonl_files("proj")

        remaining = list(project_dir.glob("session*.jsonl"))
        assert len(remaining) == 5

    def test_keeps_young_session_files(self, tmp_path):
        mod = _import_session_end()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        f = project_dir / "recent.jsonl"
        self._touch_old(f, days_old=1)  # only 1 day old

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_old_jsonl_files("proj")

        assert f.exists()

    def test_removes_old_agent_files(self, tmp_path):
        mod = _import_session_end()
        project_dir = tmp_path / ".claude" / "projects" / "proj"
        project_dir.mkdir(parents=True)
        agent_file = project_dir / "agent-old.jsonl"
        self._touch_old(agent_file, days_old=10)  # older than 7-day limit

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_old_jsonl_files("proj")

        assert not agent_file.exists()

    def test_noop_when_dir_missing(self, tmp_path):
        mod = _import_session_end()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            mod.cleanup_old_jsonl_files("nonexistent")  # no exception


# ---------------------------------------------------------------------------
# save_session_details
# ---------------------------------------------------------------------------

class TestSaveSessionDetails:
    def test_writes_json_file(self, tmp_path):
        mod = _import_session_end()
        details = {"user_messages": [{"content": "fix auth"}], "commands": []}
        details_dir = tmp_path / "recall-sessions"

        with mock.patch.object(mod, "get_session_details_dir", return_value=details_dir):
            mod.save_session_details("proj", "sess-abc123", details)

        saved_file = details_dir / "sess-abc123.json"
        assert saved_file.exists()
        import json
        data = json.loads(saved_file.read_text())
        assert data["user_messages"][0]["content"] == "fix auth"

    def test_creates_directory_if_missing(self, tmp_path):
        mod = _import_session_end()
        details_dir = tmp_path / "deep" / "recall-sessions"

        with mock.patch.object(mod, "get_session_details_dir", return_value=details_dir):
            mod.save_session_details("proj", "sess-new", {"commands": []})

        assert details_dir.is_dir()

    def test_overwrites_existing_file(self, tmp_path):
        mod = _import_session_end()
        details_dir = tmp_path / "recall-sessions"
        details_dir.mkdir()
        (details_dir / "sess-x.json").write_text('{"old": true}')

        with mock.patch.object(mod, "get_session_details_dir", return_value=details_dir):
            mod.save_session_details("proj", "sess-x", {"new": True})

        import json
        data = json.loads((details_dir / "sess-x.json").read_text())
        assert data.get("new") is True
        assert "old" not in data


# ---------------------------------------------------------------------------
# load_index (session-end wrapper — always creates if missing)
# ---------------------------------------------------------------------------

class TestSessionEndLoadIndex:
    def test_returns_empty_index_when_missing(self, tmp_path):
        mod = _import_session_end()
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = mod.load_index("proj")
        assert result is not None
        assert result["sessions"] == {}

    def test_loads_existing_index(self, tmp_path):
        mod = _import_session_end()
        import json
        index = {"version": 2, "sessions": {"x": {"summary": "loaded"}}, "failure_patterns": {}, "learnings": [], "pending_learnings": [], "usage": {}}
        (tmp_path / "recall-index.json").write_text(json.dumps(index))

        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = mod.load_index("proj")

        assert result["sessions"]["x"]["summary"] == "loaded"


# ---------------------------------------------------------------------------
# save_index (session-end wrapper — uses prune_index)
# ---------------------------------------------------------------------------

class TestSessionEndSaveIndex:
    def test_save_then_load_roundtrip(self, tmp_path):
        mod = _import_session_end()
        import json
        index = {"version": 2, "sessions": {"s": {"summary": "roundtrip"}}, "failure_patterns": {}, "learnings": [], "pending_learnings": [], "usage": {}}

        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            mod.save_index("proj", index)
            result = mod.load_index("proj")

        assert result["sessions"]["s"]["summary"] == "roundtrip"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestSessionEndMain:
    def test_emits_no_stdout_on_success(self, tmp_path, capsys):
        # SessionEnd hooks have no hookSpecificOutput variant in Claude Code's
        # hook schema (unlike PreToolUse/PostToolUse/Stop/etc) — printing one
        # fails hook JSON validation. Progress messages must go to stderr and
        # stdout must stay empty.
        mod = _import_session_end()
        session_file = tmp_path / "abc123.jsonl"
        session_file.write_text("{}\n")
        session_data = {
            "session_id": "abc123",
            "date": "2026-04-24T10:00:00",
            "summary": "Fix auth",
            "topics": [],
            "user_messages": [],
            "commands": [],
            "failures": [],
            "failure_patterns": {},
            "skills_used": [],
        }

        with mock.patch.object(mod, "get_project_folders", return_value=("proj", "proj")), \
             mock.patch.object(mod, "find_current_session", return_value=session_file), \
             mock.patch.object(mod, "parse_session_full", return_value=session_data), \
             mock.patch.object(mod, "save_session_details"), \
             mock.patch.object(mod, "load_index", return_value={"version": 2, "sessions": {}, "failure_patterns": {}, "learnings": [], "pending_learnings": [], "usage": {}}), \
             mock.patch.object(mod, "save_index"), \
             mock.patch.object(mod, "cleanup_old_detail_files"), \
             mock.patch.object(mod, "cleanup_old_jsonl_files"), \
             mock.patch("lib.sync_hooks.maybe_sync_push"), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="{}")), \
             mock.patch("random.random", return_value=1.0), \
             mock.patch.object(sys, "argv", ["session-end.py", str(tmp_path)]):
            mod.main()

        out = capsys.readouterr()
        assert out.out == ""
