#!/usr/bin/env python3
"""
Parity tests: run the Rust binary and Python backend against the same fixture
and assert they produce equivalent output for the 'failures' command.

Both paths use $HOME/.claude/projects/<slug>/recall-index.json.
We point HOME at a tmp dir so tests never touch the real user index.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUST_BIN = REPO / "target" / "release" / "recall-sessions-rs"
PYTHON_BIN = REPO / "bin" / "recall-sessions.py"

FAKE_CWD = "/fake/test/cwd"
FAKE_CWD_SLUG = FAKE_CWD.replace("/", "-")  # "-fake-test-cwd"


def _write_index(home_dir: Path, index: dict):
    proj_dir = home_dir / ".claude" / "projects" / FAKE_CWD_SLUG
    proj_dir.mkdir(parents=True)
    (proj_dir / "recall-index.json").write_text(json.dumps(index))
    return proj_dir


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


def _run_rust(home_dir: Path, *extra_args) -> str:
    result = subprocess.run(
        [str(RUST_BIN), FAKE_CWD, *extra_args],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home_dir)},
    )
    return result.stdout


def _run_python(home_dir: Path, *extra_args) -> str:
    result = subprocess.run(
        [sys.executable, str(PYTHON_BIN), FAKE_CWD, *extra_args],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home_dir)},
    )
    return result.stdout


@pytest.mark.skipif(not RUST_BIN.exists(), reason="Rust binary not built")
class TestFailuresParity:
    """Both implementations must handle failures identically."""

    def test_empty_index_both_show_no_patterns(self, tmp_path):
        _write_index(tmp_path, _make_index())
        rust_out = _run_rust(tmp_path, "failures")
        py_out = _run_python(tmp_path, "failures")
        assert "No failure patterns" in rust_out
        assert "No failure patterns" in py_out

    def test_prefers_fix_over_solution_both_paths(self, tmp_path):
        """Both Rust and Python must show 'fix' field, not 'solution', for learnings."""
        index = _make_index(learnings=[{
            "title": "Use SSH",
            "category": "git",
            "description": "HTTPS tokens expire",
            "solution": "git remote set-url origin git@github.com:org/repo.git",
            "fix": "Always use SSH remotes — they don't expire like HTTPS tokens.",
        }])
        _write_index(tmp_path, index)
        rust_out = _run_rust(tmp_path, "failures")
        py_out = _run_python(tmp_path, "failures")

        for label, output in [("rust", rust_out), ("python", py_out)]:
            assert "Always use SSH remotes" in output, f"{label}: fix field not shown"
            assert "git remote set-url" not in output, f"{label}: raw solution leaked"

    def test_truncates_multiline_fix_both_paths(self, tmp_path):
        """Both implementations must truncate multi-line fix/solution to first line + '...'"""
        index = _make_index(learnings=[{
            "title": "Multi-step auth fix",
            "category": "auth",
            "description": "Complex multi-step issue",
            "solution": "step one\nstep two\nstep three",
        }])
        _write_index(tmp_path, index)
        rust_out = _run_rust(tmp_path, "failures")
        py_out = _run_python(tmp_path, "failures")

        for label, output in [("rust", rust_out), ("python", py_out)]:
            assert "step one..." in output, f"{label}: first line + ellipsis missing"
            assert "step two" not in output, f"{label}: second line leaked"

    def test_failure_patterns_shown_both_paths(self, tmp_path):
        """Both paths must display failure pattern categories."""
        index = _make_index(failure_patterns={
            "git_error": [
                {"command": "git push", "date": "2026-01-01", "error": "fatal: denied"}
            ]
        })
        _write_index(tmp_path, index)
        rust_out = _run_rust(tmp_path, "failures")
        py_out = _run_python(tmp_path, "failures")

        for label, output in [("rust", rust_out), ("python", py_out)]:
            assert "Git Error" in output, f"{label}: pattern category missing"
            assert "git push" in output, f"{label}: command missing"
