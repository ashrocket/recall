import json
import pytest
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.session_start_helpers import collect_todays_sessions, format_session_picker, _project_short_name


def _make_index(sessions_dir: Path, sessions: dict):
    index_file = sessions_dir / "recall-index.json"
    index_file.write_text(json.dumps({"version": 2, "sessions": sessions}))


class TestCollectTodaysSessions:
    def test_returns_empty_when_no_projects_dir(self, tmp_path):
        result = collect_todays_sessions(projects_dir=tmp_path / "nonexistent")
        assert result == []

    def test_returns_todays_sessions(self, tmp_path):
        today = datetime.now().strftime("%Y-%m-%d")
        proj = tmp_path / "myapp"
        proj.mkdir()
        _make_index(proj, {
            "abc": {"date": f"{today}T10:00:00", "summary": "Fixing payroll bug"},
            "def": {"date": f"{today}T11:00:00", "summary": "Second session today"},
        })

        result = collect_todays_sessions(projects_dir=tmp_path)
        assert len(result) == 1
        assert result[0]["session_count"] == 2
        assert "payroll" in result[0]["summary"] or "Second" in result[0]["summary"]

    def test_skips_projects_without_index(self, tmp_path):
        (tmp_path / "no-index-proj").mkdir()
        result = collect_todays_sessions(projects_dir=tmp_path)
        assert result == []

    def test_skips_non_directory_entries(self, tmp_path):
        """Files (not dirs) in the projects root are silently skipped."""
        (tmp_path / "stray-file.txt").write_text("not a project")
        result = collect_todays_sessions(projects_dir=tmp_path)
        assert result == []

    def test_skips_index_with_empty_sessions(self, tmp_path):
        """Index file that exists but has no sessions is skipped."""
        proj = tmp_path / "empty-proj"
        proj.mkdir()
        _make_index(proj, {})  # valid JSON but no sessions
        result = collect_todays_sessions(projects_dir=tmp_path)
        assert result == []

    def test_skips_corrupt_index(self, tmp_path):
        proj = tmp_path / "corrupt-proj"
        proj.mkdir()
        (proj / "recall-index.json").write_text("not valid json {{{")
        result = collect_todays_sessions(projects_dir=tmp_path)
        assert result == []

    def test_skips_old_sessions(self, tmp_path):
        proj = tmp_path / "old-proj"
        proj.mkdir()
        _make_index(proj, {"abc": {"date": "2020-01-01T10:00:00", "summary": "Ancient session"}})
        result = collect_todays_sessions(projects_dir=tmp_path)
        assert result == []


class TestProjectShortName:
    def test_resolves_real_filesystem_path(self, tmp_path):
        # Create a real directory and use its encoded form
        app_dir = tmp_path / "my-app"
        app_dir.mkdir()
        # Encode tmp_path / "my-app" as the folder string (replace / with -)
        folder = str(app_dir).lstrip("/").replace("/", "-")
        result = _project_short_name(folder)
        assert result == "my-app"

    def test_fallback_to_last_segment_when_path_not_found(self):
        # Path that definitely doesn't exist on disk
        result = _project_short_name("-nonexistent-path-myproject")
        assert result == "myproject"


class TestFormatSessionPicker:
    def test_returns_empty_string_for_no_sessions(self):
        result = format_session_picker([])
        assert result == ""

    def test_formats_sessions_list(self):
        sessions = [
            {"project_folder": "-Users-ash-myapp", "session_count": 3, "summary": "Fixing payroll"},
        ]
        result = format_session_picker(sessions)
        assert "Today's sessions" in result
        assert "3 sessions" in result
        assert "Fixing payroll" in result
        assert "Enter to skip" in result


class TestCollectTodaysSessionsDefaultPath:
    def test_uses_default_projects_dir_when_none(self, tmp_path):
        """When projects_dir is None, defaults to ~/.claude/projects."""
        from unittest.mock import patch
        with patch("lib.session_start_helpers.Path") as mock_path_cls:
            mock_home = mock_path_cls.return_value = tmp_path
            mock_path_cls.home.return_value = tmp_path
            # The default path doesn't exist → returns []
            result = collect_todays_sessions(projects_dir=None)
        assert isinstance(result, list)
