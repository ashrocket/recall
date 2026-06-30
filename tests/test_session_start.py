#!/usr/bin/env python3
"""Tests for hooks/scripts/session-start.py utility functions."""

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_session_start():
    spec = importlib.util.spec_from_file_location(
        "session_start",
        Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "session-start.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# format_time_ago
# ---------------------------------------------------------------------------

class TestFormatTimeAgo:
    def _ago(self, **kwargs) -> str:
        """Return an ISO date string for datetime.now() - kwargs timedelta."""
        dt = datetime.now() - timedelta(**kwargs)
        return dt.isoformat()

    def test_just_now(self):
        mod = _import_session_start()
        result = mod.format_time_ago(self._ago(seconds=10))
        assert result == "just now"

    def test_minutes_ago(self):
        mod = _import_session_start()
        result = mod.format_time_ago(self._ago(seconds=300))
        assert "m ago" in result
        assert result.startswith("5")

    def test_hours_ago(self):
        mod = _import_session_start()
        result = mod.format_time_ago(self._ago(seconds=7200))
        assert "h ago" in result
        assert result.startswith("2")

    def test_days_ago(self):
        mod = _import_session_start()
        result = mod.format_time_ago(self._ago(days=3))
        assert "d ago" in result
        assert result.startswith("3")

    def test_z_suffix_handled(self):
        mod = _import_session_start()
        dt = datetime.now() - timedelta(hours=1)
        result = mod.format_time_ago(dt.isoformat() + "Z")
        assert "h ago" in result or "m ago" in result

    def test_fallback_on_invalid_date(self):
        mod = _import_session_start()
        result = mod.format_time_ago("not-a-date-at-all")
        assert isinstance(result, str)
        assert len(result) <= 10  # should return first 10 chars

    def test_fallback_returns_first_10_chars(self):
        mod = _import_session_start()
        result = mod.format_time_ago("2026-04-24Tinvalid")
        assert len(result) <= 10


class TestFormatSessionContext:
    def _index(self):
        return {
            "sessions": {
                "s1": {
                    "date": (datetime.now() - timedelta(days=3)).isoformat(),
                    "summary": "Long previous-session summary that should stay out of the compact hook",
                    "failure_count": 4,
                    "user_messages": [{"content": "finish this later"}],
                },
                "s0": {
                    "date": (datetime.now() - timedelta(days=5)).isoformat(),
                    "summary": "Older work",
                    "failure_count": 1,
                },
            },
            "pending_learnings": [{"id": 1}, {"id": 2}],
            "failure_patterns": {
                "git_error": [
                    {"command": "git pull --rebase origin main"},
                    {"command": "git pull --rebase origin main"},
                ],
                "not_found": [{"command": "missing"}],
            },
        }

    def _sorted_sessions(self, index):
        return sorted(
            index["sessions"].items(),
            key=lambda x: x[1].get("date", ""),
            reverse=True,
        )

    def test_compact_context_is_single_line_without_session_dump(self):
        mod = _import_session_start()
        index = self._index()
        result = mod.format_session_context(index, self._sorted_sessions(index))

        assert result.startswith("Recall:")
        assert "\n" not in result
        assert "2 sessions indexed" in result
        assert "2 pending learnings" in result
        assert "1 recurring issue available" in result
        assert "/recall last" in result
        assert "/recall learn" in result
        assert "/recall failures" in result
        assert "Long previous-session summary" not in result
        assert "git pull --rebase" not in result
        assert "## Session Context" not in result

    def test_verbose_context_preserves_full_briefing_when_enabled(self, monkeypatch):
        mod = _import_session_start()
        index = self._index()
        monkeypatch.setenv("RECALL_SESSION_START_VERBOSE", "1")

        result = mod.format_session_context(index, self._sorted_sessions(index))

        assert result.startswith("## Session Context from /recall")
        assert "Long previous-session summary" in result
        assert "git pull --rebase" in result
