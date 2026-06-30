import pytest
from datetime import datetime
from pathlib import Path


def test_restart_to_yaml():
    from lib.sync_format import restart_to_yaml, yaml_to_restart
    restart = {
        "name": "payroll-fix",
        "date": "2026-03-20",
        "project": "myapp",
        "branch": "feature/payroll-fix",
        "summary": "Fixing payroll bonus calculation",
        "next_steps": "Fix rounding edge case on line 247",
        "content": "Full restart prompt content here...",
    }
    yaml_str = restart_to_yaml(restart)
    assert "name: payroll-fix" in yaml_str
    assert "content:" in yaml_str
    parsed = yaml_to_restart(yaml_str)
    assert parsed["name"] == "payroll-fix"
    assert parsed["content"] == "Full restart prompt content here..."


def test_learning_to_yaml():
    from lib.sync_format import learning_to_yaml, yaml_to_learning
    learning = {
        "bucket": "personal",
        "category": "git",
        "title": "SSH vs HTTPS remotes",
        "description": "HTTPS tokens expire; SSH keys are persistent",
        "solution": "git remote set-url origin git@github.com:org/repo.git",
    }
    yaml_str = learning_to_yaml(learning)
    parsed = yaml_to_learning(yaml_str)
    assert parsed["bucket"] == "personal"
    assert parsed["title"] == "SSH vs HTTPS remotes"


def test_session_metadata_to_yaml():
    from lib.sync_format import session_meta_to_yaml, yaml_to_session_meta
    meta = {
        "session_id": "abc123",
        "date": "2026-03-20T09:41:00",
        "project": "myapp",
        "summary": "Implementing payroll bonus fix",
        "message_count": 34,
        "command_count": 12,
        "failure_count": 2,
        "topics": ["payroll", "rounding"],
        "source_platform": "claude-code",
        "source_machine": "ashbook-pro",
    }
    yaml_str = session_meta_to_yaml(meta)
    parsed = yaml_to_session_meta(yaml_str)
    assert parsed["session_id"] == "abc123"
    assert parsed["source_platform"] == "claude-code"
    assert parsed["topics"] == ["payroll", "rounding"]


def test_sop_to_yaml():
    from lib.sync_format import sop_to_yaml, yaml_to_sop
    sop = {
        "category": "git_error",
        "pattern": "permission denied on push",
        "solution": "Switch HTTPS to SSH remote",
        "commands": ["git remote set-url origin git@github.com:org/repo.git"],
    }
    yaml_str = sop_to_yaml(sop)
    parsed = yaml_to_sop(yaml_str)
    assert parsed["category"] == "git_error"


def test_agent_config_to_yaml():
    from lib.sync_format import agent_config_to_yaml, yaml_to_agent_config
    snapshot = {
        "file": "CLAUDE.md",
        "project": "myapp",
        "snapshot_date": "2026-03-30T08:01:00",
        "session_id": "abc123",
        "changed_by": "agent:claude-opus-4-6",
        "diff_summary": "Added 3 rules about ArangoDB",
        "content": "# CLAUDE.md\n\nRules here...",
    }
    yaml_str = agent_config_to_yaml(snapshot)
    parsed = yaml_to_agent_config(yaml_str)
    assert parsed["file"] == "CLAUDE.md"
    assert parsed["changed_by"] == "agent:claude-opus-4-6"
    assert "Rules here..." in parsed["content"]


def test_sync_filename_format():
    from lib.sync_format import sync_filename
    result = sync_filename("restart", "payroll fix", "2026-03-20")
    assert result == "2026-03-20_payroll-fix.yaml"


def test_sync_filename_truncates_long_name():
    from lib.sync_format import sync_filename
    long_name = "a" * 100
    result = sync_filename("restart", long_name, "2026-03-20")
    assert len(result) <= len("2026-03-20_") + 60 + len(".yaml")


def test_sync_filename_short_date_used_as_is():
    from lib.sync_format import sync_filename
    result = sync_filename("restart", "my session", "2026-04")
    assert result.startswith("2026-04_")
