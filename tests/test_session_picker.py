#!/usr/bin/env python3
"""Tests for session picker helpers (lib/session_start_helpers.py)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Ensure lib/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.session_start_helpers import collect_todays_sessions, format_session_picker


# ---------------------------------------------------------------------------
# Helpers to build fake project dirs with recall-index.json
# ---------------------------------------------------------------------------

def _make_index(sessions: dict) -> dict:
    """Return a minimal recall-index with the given sessions dict."""
    return {
        "version": 2,
        "sessions": sessions,
        "failure_patterns": {},
        "learnings": [],
    }


def _write_index(projects_dir: Path, folder_name: str, index: dict):
    """Write a recall-index.json inside projects_dir/folder_name/."""
    proj = projects_dir / folder_name
    proj.mkdir(parents=True, exist_ok=True)
    with open(proj / "recall-index.json", "w") as f:
        json.dump(index, f)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _encoded_path(path: Path) -> str:
    """Encode an absolute path the same way project_folder values are stored."""
    return "-" + "-".join(path.resolve().parts[1:])


# ---------------------------------------------------------------------------
# test_finds_todays_sessions
# ---------------------------------------------------------------------------

class TestCollectTodaysSessions:
    """Tests for collect_todays_sessions()."""

    def test_finds_todays_sessions(self, tmp_path):
        """Sessions from today are returned with correct structure."""
        today = _today_str()
        _write_index(tmp_path, "-Users-ash-ashcode-recall", _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": "Worked on session picker"},
            "s2": {"date": f"{today}T14:00:00", "summary": "Fixed tests"},
        }))
        _write_index(tmp_path, "-Users-ash-ashcode-demoapp", _make_index({
            "s3": {"date": f"{today}T09:00:00", "summary": "Demoapp prompt update"},
        }))

        result = collect_todays_sessions(tmp_path)

        assert len(result) == 2
        # Sorted by session_count descending — recall has 2, demoapp has 1
        assert result[0]["session_count"] == 2
        assert result[0]["project_folder"] == "-Users-ash-ashcode-recall"
        assert result[1]["session_count"] == 1
        assert result[1]["project_folder"] == "-Users-ash-ashcode-demoapp"

    def test_ignores_old_sessions(self, tmp_path):
        """Sessions from yesterday are not included."""
        yesterday = _yesterday_str()
        _write_index(tmp_path, "-Users-ash-old-project", _make_index({
            "s1": {"date": f"{yesterday}T10:00:00", "summary": "Old work"},
        }))

        result = collect_todays_sessions(tmp_path)
        assert result == []

    def test_empty_when_no_sessions_today(self, tmp_path):
        """Empty projects_dir returns empty list."""
        result = collect_todays_sessions(tmp_path)
        assert result == []

    def test_mixed_today_and_old(self, tmp_path):
        """Project with mix of today and old sessions only counts today's."""
        today = _today_str()
        yesterday = _yesterday_str()
        _write_index(tmp_path, "-Users-ash-ashcode-mixed", _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": "Today's work"},
            "s2": {"date": f"{yesterday}T10:00:00", "summary": "Yesterday's work"},
        }))

        result = collect_todays_sessions(tmp_path)
        assert len(result) == 1
        assert result[0]["session_count"] == 1
        assert result[0]["summary"] == "Today's work"

    def test_summary_from_most_recent_session(self, tmp_path):
        """Summary is taken from the most recent session of the day."""
        today = _today_str()
        _write_index(tmp_path, "-Users-ash-ashcode-project", _make_index({
            "s1": {"date": f"{today}T08:00:00", "summary": "Morning session"},
            "s2": {"date": f"{today}T16:00:00", "summary": "Afternoon session with a lot more detail"},
        }))

        result = collect_todays_sessions(tmp_path)
        assert len(result) == 1
        assert result[0]["summary"].startswith("Afternoon session")

    def test_summary_truncated_to_80_chars(self, tmp_path):
        """Summary is truncated to 80 characters."""
        today = _today_str()
        long_summary = "A" * 200
        _write_index(tmp_path, "-Users-ash-ashcode-project", _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": long_summary},
        }))

        result = collect_todays_sessions(tmp_path)
        assert len(result[0]["summary"]) <= 80

    def test_skips_corrupt_index(self, tmp_path):
        """Corrupt JSON files are silently skipped."""
        today = _today_str()
        # Write a corrupt file
        bad_proj = tmp_path / "-Users-ash-broken"
        bad_proj.mkdir(parents=True)
        with open(bad_proj / "recall-index.json", "w") as f:
            f.write("{corrupt json!!!")

        # Write a good one
        _write_index(tmp_path, "-Users-ash-good", _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": "Good project"},
        }))

        result = collect_todays_sessions(tmp_path)
        assert len(result) == 1
        assert result[0]["project_folder"] == "-Users-ash-good"


# ---------------------------------------------------------------------------
# test_project_name_extraction
# ---------------------------------------------------------------------------

class TestProjectNameExtraction:
    """Verify short name extraction from project_folder strings."""

    def test_project_name_resolves_real_path(self, tmp_path):
        """When the encoded path exists on disk, the real dir name is used."""
        # Use the actual repo path which exists on this machine
        today = _today_str()
        repo_root = Path(__file__).resolve().parent.parent
        folder = _encoded_path(repo_root)
        _write_index(tmp_path, folder, _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": "Test"},
        }))

        result = collect_todays_sessions(tmp_path)
        output = format_session_picker(result)
        # The encoded path resolves back to the real checkout, so the
        # basename from the filesystem should be used.
        assert repo_root.name in output

    def test_fallback_uses_last_segment(self, tmp_path):
        """When the encoded path doesn't exist, falls back to last dash segment."""
        today = _today_str()
        # This path doesn't exist on disk
        _write_index(tmp_path, "-nonexistent-fake-path-myapp", _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": "Fake project"},
        }))

        result = collect_todays_sessions(tmp_path)
        output = format_session_picker(result)
        assert "myapp" in output

    def test_deeply_nested_project_name(self, tmp_path):
        """Deeply nested non-existent paths still extract the last segment."""
        today = _today_str()
        _write_index(tmp_path, "-nonexistent-code-projects-deep-myapp", _make_index({
            "s1": {"date": f"{today}T10:00:00", "summary": "Deep project"},
        }))

        result = collect_todays_sessions(tmp_path)
        output = format_session_picker(result)
        assert "myapp" in output


# ---------------------------------------------------------------------------
# test_formats_picker_output
# ---------------------------------------------------------------------------

class TestFormatSessionPicker:
    """Tests for format_session_picker()."""

    def test_formats_picker_output(self):
        """Output has numbered lines and expected structure."""
        repo_root = Path(__file__).resolve().parent.parent
        sessions = [
            {"project_folder": _encoded_path(repo_root), "session_count": 3, "summary": "Session picker work"},
            {"project_folder": "-Users-exampleuser-ashcode-demoapp", "session_count": 1, "summary": "Demoapp updates"},
        ]
        output = format_session_picker(sessions)

        assert "No session history for this directory." in output
        assert "Today's sessions:" in output
        assert "1." in output
        assert "2." in output
        assert repo_root.name in output
        assert "demoapp" in output
        assert "[3 sessions]" in output
        assert "[1 sessions]" in output
        assert "Resume context from which project?" in output

    def test_empty_sessions_list(self):
        """Empty list returns empty string (no picker to show)."""
        output = format_session_picker([])
        assert output == ""

    def test_single_session_project(self):
        """Single project still formats correctly."""
        sessions = [
            {"project_folder": "-Users-ash-ashcode-myproject", "session_count": 1, "summary": "Initial work"},
        ]
        output = format_session_picker(sessions)

        assert "1." in output
        assert "myproject" in output
        assert "2." not in output
