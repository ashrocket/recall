#!/usr/bin/env python3
"""Tests for hooks/scripts/codex_session_end.py — real Codex JSONL format."""

import json
import time
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "scripts"))

from codex_session_end import parse_codex_rollout, find_latest_codex_session, _extract_exit_code


# ---------------------------------------------------------------------------
# Helpers for building Codex JSONL entries
# ---------------------------------------------------------------------------

def _meta(session_id="abc-123", cwd="/tmp/project", ts="2026-03-20T10:00:00.000Z") -> str:
    return json.dumps({
        "type": "session_meta",
        "payload": {"id": session_id, "cwd": cwd, "timestamp": ts}
    })


def _user_msg(text: str) -> str:
    return json.dumps({
        "type": "response_item",
        "timestamp": "2026-03-20T10:00:01.000Z",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}]
        }
    })


def _function_call(call_id: str, cmd: str) -> str:
    return json.dumps({
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "call_id": call_id,
            "arguments": json.dumps({"cmd": cmd, "workdir": "/tmp/project"})
        }
    })


def _function_output(call_id: str, output: str) -> str:
    return json.dumps({
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output
        }
    })


def _ok_output(call_id: str, stdout: str = "") -> str:
    output = f"Command: /bin/zsh -lc ...\nProcess exited with code 0\nOutput:\n{stdout}"
    return _function_output(call_id, output)


def _err_output(call_id: str, stdout: str, code: int = 1) -> str:
    output = f"Command: /bin/zsh -lc ...\nProcess exited with code {code}\nOutput:\n{stdout}"
    return _function_output(call_id, output)


# ---------------------------------------------------------------------------
# TestExtractExitCode
# ---------------------------------------------------------------------------

class TestExtractExitCode:
    def test_parses_code_zero(self):
        assert _extract_exit_code("Process exited with code 0") == 0

    def test_parses_nonzero_code(self):
        assert _extract_exit_code("Process exited with code 1") == 1

    def test_parses_code_127(self):
        assert _extract_exit_code("Process exited with code 127") == 127

    def test_returns_none_when_missing(self):
        assert _extract_exit_code("No exit code here") is None

    def test_finds_code_within_longer_output(self):
        output = "Wall time: 0.001s\nProcess exited with code 2\nOutput:\nsome text"
        assert _extract_exit_code(output) == 2


# ---------------------------------------------------------------------------
# TestParseCodexRollout
# ---------------------------------------------------------------------------

class TestParseCodexRollout:

    def test_reads_session_id_from_meta(self):
        lines = [_meta(session_id="019d05c7-bcf8-7520-a813-84e47ada2d5e")]
        result = parse_codex_rollout(lines)
        assert "019d05c7" in result["session_id"]
        assert result["session_id"].startswith("codex-")

    def test_reads_cwd_from_meta(self):
        lines = [_meta(cwd="/Users/ash/myproject")]
        result = parse_codex_rollout(lines)
        assert result["cwd"] == "/Users/ash/myproject"

    def test_reads_timestamp_from_meta(self):
        lines = [_meta(ts="2026-03-20T10:00:00.000Z")]
        result = parse_codex_rollout(lines)
        assert "2026-03-20" in result["date"]

    def test_extracts_user_messages(self):
        lines = [_meta(), _user_msg("Refactor the authentication module")]
        result = parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1
        assert "authentication" in result["user_messages"][0]["content"]

    def test_skips_agents_md_injection(self):
        """Codex prepends AGENTS.md content as first user turn — skip it."""
        lines = [
            _meta(),
            _user_msg("# AGENTS.md instructions for /Users/ash/project\n\n## Git rules..."),
            _user_msg("Build me a CLI tool"),
        ]
        result = parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1
        assert "CLI" in result["user_messages"][0]["content"]

    def test_skips_environment_context_injection(self):
        """Codex prepends <environment_context> XML — skip it."""
        lines = [
            _meta(),
            _user_msg("<environment_context>\n  <cwd>/Users/ash/project</cwd>\n</environment_context>"),
            _user_msg("Find all failing tests"),
        ]
        result = parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1
        assert "failing tests" in result["user_messages"][0]["content"]

    def test_skips_short_messages(self):
        lines = [_meta(), _user_msg("ok"), _user_msg("yes"), _user_msg("Build the auth module")]
        result = parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1

    def test_extracts_exec_command_calls(self):
        lines = [_meta(), _function_call("c1", "ls -la")]
        result = parse_codex_rollout(lines)
        assert len(result["commands"]) == 1
        assert result["commands"][0]["command"] == "ls -la"

    def test_ignores_non_exec_command_functions(self):
        entry = json.dumps({
            "type": "response_item",
            "payload": {"type": "function_call", "name": "write_file", "call_id": "c1",
                        "arguments": json.dumps({"path": "foo.py", "content": ""})}
        })
        result = parse_codex_rollout([_meta(), entry])
        assert len(result["commands"]) == 0

    def test_corrupt_function_arguments_gracefully_skipped(self):
        """exec_command with corrupt JSON arguments does not crash — command is skipped."""
        entry = json.dumps({
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1",
                        "arguments": "{not valid json"}
        })
        result = parse_codex_rollout([_meta(), entry])
        assert len(result["commands"]) == 0

    def test_successful_command_not_a_failure(self):
        lines = [_meta(), _function_call("c1", "echo hello"), _ok_output("c1", "hello")]
        result = parse_codex_rollout(lines)
        assert len(result["failures"]) == 0

    def test_nonzero_exit_code_is_failure(self):
        lines = [
            _meta(),
            _function_call("c1", "cat missing.txt"),
            _err_output("c1", "cat: missing.txt: No such file or directory", code=1),
        ]
        result = parse_codex_rollout(lines)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["command"] == "cat missing.txt"

    def test_categorises_permission_denied(self):
        lines = [
            _meta(),
            _function_call("c1", "rm /etc/hosts"),
            _err_output("c1", "rm: /etc/hosts: Permission denied", code=1),
        ]
        result = parse_codex_rollout(lines)
        assert "permission_denied" in result["failure_patterns"]

    def test_categorises_not_found(self):
        lines = [
            _meta(),
            _function_call("c1", "python3 nope.py"),
            _err_output("c1", "python3: can't open file 'nope.py': No such file or directory", code=2),
        ]
        result = parse_codex_rollout(lines)
        assert "not_found" in result["failure_patterns"]

    def test_categorises_command_not_found_127(self):
        lines = [
            _meta(),
            _function_call("c1", "foobar"),
            _err_output("c1", "zsh: command not found: foobar", code=127),
        ]
        result = parse_codex_rollout(lines)
        assert "not_found" in result["failure_patterns"]

    def test_keyword_failure_when_exit_code_is_zero(self):
        """Failure detected by error keyword even when exit code is 0."""
        lines = [
            _meta(),
            _function_call("c1", "npm install"),
            _ok_output("c1", "error: Cannot find module 'webpack'"),
        ]
        result = parse_codex_rollout(lines)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["command"] == "npm install"

    def test_summary_from_first_user_message(self):
        lines = [_meta(), _user_msg("Build me a CLI for monitoring Bitbucket pipelines")]
        result = parse_codex_rollout(lines)
        assert "Bitbucket" in result["summary"]

    def test_summary_appends_second_message(self):
        lines = [
            _meta(),
            _user_msg("Build me a CLI tool"),
            _user_msg("Use Rust for the implementation"),
        ]
        result = parse_codex_rollout(lines)
        assert " | " in result["summary"]
        assert "Rust" in result["summary"]

    def test_empty_input_returns_defaults(self):
        result = parse_codex_rollout([])
        assert result["user_messages"] == []
        assert result["commands"] == []
        assert result["failures"] == []
        assert result["summary"] == ""

    def test_session_id_has_codex_prefix(self):
        result = parse_codex_rollout([])
        assert result["session_id"].startswith("codex-")

    def test_platform_field_set(self):
        from codex_session_end import create_session_summary
        data = parse_codex_rollout([_meta()])
        summary = create_session_summary(data)
        assert summary.get("platform") == "codex"

    def test_truncates_long_command(self):
        long_cmd = "echo " + "x" * 200
        lines = [_meta(), _function_call("c1", long_cmd)]
        result = parse_codex_rollout(lines)
        assert len(result["commands"][0]["command"]) <= 150

    def test_truncates_long_user_message(self):
        long_msg = "Please help me " + "with this task " * 30
        lines = [_meta(), _user_msg(long_msg)]
        result = parse_codex_rollout(lines)
        assert len(result["user_messages"][0]["content"]) <= 200

    def test_skips_corrupt_lines(self):
        lines = [_meta(), "not json at all", _user_msg("Valid message after corruption")]
        result = parse_codex_rollout(lines)
        assert len(result["user_messages"]) == 1

    def test_multiple_commands_tracked(self):
        lines = [
            _meta(),
            _function_call("c1", "ls"),
            _function_call("c2", "pwd"),
            _function_call("c3", "git status"),
        ]
        result = parse_codex_rollout(lines)
        assert len(result["commands"]) == 3


# ---------------------------------------------------------------------------
# TestFindLatestCodexSession
# ---------------------------------------------------------------------------

class TestFindLatestCodexSession:
    def test_returns_none_when_no_sessions_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert find_latest_codex_session() is None

    def test_returns_none_when_sessions_dir_empty(self, tmp_path, monkeypatch):
        (tmp_path / ".codex" / "sessions").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert find_latest_codex_session() is None

    def test_finds_session_in_nested_date_dir(self, tmp_path, monkeypatch):
        session_dir = tmp_path / ".codex" / "sessions" / "2026" / "03" / "20"
        session_dir.mkdir(parents=True)
        f = session_dir / "rollout-2026-03-20T10-00-00-abc123.jsonl"
        f.write_text("{}")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert find_latest_codex_session() == f

    def test_returns_most_recent_across_dates(self, tmp_path, monkeypatch):
        old_dir = tmp_path / ".codex" / "sessions" / "2026" / "03" / "19"
        new_dir = tmp_path / ".codex" / "sessions" / "2026" / "03" / "20"
        old_dir.mkdir(parents=True)
        new_dir.mkdir(parents=True)
        old = old_dir / "rollout-old.jsonl"
        new = new_dir / "rollout-new.jsonl"
        old.write_text("{}")
        time.sleep(0.01)
        new.write_text("{}")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert find_latest_codex_session() == new
