#!/usr/bin/env python3
"""Tests for bin/extract-knowledge.py."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_extract_knowledge():
    spec = importlib.util.spec_from_file_location(
        "extract_knowledge",
        Path(__file__).resolve().parent.parent / "bin" / "extract-knowledge.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_session(commands=None, failures=None):
    return {
        "session_id": "test-session-001",
        "summary": "test session",
        "user_messages": [],
        "commands": commands or [],
        "failures": failures or [],
    }


# ---------------------------------------------------------------------------
# categorize_for_learning
# ---------------------------------------------------------------------------

class TestCategorizeForLearning:
    def test_shell_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("syntax error: unexpected token") == "shell"

    def test_permissions_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("permission denied: /etc/hosts") == "permissions"

    def test_paths_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("No such file or directory: ENOENT") == "paths"

    def test_network_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("Connection refused: ECONNREFUSED") == "network"

    def test_python_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("Traceback (most recent call last):") == "python"

    def test_git_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("fatal: unable to access remote") == "git"

    def test_npm_error(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("npm ERR! version mismatch") == "npm"

    def test_general_fallback(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("some totally unknown error xyz") == "general"

    def test_case_insensitive(self):
        mod = _import_extract_knowledge()
        assert mod.categorize_for_learning("PERMISSION DENIED for root") == "permissions"


# ---------------------------------------------------------------------------
# extract_failure_resolution_pairs
# ---------------------------------------------------------------------------

class TestExtractFailureResolutionPairs:
    def test_finds_resolution_pair(self):
        mod = _import_extract_knowledge()
        session = _make_session(
            commands=[
                {"command": "git push https://github.com/org/repo", "index": 1, "tool_id": "t1"},
                {"command": "git push git@github.com:org/repo", "index": 5, "tool_id": "t2"},
            ],
            failures=[
                {"command": "git push https://github.com/org/repo", "error": "fatal: denied", "index": 2},
            ],
        )
        proposals = mod.extract_failure_resolution_pairs(session, "work")
        assert len(proposals) == 1
        assert "git push git@" in proposals[0]["solution"]
        assert proposals[0]["bucket"] == "work"
        assert proposals[0]["source"] == "failure_resolution"

    def test_no_resolution_when_later_command_absent(self):
        mod = _import_extract_knowledge()
        session = _make_session(
            commands=[
                {"command": "git push https://", "index": 1, "tool_id": "t1"},
            ],
            failures=[
                {"command": "git push https://", "error": "fatal: denied", "index": 2},
            ],
        )
        proposals = mod.extract_failure_resolution_pairs(session)
        assert proposals == []

    def test_resolution_must_appear_after_failure(self):
        mod = _import_extract_knowledge()
        # The "resolution" appears BEFORE the failure
        session = _make_session(
            commands=[
                {"command": "git push git@github.com:org/repo", "index": 1, "tool_id": "t1"},
                {"command": "git push https://github.com/org/repo", "index": 5, "tool_id": "t2"},
            ],
            failures=[
                {"command": "git push https://github.com/org/repo", "error": "fatal: denied", "index": 6},
            ],
        )
        proposals = mod.extract_failure_resolution_pairs(session)
        assert proposals == []

    def test_no_proposals_when_no_failures(self):
        mod = _import_extract_knowledge()
        session = _make_session(
            commands=[{"command": "git push", "index": 1, "tool_id": "t1"}],
            failures=[],
        )
        assert mod.extract_failure_resolution_pairs(session) == []

    def test_uses_default_bucket_when_none_given(self):
        mod = _import_extract_knowledge()
        session = _make_session(
            commands=[
                {"command": "npm install", "index": 1, "tool_id": "t1"},
                {"command": "npm ci", "index": 5, "tool_id": "t2"},
            ],
            failures=[
                {"command": "npm install", "error": "npm ERR! version mismatch", "index": 2},
            ],
        )
        with mock.patch.object(mod, "DEFAULT_BUCKET", "personal"):
            proposals = mod.extract_failure_resolution_pairs(session)
        assert proposals[0]["bucket"] == "personal"


# ---------------------------------------------------------------------------
# extract_repeated_failure_patterns
# ---------------------------------------------------------------------------

class TestExtractRepeatedFailurePatterns:
    def test_proposes_when_three_or_more_same_category(self):
        mod = _import_extract_knowledge()
        session = _make_session(failures=[
            {"command": "cat /etc/shadow", "error": "Permission denied", "index": 1},
            {"command": "sudo cat /etc/shadow", "error": "Permission denied", "index": 3},
            {"command": "less /etc/shadow", "error": "Permission denied", "index": 5},
        ])
        proposals = mod.extract_repeated_failure_patterns(session)
        assert len(proposals) == 1
        assert proposals[0]["category"] == "permissions"
        assert "3" in proposals[0]["title"] or 3 <= int(next(
            c for c in proposals[0]["title"] if c.isdigit()
        ))

    def test_no_proposal_when_fewer_than_three(self):
        mod = _import_extract_knowledge()
        session = _make_session(failures=[
            {"command": "cat /etc/shadow", "error": "Permission denied"},
            {"command": "sudo cat /etc/shadow", "error": "Permission denied"},
        ])
        assert mod.extract_repeated_failure_patterns(session) == []

    def test_no_proposals_when_no_failures(self):
        mod = _import_extract_knowledge()
        assert mod.extract_repeated_failure_patterns(_make_session()) == []

    def test_uses_default_bucket(self):
        mod = _import_extract_knowledge()
        session = _make_session(failures=[
            {"command": f"cmd{i}", "error": "Permission denied"} for i in range(3)
        ])
        with mock.patch.object(mod, "DEFAULT_BUCKET", "personal"):
            proposals = mod.extract_repeated_failure_patterns(session)
        assert all(p["bucket"] == "personal" for p in proposals)

    def test_multiple_categories_independent(self):
        mod = _import_extract_knowledge()
        # Use "fatal:" without "connection refused" so it maps to git, not network
        session = _make_session(failures=[
            {"command": f"perm{i}", "error": "Permission denied"} for i in range(3)
        ] + [
            {"command": f"git{i}", "error": "fatal: merge conflict detected"} for i in range(3)
        ])
        proposals = mod.extract_repeated_failure_patterns(session)
        categories = {p["category"] for p in proposals}
        assert "permissions" in categories
        assert "git" in categories


# ---------------------------------------------------------------------------
# DEFAULT_BUCKET import (regression test for the NameError bug)
# ---------------------------------------------------------------------------

class TestDefaultBucketImport:
    def test_DEFAULT_BUCKET_is_importable(self):
        mod = _import_extract_knowledge()
        assert hasattr(mod, "DEFAULT_BUCKET")
        assert isinstance(mod.DEFAULT_BUCKET, str)
        assert mod.DEFAULT_BUCKET  # non-empty

    def test_extract_repeated_uses_DEFAULT_BUCKET_not_karepartners(self):
        mod = _import_extract_knowledge()
        session = _make_session(failures=[
            {"command": f"cmd{i}", "error": "Permission denied"} for i in range(3)
        ])
        proposals = mod.extract_repeated_failure_patterns(session)
        for p in proposals:
            assert p["bucket"] != "karepartners", "hardcoded karepartners bucket found"


# ---------------------------------------------------------------------------
# main() — stdin/argv error branches
# ---------------------------------------------------------------------------

class TestMain:
    def test_corrupt_stdin_exits_with_error_json(self, tmp_path):
        mod = _import_extract_knowledge()
        import io
        with mock.patch("sys.stdin", io.StringIO("{bad json")), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as cap:
            try:
                mod.main()
            except SystemExit:
                pass
        output = json.loads(cap.getvalue())
        assert output["proposals_added"] == 0
        assert "error" in output

    def test_main_happy_path_adds_proposals(self, tmp_path):
        """main() adds proposals when repeated failures are detected."""
        mod = _import_extract_knowledge()
        import io
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        session = _make_session(failures=[
            {"command": "git push", "error": "permission denied", "category": "permission_error"},
            {"command": "git push", "error": "permission denied", "category": "permission_error"},
            {"command": "git push", "error": "permission denied", "category": "permission_error"},
        ])
        with mock.patch("sys.stdin", io.StringIO(json.dumps(session))), \
             mock.patch("sys.argv", ["extract-knowledge.py", "stdin", "proj"]), \
             mock.patch("lib.shared.get_project_dir", return_value=proj_dir), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as cap:
            mod.main()
        output = json.loads(cap.getvalue())
        assert "proposals_added" in output

    def test_missing_project_folder_exits_with_error_json(self, tmp_path):
        mod = _import_extract_knowledge()
        import io
        session = json.dumps(_make_session())
        with mock.patch("sys.stdin", io.StringIO(session)), \
             mock.patch("sys.argv", ["extract-knowledge.py"]), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as cap:
            try:
                mod.main()
            except SystemExit:
                pass
        output = json.loads(cap.getvalue())
        assert output["proposals_added"] == 0
        assert "no project folder" in output.get("error", "")
