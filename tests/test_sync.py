import pytest
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime


def test_provider_interface():
    """Provider adapters must implement push, pull, status."""
    from lib.sync import SyncProvider
    with pytest.raises(TypeError):
        SyncProvider()


def test_gather_sync_files(tmp_path):
    """Gather files from local recall data for push."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "2026-03-20_payroll-fix.yaml").write_text("name: payroll-fix\n")
    (restarts / "2026-03-28_auth-refactor.yaml").write_text("name: auth-refactor\n")

    learnings = tmp_path / "learnings"
    learnings.mkdir()
    (learnings / "2026-03-15_git-ssh.yaml").write_text("title: SSH vs HTTPS\n")

    config = SyncConfig(include=SyncInclude(restarts=True, learnings=True))
    files = gather_sync_files(tmp_path, config)

    assert len(files) == 3
    paths = [f["relative_path"] for f in files]
    assert "restarts/2026-03-20_payroll-fix.yaml" in paths
    assert "learnings/2026-03-15_git-ssh.yaml" in paths


def test_gather_respects_include_flags(tmp_path):
    """Disabled categories are not gathered."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "file.yaml").write_text("x: 1\n")

    learnings = tmp_path / "learnings"
    learnings.mkdir()
    (learnings / "file.yaml").write_text("x: 1\n")

    config = SyncConfig(include=SyncInclude(restarts=True, learnings=False))
    files = gather_sync_files(tmp_path, config)

    paths = [f["relative_path"] for f in files]
    assert any("restarts" in p for p in paths)
    assert not any("learnings" in p for p in paths)


def test_gather_respects_recallignore(tmp_path):
    """Files matching .recallignore are excluded."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "safe.yaml").write_text("x: 1\n")
    (restarts / "secret-project.yaml").write_text("x: 1\n")

    ignore = tmp_path / ".recallignore"
    ignore.write_text("restarts/secret-*\n")

    config = SyncConfig(include=SyncInclude(restarts=True))
    files = gather_sync_files(tmp_path, config, ignore_path=ignore)

    paths = [f["relative_path"] for f in files]
    assert "restarts/safe.yaml" in paths
    assert "restarts/secret-project.yaml" not in paths


def test_gather_runs_secret_scan(tmp_path):
    """Files with detected secrets are flagged."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "dirty.yaml").write_text("token: ghp_ABCDEFghijklmnop1234567890abcdef\n")

    config = SyncConfig(secret_scan="strict", include=SyncInclude(restarts=True))
    files = gather_sync_files(tmp_path, config)

    assert len(files) == 1
    assert files[0]["secret_findings"]


def test_gather_skips_secret_scan_when_off(tmp_path):
    """When secret_scan is 'off', all files are gathered with empty findings."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "dirty.yaml").write_text("token: ghp_ABCDEFghijklmnop1234567890abcdef\n")

    config = SyncConfig(secret_scan="off", include=SyncInclude(restarts=True))
    files = gather_sync_files(tmp_path, config)

    assert len(files) == 1
    assert files[0]["secret_findings"] == []


def test_get_provider_raises_for_unknown():
    """get_provider raises ValueError for an unregistered provider name."""
    from lib.sync import get_provider
    with pytest.raises(ValueError, match="Unknown sync provider"):
        get_provider("__nonexistent_provider__")
