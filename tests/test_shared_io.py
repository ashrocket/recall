#!/usr/bin/env python3
"""Tests for lib/shared.py I/O functions: load_index, save_index, load_session_details, load_agents."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.shared import (
    load_index,
    save_index,
    load_session_details,
    load_agents,
    save_agents,
    _new_empty_index,
    get_project_dir,
    get_restarts_dir,
    read_session_title,
)


# ---------------------------------------------------------------------------
# _new_empty_index
# ---------------------------------------------------------------------------

class TestNewEmptyIndex:
    def test_has_required_keys(self):
        idx = _new_empty_index("myapp")
        for key in ("version", "sessions", "failure_patterns", "learnings", "pending_learnings", "usage"):
            assert key in idx

    def test_project_key_set(self):
        idx = _new_empty_index("myapp")
        assert idx["project"] == "myapp"

    def test_mutable_values_are_independent(self):
        a = _new_empty_index("a")
        b = _new_empty_index("b")
        a["sessions"]["x"] = 1
        assert "x" not in b["sessions"]


# ---------------------------------------------------------------------------
# load_index / save_index
# ---------------------------------------------------------------------------

class TestLoadSaveIndex:
    def test_save_then_load_roundtrip(self, tmp_path):
        index = {"version": 2, "sessions": {"s1": {"summary": "fix bug"}}, "failure_patterns": {}, "learnings": [], "pending_learnings": [], "usage": {}}
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            save_index(index, "proj")
            result = load_index("proj")
        assert result["sessions"]["s1"]["summary"] == "fix bug"

    def test_load_returns_none_when_missing(self, tmp_path):
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = load_index("proj")
        assert result is None

    def test_load_creates_empty_index_when_flag_set(self, tmp_path):
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = load_index("proj", create_if_missing=True)
        assert result is not None
        assert result["sessions"] == {}

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        index_file = tmp_path / "recall-index.json"
        index_file.write_text("not valid json{{{")
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = load_index("proj")
        assert result is None

    def test_load_creates_empty_index_on_corrupt_json_when_flag_set(self, tmp_path):
        """Corrupt file + create_if_missing=True falls through to return empty index."""
        index_file = tmp_path / "recall-index.json"
        index_file.write_text("{bad json")
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            result = load_index("proj", create_if_missing=True)
        assert result is not None
        assert result["sessions"] == {}

    def test_save_calls_prune_fn(self, tmp_path):
        index = {"version": 2, "sessions": {}, "failure_patterns": {}, "learnings": [], "pending_learnings": [], "usage": {}}
        pruned = {}
        prune_called = []

        def prune_fn(idx):
            prune_called.append(True)
            return idx

        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            save_index(index, "proj", prune_fn=prune_fn)

        assert prune_called

    def test_save_derives_project_folder_when_none(self, tmp_path):
        """When project_folder is None, save_index calls get_project_folder() to derive it."""
        index = {"version": 2, "sessions": {}, "failure_patterns": {}, "learnings": []}
        with mock.patch("lib.shared.get_project_folder", return_value="auto-proj") as mock_gpf, \
             mock.patch("lib.shared.get_project_dir", return_value=tmp_path):
            save_index(index)  # no project_folder argument
        mock_gpf.assert_called_once()


class TestGetProjectDir:
    def test_derives_folder_when_none(self, tmp_path):
        """When project_folder is None, get_project_dir calls get_project_folder()."""
        from lib.shared import get_project_dir
        with mock.patch("lib.shared.get_project_folder", return_value="auto-proj") as mock_gpf:
            result = get_project_dir(None)
        mock_gpf.assert_called_once()
        assert str(result).endswith("auto-proj")


# ---------------------------------------------------------------------------
# load_session_details
# ---------------------------------------------------------------------------

class TestLoadSessionDetails:
    def test_loads_existing_detail_file(self, tmp_path):
        details = {"user_messages": ["hello"], "commands": []}
        details_dir = tmp_path / "recall-sessions"
        details_dir.mkdir()
        (details_dir / "session123.json").write_text(json.dumps(details))

        with mock.patch("lib.shared.get_session_details_dir", return_value=details_dir):
            result = load_session_details("proj", "session123")

        assert result["user_messages"] == ["hello"]

    def test_returns_none_when_missing(self, tmp_path):
        details_dir = tmp_path / "recall-sessions"
        details_dir.mkdir()

        with mock.patch("lib.shared.get_session_details_dir", return_value=details_dir):
            result = load_session_details("proj", "nonexistent")

        assert result is None

    def test_returns_none_on_corrupt_json(self, tmp_path):
        details_dir = tmp_path / "recall-sessions"
        details_dir.mkdir()
        (details_dir / "bad.json").write_text("{invalid")

        with mock.patch("lib.shared.get_session_details_dir", return_value=details_dir):
            result = load_session_details("proj", "bad")

        assert result is None


# ---------------------------------------------------------------------------
# load_agents / save_agents
# ---------------------------------------------------------------------------

class TestLoadSaveAgents:
    def test_save_then_load_roundtrip(self, tmp_path):
        agents = [{"id": 1, "summary": "deploy job"}]
        agents_file = tmp_path / "agents.json"

        with mock.patch("lib.shared.get_agents_file", return_value=agents_file):
            save_agents(agents, "proj")
            result = load_agents("proj")

        assert len(result) == 1
        assert result[0]["summary"] == "deploy job"

    def test_load_returns_empty_when_missing(self, tmp_path):
        agents_file = tmp_path / "agents.json"
        with mock.patch("lib.shared.get_agents_file", return_value=agents_file):
            result = load_agents("proj")
        assert result == []

    def test_load_returns_empty_on_corrupt_json(self, tmp_path):
        agents_file = tmp_path / "agents.json"
        agents_file.write_text("{not a list}")

        with mock.patch("lib.shared.get_agents_file", return_value=agents_file):
            result = load_agents("proj")

        assert result == []

    def test_load_returns_empty_when_file_contains_dict_not_list(self, tmp_path):
        """load_agents returns [] when the file is valid JSON but not a list."""
        import json
        agents_file = tmp_path / "agents.json"
        agents_file.write_text(json.dumps({"key": "value"}))

        with mock.patch("lib.shared.get_agents_file", return_value=agents_file):
            result = load_agents("proj")

        assert result == []


# ---------------------------------------------------------------------------
# get_restarts_dir
# ---------------------------------------------------------------------------

class TestGetRestartsDir:
    def test_returns_recall_restarts_subdir(self, tmp_path):
        with mock.patch("lib.shared.get_project_dir", return_value=tmp_path / "proj"):
            result = get_restarts_dir("proj")
        assert result == tmp_path / "proj" / "recall-restarts"

    def test_name_contains_recall_restarts(self):
        result = get_restarts_dir("myapp")
        assert "recall-restarts" in str(result)


# ---------------------------------------------------------------------------
# read_session_title
# ---------------------------------------------------------------------------

class TestReadSessionTitle:
    def test_returns_latest_custom_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text(
            '{"type":"custom-title","customTitle":"first","sessionId":"a"}\n'
            '{"type":"user","content":"hi"}\n'
            '{"type":"custom-title","customTitle":"second","sessionId":"a"}\n'
        )
        assert read_session_title(t) == "second"

    def test_returns_none_without_custom_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text(
            '{"type":"user","content":"hi"}\n'
            '{"type":"ai-title","aiTitle":"auto-generated"}\n'
        )
        assert read_session_title(t) is None

    def test_ignores_ai_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"ai-title","aiTitle":"do not use"}\n')
        assert read_session_title(t) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        assert read_session_title(tmp_path / "nope.jsonl") is None

    def test_skips_malformed_json_lines(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text('not json at all\n{"type":"custom-title","customTitle":"ok"}\n')
        assert read_session_title(t) == "ok"

    def test_ignores_empty_custom_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":""}\n')
        assert read_session_title(t) is None
