#!/usr/bin/env python3
"""Tests for hooks/scripts/bash-failure.py and lib/sops.py."""

import json
import sys
import io
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


# ---------------------------------------------------------------------------
# sops.py tests
# ---------------------------------------------------------------------------

class TestMatchError:
    def test_matches_known_pattern(self):
        from sops import match_error
        sops = {"sops": {
            "git_error": {"patterns": ["fatal:", "remote: Permission"], "fixes": [], "description": "git fail"}
        }}
        result = match_error("fatal: unable to access remote", sops)
        assert result is not None
        name, sop = result
        assert name == "git_error"

    def test_case_insensitive_match(self):
        from sops import match_error
        sops = {"sops": {
            "permission_denied": {"patterns": ["permission denied"], "fixes": []}
        }}
        result = match_error("PERMISSION DENIED: /etc/hosts", sops)
        assert result is not None
        assert result[0] == "permission_denied"

    def test_no_match_returns_none(self):
        from sops import match_error
        sops = {"sops": {
            "git_error": {"patterns": ["fatal:"], "fixes": []}
        }}
        result = match_error("completely unrelated error output", sops)
        assert result is None

    def test_empty_sops_returns_none(self):
        from sops import match_error
        result = match_error("some error", {"sops": {}})
        assert result is None

    def test_returns_first_match(self):
        from sops import match_error
        sops = {"sops": {
            "first": {"patterns": ["error"], "fixes": []},
            "second": {"patterns": ["error"], "fixes": []},
        }}
        name, _ = match_error("some error here", sops)
        assert name == "first"


class TestFormatSop:
    def test_includes_name_and_description(self):
        from sops import format_sop
        sop = {"description": "Git remote failed", "fixes": ["Use SSH"]}
        result = format_sop("git_error", sop)
        assert "git_error" in result
        assert "Git remote failed" in result
        assert "Use SSH" in result

    def test_includes_examples_when_present(self):
        from sops import format_sop
        sop = {
            "description": "desc",
            "fixes": [],
            "examples": {"bad": "git push https://", "good": "git push git@github.com:"}
        }
        result = format_sop("git_error", sop)
        assert "BAD" in result
        assert "GOOD" in result
        assert "git push https://" in result

    def test_omits_examples_section_when_empty(self):
        from sops import format_sop
        sop = {"description": "desc", "fixes": ["fix one"], "examples": {}}
        result = format_sop("thing", sop)
        assert "BAD" not in result
        assert "GOOD" not in result

    def test_handles_missing_keys_gracefully(self):
        from sops import format_sop
        result = format_sop("empty", {})
        assert "empty" in result  # name always shown

    def test_shows_good_example_without_bad(self):
        from sops import format_sop
        sop = {"description": "desc", "fixes": [], "examples": {"good": "git push git@github.com:"}}
        result = format_sop("git_tip", sop)
        assert "GOOD" in result
        assert "BAD" not in result


class TestLoadSops:
    def test_returns_empty_structure_when_no_files(self, tmp_path):
        from sops import load_sops
        missing = tmp_path / "nope.json"
        with mock.patch("sops.GLOBAL_SOPS_PATH", missing):
            with mock.patch("sops.get_project_sops_path", return_value=None):
                result = load_sops()
        assert result == {"version": 1, "sops": {}}

    def test_loads_global_sops(self, tmp_path):
        from sops import load_sops
        global_file = tmp_path / "sops.json"
        global_file.write_text(json.dumps({
            "sops": {"git_error": {"patterns": ["fatal:"], "fixes": []}}
        }))
        with mock.patch("sops.GLOBAL_SOPS_PATH", global_file):
            with mock.patch("sops.get_project_sops_path", return_value=None):
                result = load_sops()
        assert "git_error" in result["sops"]

    def test_project_overrides_global(self, tmp_path):
        from sops import load_sops
        global_file = tmp_path / "global.json"
        project_file = tmp_path / "project.json"
        global_file.write_text(json.dumps({
            "sops": {"git_error": {"description": "global version", "patterns": [], "fixes": []}}
        }))
        project_file.write_text(json.dumps({
            "sops": {"git_error": {"description": "project override", "patterns": [], "fixes": []}}
        }))
        with mock.patch("sops.GLOBAL_SOPS_PATH", global_file):
            with mock.patch("sops.get_project_sops_path", return_value=project_file):
                result = load_sops()
        assert result["sops"]["git_error"]["description"] == "project override"

    def test_tolerates_corrupt_global_file(self, tmp_path):
        from sops import load_sops
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with mock.patch("sops.GLOBAL_SOPS_PATH", bad):
            with mock.patch("sops.get_project_sops_path", return_value=None):
                result = load_sops()
        assert result["sops"] == {}

    def test_tolerates_corrupt_project_file(self, tmp_path):
        from sops import load_sops
        good_global = tmp_path / "global.json"
        good_global.write_text(json.dumps({"sops": {"git_error": {"patterns": [], "fixes": []}}}))
        bad_project = tmp_path / "bad-project.json"
        bad_project.write_text("{not json")
        with mock.patch("sops.GLOBAL_SOPS_PATH", good_global):
            with mock.patch("sops.get_project_sops_path", return_value=bad_project):
                result = load_sops()
        # Global loaded, corrupt project silently ignored
        assert "git_error" in result["sops"]


# ---------------------------------------------------------------------------
# bash-failure.py — state helpers
# ---------------------------------------------------------------------------

def _import_bash_failure():
    """Import bash-failure module (hyphen in name requires importlib.util)."""
    import importlib.util
    scripts_dir = Path(__file__).resolve().parent.parent / "hooks" / "scripts"
    spec = importlib.util.spec_from_file_location(
        "bash_failure", scripts_dir / "bash-failure.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # Ensure lib/ is on path so the module can import sops
    lib_dir = str(Path(__file__).resolve().parent.parent / "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    spec.loader.exec_module(mod)
    return mod


class TestReadState:
    def test_returns_none_when_file_missing(self, tmp_path):
        mod = _import_bash_failure()
        missing = tmp_path / ".last-failure"
        with mock.patch.object(mod, "STATE_FILE", missing):
            result = mod.read_state()
        assert result is None

    def test_returns_state_when_recent(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        state = {
            "timestamp": datetime.now().isoformat(),
            "error_type": "git_error",
            "failed_command": "git push",
            "error_message": "fatal: Permission denied",
        }
        state_file.write_text(json.dumps(state))
        with mock.patch.object(mod, "STATE_FILE", state_file):
            result = mod.read_state()
        assert result is not None
        assert result["error_type"] == "git_error"

    def test_returns_none_and_deletes_file_when_expired(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        old_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        state_file.write_text(json.dumps({"timestamp": old_time, "error_type": "x"}))
        with mock.patch.object(mod, "STATE_FILE", state_file):
            result = mod.read_state()
        assert result is None
        assert not state_file.exists()

    def test_returns_none_on_corrupt_json(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        state_file.write_text("{bad json")
        with mock.patch.object(mod, "STATE_FILE", state_file):
            result = mod.read_state()
        assert result is None

    def test_returns_none_when_timestamp_key_missing(self, tmp_path):
        """KeyError on missing 'timestamp' key returns None."""
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        state_file.write_text('{"error_type": "git"}')  # no 'timestamp' key
        with mock.patch.object(mod, "STATE_FILE", state_file):
            result = mod.read_state()
        assert result is None


class TestWriteAndClearState:
    def test_write_creates_file_with_correct_fields(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        with mock.patch.object(mod, "STATE_FILE", state_file):
            mod.write_state("git_error", "git push origin", "fatal: denied")
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["error_type"] == "git_error"
        assert data["failed_command"] == "git push origin"
        assert "timestamp" in data

    def test_write_truncates_long_command(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        long_cmd = "x" * 1000
        with mock.patch.object(mod, "STATE_FILE", state_file):
            mod.write_state("x", long_cmd, "err")
        data = json.loads(state_file.read_text())
        assert len(data["failed_command"]) <= 500

    def test_write_ignores_state_file_permission_error(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        with mock.patch.object(mod, "STATE_FILE", state_file), \
             mock.patch("builtins.open", side_effect=PermissionError("nope")):
            mod.write_state("x", "cmd", "err")  # must not raise

    def test_clear_removes_file(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        state_file.write_text("{}")
        with mock.patch.object(mod, "STATE_FILE", state_file):
            mod.clear_state()
        assert not state_file.exists()

    def test_clear_is_noop_when_file_missing(self, tmp_path):
        mod = _import_bash_failure()
        missing = tmp_path / ".last-failure"
        with mock.patch.object(mod, "STATE_FILE", missing):
            mod.clear_state()  # must not raise

    def test_clear_ignores_state_file_permission_error(self):
        mod = _import_bash_failure()
        state_file = mock.Mock()
        state_file.unlink.side_effect = PermissionError("nope")
        with mock.patch.object(mod, "STATE_FILE", state_file):
            mod.clear_state()  # must not raise


class TestTruncate:
    def test_passes_short_strings_unchanged(self):
        mod = _import_bash_failure()
        assert mod.truncate("hello", 100) == "hello"

    def test_truncates_long_strings(self):
        mod = _import_bash_failure()
        result = mod.truncate("x" * 200, 100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_exact_limit_not_truncated(self):
        mod = _import_bash_failure()
        s = "x" * 100
        assert mod.truncate(s, 100) == s


# ---------------------------------------------------------------------------
# bash-failure.py — main() integration
# ---------------------------------------------------------------------------

def _run_main(hook_input: dict, state_file: Path, sops_data: dict = None, tmp_path: Path = None) -> dict | None:
    """Run main() with given input, returning parsed JSON output or None."""
    mod = _import_bash_failure()
    if sops_data is None:
        sops_data = {"version": 1, "sops": {
            "git_error": {"patterns": ["fatal:"], "description": "git failed", "fixes": ["Use SSH"], "examples": {}}
        }}
    stdin_data = json.dumps(hook_input)
    captured = io.StringIO()
    # Patch load_sops on the module's own namespace (it was imported with `from sops import load_sops`)
    with mock.patch.object(mod, "STATE_FILE", state_file):
        with mock.patch.object(mod, "load_sops", return_value=sops_data):
            with mock.patch("sys.stdin", io.StringIO(stdin_data)):
                with mock.patch("sys.stdout", captured):
                    try:
                        mod.main()
                    except SystemExit:
                        pass
    output = captured.getvalue().strip()
    if output:
        return json.loads(output)
    return None


class TestMainBashFailure:
    def test_shows_sop_on_known_failure(self, tmp_path):
        state_file = tmp_path / ".last-failure"
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "tool_response": {"exitCode": 1, "stderr": "fatal: Permission denied", "stdout": ""},
        }
        result = _run_main(hook_input, state_file, tmp_path=tmp_path)
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "git_error" in ctx

    def test_shows_unknown_message_for_unmatched_error(self, tmp_path):
        state_file = tmp_path / ".last-failure"
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "some command"},
            "tool_response": {"exitCode": 1, "stderr": "totally unknown error xyz", "stdout": ""},
        }
        result = _run_main(hook_input, state_file, tmp_path=tmp_path)
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "UNKNOWN" in ctx

    def test_silent_on_non_bash_tool(self, tmp_path):
        state_file = tmp_path / ".last-failure"
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/etc/hosts"},
            "tool_response": {"exitCode": 0, "stderr": "", "stdout": "localhost"},
        }
        result = _run_main(hook_input, state_file, tmp_path=tmp_path)
        assert result is None

    def test_shows_resolution_after_prior_failure(self, tmp_path):
        state_file = tmp_path / ".last-failure"
        state_data = {
            "timestamp": datetime.now().isoformat(),
            "error_type": "git_error",
            "failed_command": "git push https://",
            "error_message": "fatal: denied",
        }
        state_file.write_text(json.dumps(state_data))
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push git@github.com:org/repo"},
            "tool_response": {"exitCode": 0, "stderr": "", "stdout": "Branch pushed"},
        }
        result = _run_main(hook_input, state_file, tmp_path=tmp_path)
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "git_error" in ctx
        assert "Save as SOP" in ctx

    def test_silent_on_success_with_no_prior_failure(self, tmp_path):
        state_file = tmp_path / ".last-failure-nonexistent"
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_response": {"exitCode": 0, "stderr": "", "stdout": "total 0"},
        }
        result = _run_main(hook_input, state_file, tmp_path=tmp_path)
        assert result is None

    def test_handles_corrupt_stdin_gracefully(self, tmp_path):
        mod = _import_bash_failure()
        state_file = tmp_path / ".last-failure"
        with mock.patch.object(mod, "STATE_FILE", state_file):
            with mock.patch("sys.stdin", io.StringIO("{not json")):
                try:
                    mod.main()
                except SystemExit:
                    pass
        # No exception means graceful handling

    def test_failure_without_stderr_is_ignored(self, tmp_path):
        state_file = tmp_path / ".last-failure"
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "failing-cmd"},
            "tool_response": {"exitCode": 1, "stderr": "", "stdout": "some output"},
        }
        result = _run_main(hook_input, state_file, tmp_path=tmp_path)
        assert result is None
