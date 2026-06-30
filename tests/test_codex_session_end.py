#!/usr/bin/env python3
"""Tests for hooks/scripts/codex_session_end.py — pure utility functions."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_codex_session_end():
    scripts_dir = Path(__file__).resolve().parent.parent / "hooks" / "scripts"
    spec = importlib.util.spec_from_file_location(
        "codex_session_end", scripts_dir / "codex_session_end.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_session(**kwargs):
    base = {
        "session_id": "codex-test-001",
        "date": "2026-04-24T10:00:00",
        "user_messages": [],
        "commands": [],
        "failures": [],
        "skills_used": [],
        "topics": [],
        "summary": "",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# categorize_error
# ---------------------------------------------------------------------------

class TestCategorizeError:
    def test_permission_denied(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("Permission denied: /etc/hosts") == "permission_denied"

    def test_not_found(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("No such file or directory: ENOENT") == "not_found"

    def test_syntax_error(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("syntax error: unexpected token '}'") == "syntax_error"

    def test_connection_error(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("Connection refused: ECONNREFUSED") == "connection_error"

    def test_import_error(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("No module named 'requests'") == "import_error"

    def test_type_error(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("TypeError: 'int' is not callable") == "type_error"

    def test_git_error(self):
        mod = _import_codex_session_end()
        # "fatal: merge conflict" matches git_error; avoid "not found" which hits not_found first
        assert mod.categorize_error("fatal: merge conflict detected") == "git_error"

    def test_npm_error(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("npm ERR! version mismatch") == "npm_error"

    def test_python_error(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("Traceback (most recent call last):") == "python_error"

    def test_fallback_to_other(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("some totally unknown error") == "other_error"

    def test_case_insensitive(self):
        mod = _import_codex_session_end()
        assert mod.categorize_error("PERMISSION DENIED for file") == "permission_denied"

    def test_priority_not_found_before_git(self):
        # "not found" matches not_found before git
        mod = _import_codex_session_end()
        assert mod.categorize_error("fatal: command not found: xyz") == "not_found"


# ---------------------------------------------------------------------------
# create_session_summary
# ---------------------------------------------------------------------------

class TestCreateSessionSummary:
    def test_uses_existing_summary(self):
        mod = _import_codex_session_end()
        session = _make_session(summary="pre-computed summary")
        result = mod.create_session_summary(session)
        assert result["summary"] == "pre-computed summary"

    def test_builds_summary_from_messages(self):
        mod = _import_codex_session_end()
        session = _make_session(
            summary="",
            user_messages=[
                {"content": "Fix the payment bug"},
                {"content": "Also update docs"},
                {"content": "And run tests"},
            ],
        )
        result = mod.create_session_summary(session)
        assert "Fix the payment bug" in result["summary"]

    def test_truncates_summary_to_200(self):
        mod = _import_codex_session_end()
        session = _make_session(
            summary="",
            user_messages=[{"content": "x" * 300}],
        )
        result = mod.create_session_summary(session)
        assert len(result["summary"]) <= 200

    def test_counts_messages_commands_failures(self):
        mod = _import_codex_session_end()
        session = _make_session(
            user_messages=[{"content": "msg1"}, {"content": "msg2"}],
            commands=[{"command": "git status"}, {"command": "git diff"}],
            failures=[{"command": "git push", "error": "denied"}],
        )
        result = mod.create_session_summary(session)
        assert result["message_count"] == 2
        assert result["command_count"] == 2
        assert result["failure_count"] == 1

    def test_has_details_flag_and_platform(self):
        mod = _import_codex_session_end()
        result = mod.create_session_summary(_make_session())
        assert result["has_details"] is True
        assert result["platform"] == "codex"

    def test_topics_truncated_to_10(self):
        mod = _import_codex_session_end()
        session = _make_session(topics=[f"topic{i}" for i in range(20)])
        result = mod.create_session_summary(session)
        assert len(result["topics"]) == 10


# ---------------------------------------------------------------------------
# prune_index
# ---------------------------------------------------------------------------

class TestPruneIndex:
    def _make_index(self, n_sessions: int) -> dict:
        sessions = {}
        for i in range(n_sessions):
            sessions[f"session-{i:04d}"] = {
                "date": f"2026-04-{i+1:02d}T10:00:00",
                "summary": f"session {i}",
                "message_count": 5,
            }
        return {"version": 2, "sessions": sessions, "failure_patterns": {}}

    def test_no_prune_under_limit(self):
        mod = _import_codex_session_end()
        index = self._make_index(10)
        result = mod.prune_index(index)
        assert len(result["sessions"]) == 10

    def test_prunes_to_max_sessions(self):
        mod = _import_codex_session_end()
        index = self._make_index(mod.MAX_SESSIONS_IN_INDEX + 10)
        result = mod.prune_index(index)
        assert len(result["sessions"]) <= mod.MAX_SESSIONS_IN_INDEX

    def test_keeps_most_recent_sessions(self):
        mod = _import_codex_session_end()
        index = self._make_index(mod.MAX_SESSIONS_IN_INDEX + 5)
        result = mod.prune_index(index)
        dates = [s["date"] for s in result["sessions"].values()]
        # All kept sessions should be the most recent ones
        # The oldest kept should be newer than any removed
        assert len(dates) == mod.MAX_SESSIONS_IN_INDEX

    def test_empty_sessions(self):
        mod = _import_codex_session_end()
        index = {"sessions": {}, "failure_patterns": {}}
        result = mod.prune_index(index)
        assert result["sessions"] == {}


# ---------------------------------------------------------------------------
# _extract_exit_code
# ---------------------------------------------------------------------------

class TestExtractExitCode:
    def test_extracts_zero(self):
        mod = _import_codex_session_end()
        assert mod._extract_exit_code("Process exited with code 0") == 0

    def test_extracts_nonzero(self):
        mod = _import_codex_session_end()
        assert mod._extract_exit_code("Process exited with code 1") == 1

    def test_extracts_large_code(self):
        mod = _import_codex_session_end()
        assert mod._extract_exit_code("Process exited with code 127") == 127

    def test_returns_none_when_absent(self):
        mod = _import_codex_session_end()
        assert mod._extract_exit_code("Command completed successfully") is None

    def test_returns_none_on_empty(self):
        mod = _import_codex_session_end()
        assert mod._extract_exit_code("") is None


# ---------------------------------------------------------------------------
# parse_codex_rollout
# ---------------------------------------------------------------------------

class TestParseCodexRollout:
    def _meta_line(self, session_id="abc123", cwd="/repo", timestamp="2026-04-24T10:00:00Z"):
        return json.dumps({
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": cwd, "timestamp": timestamp},
        })

    def _user_msg_line(self, text):
        return json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        })

    def _tool_call_line(self, cmd, call_id="c1"):
        return json.dumps({
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": cmd}),
                "call_id": call_id,
            },
        })

    def _tool_output_line(self, call_id, output):
        return json.dumps({
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": call_id, "output": output},
        })

    def test_extracts_session_metadata(self):
        mod = _import_codex_session_end()
        lines = [self._meta_line(session_id="s1", cwd="/myrepo")]
        result = mod.parse_codex_rollout(lines)
        assert "codex-s1" in result["session_id"]
        assert result["cwd"] == "/myrepo"

    def test_extracts_user_messages(self):
        mod = _import_codex_session_end()
        lines = [
            self._meta_line(),
            self._user_msg_line("Fix the bug in auth module"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1
        assert "Fix the bug" in result["user_messages"][0]["content"]

    def test_skips_agents_md_injection(self):
        mod = _import_codex_session_end()
        lines = [
            self._user_msg_line("# AGENTS.md instructions\nYou are an agent..."),
            self._user_msg_line("Fix the login page"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1
        assert "Fix the login" in result["user_messages"][0]["content"]

    def test_preserves_goal_context_objective(self):
        mod = _import_codex_session_end()
        lines = [
            self._user_msg_line(
                "<goal_context>\n<objective>\nReduce LLM reasoning in recall save\n</objective>\n</goal_context>"
            ),
        ]
        result = mod.parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1
        assert result["user_messages"][0]["content"] == "Reduce LLM reasoning in recall save"
        assert "llm reasoning" in result["summary"].lower()

    def test_extracts_commands(self):
        mod = _import_codex_session_end()
        lines = [
            self._meta_line(),
            self._tool_call_line("git status", call_id="c1"),
            self._tool_output_line("c1", "On branch main\nProcess exited with code 0"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert len(result["commands"]) == 1
        assert result["commands"][0]["command"] == "git status"

    def test_detects_failures_by_exit_code(self):
        mod = _import_codex_session_end()
        lines = [
            self._meta_line(),
            self._tool_call_line("git push", call_id="c1"),
            self._tool_output_line("c1", "fatal: denied\nProcess exited with code 1"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["command"] == "git push"

    def test_detects_failures_by_error_keywords(self):
        mod = _import_codex_session_end()
        lines = [
            self._meta_line(),
            self._tool_call_line("python app.py", call_id="c1"),
            self._tool_output_line("c1", "Traceback (most recent call last): ..."),
        ]
        result = mod.parse_codex_rollout(lines)
        assert len(result["failures"]) == 1

    def test_success_not_counted_as_failure(self):
        mod = _import_codex_session_end()
        lines = [
            self._meta_line(),
            self._tool_call_line("ls -la", call_id="c1"),
            self._tool_output_line("c1", "total 0\nProcess exited with code 0"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert result["failures"] == []

    def test_generates_summary_from_messages(self):
        mod = _import_codex_session_end()
        lines = [
            self._meta_line(),
            self._user_msg_line("Update the payment integration"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert "payment" in result["summary"].lower()

    def test_skips_trivial_messages_for_summary(self):
        mod = _import_codex_session_end()
        lines = [
            self._user_msg_line("yes"),
            self._user_msg_line("ok"),
            self._user_msg_line("Fix the database migration issue"),
        ]
        result = mod.parse_codex_rollout(lines)
        assert "database" in result["summary"].lower()

    def test_empty_lines_skipped(self):
        mod = _import_codex_session_end()
        result = mod.parse_codex_rollout(["", "   ", "\n"])
        assert result["user_messages"] == []
        assert result["commands"] == []

    def test_invalid_json_lines_skipped(self):
        mod = _import_codex_session_end()
        result = mod.parse_codex_rollout(["not json", '{"type": "response_item"}'])
        assert result["user_messages"] == []


# ---------------------------------------------------------------------------
# find_latest_codex_session
# ---------------------------------------------------------------------------

class TestFindLatestCodexSession:
    def test_returns_most_recent_rollout(self, tmp_path):
        mod = _import_codex_session_end()
        sessions_dir = tmp_path / ".codex" / "sessions" / "2026" / "04" / "24"
        sessions_dir.mkdir(parents=True)
        import os
        f1 = sessions_dir / "rollout-a.jsonl"
        f2 = sessions_dir / "rollout-b.jsonl"
        f1.write_text("{}")
        f2.write_text("{}")
        os.utime(f1, (1000, 1000))
        os.utime(f2, (2000, 2000))

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_latest_codex_session()

        assert result == f2

    def test_returns_none_when_no_sessions_dir(self, tmp_path):
        mod = _import_codex_session_end()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_latest_codex_session()
        assert result is None

    def test_returns_none_when_dir_is_empty(self, tmp_path):
        mod = _import_codex_session_end()
        sessions_dir = tmp_path / ".codex" / "sessions"
        sessions_dir.mkdir(parents=True)
        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_latest_codex_session()
        assert result is None
