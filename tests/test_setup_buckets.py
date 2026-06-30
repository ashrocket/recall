#!/usr/bin/env python3
"""Tests for migrations/setup-buckets.py."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_setup_buckets():
    spec = importlib.util.spec_from_file_location(
        "setup_buckets",
        Path(__file__).resolve().parent.parent / "migrations" / "setup-buckets.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    with mock.patch("sys.stdout", buf):
        rv = fn(*args, **kwargs)
    return rv, buf.getvalue()


# ---------------------------------------------------------------------------
# discover_projects
# ---------------------------------------------------------------------------

class TestDiscoverProjects:
    def test_finds_folders_with_recall_index(self, tmp_path):
        mod = _import_setup_buckets()
        (tmp_path / "proj-a").mkdir()
        (tmp_path / "proj-a" / "recall-index.json").write_text("{}")
        (tmp_path / "proj-b").mkdir()  # no recall-index.json

        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path):
            result = mod.discover_projects()
        assert result == ["proj-a"]

    def test_returns_sorted_list(self, tmp_path):
        mod = _import_setup_buckets()
        for name in ["zzz-proj", "aaa-proj", "mmm-proj"]:
            (tmp_path / name).mkdir()
            (tmp_path / name / "recall-index.json").write_text("{}")

        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path):
            result = mod.discover_projects()
        assert result == sorted(result)

    def test_empty_when_dir_missing(self, tmp_path):
        mod = _import_setup_buckets()
        missing_dir = tmp_path / "nonexistent"
        with mock.patch.object(mod, "PROJECTS_DIR", missing_dir):
            result = mod.discover_projects()
        assert result == []


# ---------------------------------------------------------------------------
# load_existing_config
# ---------------------------------------------------------------------------

class TestLoadExistingConfig:
    def test_loads_valid_json(self, tmp_path):
        mod = _import_setup_buckets()
        config = {"default_bucket": "work", "project_map": {}}
        config_file = tmp_path / "recall-buckets.json"
        config_file.write_text(json.dumps(config))
        with mock.patch.object(mod, "BUCKETS_CONFIG_PATH", config_file):
            result = mod.load_existing_config()
        assert result["default_bucket"] == "work"

    def test_returns_empty_when_missing(self, tmp_path):
        mod = _import_setup_buckets()
        missing = tmp_path / "missing.json"
        with mock.patch.object(mod, "BUCKETS_CONFIG_PATH", missing):
            result = mod.load_existing_config()
        assert result == {}

    def test_returns_empty_on_invalid_json(self, tmp_path):
        mod = _import_setup_buckets()
        config_file = tmp_path / "recall-buckets.json"
        config_file.write_text("not json {{{")
        with mock.patch.object(mod, "BUCKETS_CONFIG_PATH", config_file):
            result = mod.load_existing_config()
        assert result == {}


# ---------------------------------------------------------------------------
# main (integration)
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_projects_exits_early(self, tmp_path):
        mod = _import_setup_buckets()
        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path / "empty"):
            _, output = _capture(mod.main)
        assert "No projects" in output

    def test_dry_run_prints_json_not_writes(self, tmp_path):
        mod = _import_setup_buckets()
        proj_dir = tmp_path / "projects" / "-Users-alice-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "recall-index.json").write_text("{}")
        config_file = tmp_path / "recall-buckets.json"

        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path / "projects"), \
             mock.patch.object(mod, "BUCKETS_CONFIG_PATH", config_file), \
             mock.patch("sys.argv", ["setup-buckets.py", "--dry-run"]):
            _, output = _capture(mod.main)

        assert not config_file.exists()  # not written in dry-run
        assert "Dry run" in output
        assert "-Users-alice-myapp" in output

    def test_writes_config_for_new_projects(self, tmp_path):
        mod = _import_setup_buckets()
        proj_dir = tmp_path / "projects" / "-Users-alice-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "recall-index.json").write_text("{}")
        config_file = tmp_path / "recall-buckets.json"

        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path / "projects"), \
             mock.patch.object(mod, "BUCKETS_CONFIG_PATH", config_file), \
             mock.patch("sys.argv", ["setup-buckets.py"]):
            _, output = _capture(mod.main)

        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert "-Users-alice-myapp" in data["project_map"]

    def test_no_changes_needed_when_all_projects_already_mapped(self, tmp_path):
        """When all discovered projects are already in the map, prints 'No changes needed'."""
        mod = _import_setup_buckets()
        proj_dir = tmp_path / "projects" / "proj-a"
        proj_dir.mkdir(parents=True)
        (proj_dir / "recall-index.json").write_text("{}")

        config_file = tmp_path / "recall-buckets.json"
        existing = {"default_bucket": "personal", "buckets": {}, "project_map": {"proj-a": "work"}}
        config_file.write_text(json.dumps(existing))

        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path / "projects"), \
             mock.patch.object(mod, "BUCKETS_CONFIG_PATH", config_file), \
             mock.patch("sys.argv", ["setup-buckets.py"]):
            _, output = _capture(mod.main)

        assert "No changes needed" in output

    def test_preserves_existing_assignments(self, tmp_path):
        mod = _import_setup_buckets()
        proj_dir_a = tmp_path / "projects" / "proj-a"
        proj_dir_b = tmp_path / "projects" / "proj-b"
        proj_dir_a.mkdir(parents=True)
        proj_dir_b.mkdir(parents=True)
        (proj_dir_a / "recall-index.json").write_text("{}")
        (proj_dir_b / "recall-index.json").write_text("{}")

        config_file = tmp_path / "recall-buckets.json"
        existing = {"default_bucket": "personal", "buckets": {}, "project_map": {"proj-a": "work"}}
        config_file.write_text(json.dumps(existing))

        with mock.patch.object(mod, "PROJECTS_DIR", tmp_path / "projects"), \
             mock.patch.object(mod, "BUCKETS_CONFIG_PATH", config_file), \
             mock.patch("sys.argv", ["setup-buckets.py"]):
            _, output = _capture(mod.main)

        data = json.loads(config_file.read_text())
        assert data["project_map"]["proj-a"] == "work"   # preserved
        assert data["project_map"]["proj-b"] == "personal"  # defaulted
