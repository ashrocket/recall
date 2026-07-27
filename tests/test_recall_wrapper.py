#!/usr/bin/env python3
"""Integration checks for the bin/recall shell dispatcher."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_restart_summary_and_delete_route_through_wrapper(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    project_folder = str(project).replace("/", "-")
    project_dir = tmp_path / ".claude" / "projects" / project_folder
    restarts_dir = project_dir / "recall-restarts"
    restarts_dir.mkdir(parents=True)

    prompt = restarts_dir / "old.prompt"
    prompt.write_text("restart here")
    agents = [
        {
            "id": 1,
            "date": "2026-07-01",
            "working_directory": str(project),
            "summary": "old checkpoint",
            "name": "Old Checkpoint",
            "prompt_file": "recall-restarts/old.prompt",
            "status": "saved",
            "role": "lead",
        }
    ]
    (project_dir / "agents.json").write_text(json.dumps(agents))

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_PROJECT_DIR"] = str(project)

    summary = subprocess.run(
        [str(ROOT / "bin" / "recall"), str(project), "restart", "summary"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Restart Summary" in summary.stdout
    assert "old-checkpoint" in summary.stdout
    assert "/recall restart delete" in summary.stdout

    deleted = subprocess.run(
        [str(ROOT / "bin" / "recall"), str(project), "restart", "delete", "1"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Deleted restart 1: old checkpoint" in deleted.stdout
    assert not prompt.exists()
    assert json.loads((project_dir / "agents.json").read_text()) == []


def test_restart_summary_uses_codex_skill_syntax(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    project_folder = str(project).replace("/", "-")
    project_dir = tmp_path / ".claude" / "projects" / project_folder
    project_dir.mkdir(parents=True)
    (project_dir / "agents.json").write_text(json.dumps([{
        "id": 1,
        "date": "2026-07-01",
        "working_directory": str(project),
        "summary": "old checkpoint",
        "status": "saved",
    }]))

    env = os.environ.copy()
    env.update({
        "HOME": str(tmp_path),
        "CLAUDE_PROJECT_DIR": str(project),
        "RECALL_AGENT": "codex",
        "RECALL_NO_FAST": "1",
    })
    summary = subprocess.run(
        [str(ROOT / "bin" / "recall"), str(project), "restart", "summary"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "$recall restart delete" in summary.stdout
    assert "/recall" not in summary.stdout


def test_restart_accepts_trailing_launch_flag(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    project_folder = str(project).replace("/", "-")
    project_dir = tmp_path / ".claude" / "projects" / project_folder
    project_dir.mkdir(parents=True)
    (project_dir / "agents.json").write_text("[]")

    env = os.environ.copy()
    env.update({
        "HOME": str(tmp_path),
        "CLAUDE_PROJECT_DIR": str(project),
        "RECALL_AGENT": "codex",
        "RECALL_NO_FAST": "1",
    })
    result = subprocess.run(
        [str(ROOT / "bin" / "recall"), str(project), "restart", "missing", "--launch"],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "No entries matching 'missing'." in result.stderr
    assert "missing --launch" not in result.stderr
