import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch


def _init_bare_repo(path: Path) -> str:
    """Create a bare git repo for testing."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True)
    return str(path)


def test_git_provider_init(tmp_path):
    """Init creates a local clone of the sync repo."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)

    assert (local / ".git").exists()


def test_git_provider_push(tmp_path):
    """Push writes files to the git repo and commits."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)

    files = [{
        "relative_path": "restarts/test.yaml",
        "absolute_path": None,
        "content": b"name: test\n",
        "secret_findings": [],
    }]
    result = provider.push(files, config)
    assert result["pushed"] == 1
    assert result["errors"] == []

    assert (local / "restarts" / "test.yaml").exists()


def test_git_provider_pull(tmp_path):
    """Pull retrieves files from remote."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    config = SyncConfig(provider="github", repo=bare)

    # Push from clone A
    clone_a = tmp_path / "clone_a"
    provider_a = GitProvider(local_dir=clone_a)
    provider_a.init(config)
    files = [{
        "relative_path": "restarts/from_a.yaml",
        "absolute_path": None,
        "content": b"name: from_a\n",
        "secret_findings": [],
    }]
    provider_a.push(files, config)

    # Pull from clone B
    clone_b = tmp_path / "clone_b"
    provider_b = GitProvider(local_dir=clone_b)
    provider_b.init(config)
    pulled = provider_b.pull(since=None, config=config)

    assert len(pulled) >= 1
    paths = [p["path"] for p in pulled]
    assert "restarts/from_a.yaml" in paths


def test_git_provider_pull_skips_dotfiles(tmp_path):
    """pull() skips yaml files whose relative path starts with '.'."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig
    from unittest.mock import patch

    local = tmp_path / "local"
    local.mkdir()
    # Normal file and a hidden dotfile yaml
    (local / "real.yaml").write_bytes(b"name: real\n")
    (local / ".hidden.yaml").write_bytes(b"secret: yes\n")

    provider = GitProvider(local_dir=local)
    config = SyncConfig(provider="github")

    with patch.object(provider, "_git_in_repo"):
        pulled = provider.pull(since=None, config=config)

    paths = [f["path"] for f in pulled]
    assert "real.yaml" in paths
    assert ".hidden.yaml" not in paths


def test_git_provider_status(tmp_path):
    """Status returns provider metadata and initialization state."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    local = tmp_path / "local"
    config = SyncConfig(provider="github")
    provider = GitProvider(local_dir=local)
    result = provider.status(config)

    assert result["provider"] == "git"
    assert str(local) in result["local_dir"]
    assert result["initialized"] is False  # .git doesn't exist yet


def test_git_provider_init_falls_back_when_clone_fails(tmp_path):
    """When clone fails (empty repo), init falls back to git init + remote add."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo="https://github.com/user/repo.git")
    provider = GitProvider(local_dir=local)

    fail = subprocess.CompletedProcess([], returncode=1, stdout="", stderr="err")
    ok = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=[fail, ok, ok]) as mock_run:
        provider.init(config)

    assert mock_run.call_count == 3
    assert "init" in mock_run.call_args_list[1][0][0]
    assert "remote" in mock_run.call_args_list[2][0][0]


def test_git_provider_init_noop_when_already_initialized(tmp_path):
    """Init is a no-op when .git already exists."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)  # first init
    first_mtime = (local / ".git").stat().st_mtime

    provider.init(config)  # second call should be a no-op
    second_mtime = (local / ".git").stat().st_mtime

    assert first_mtime == second_mtime


def test_git_provider_push_no_files_returns_zero(tmp_path):
    """Push with empty file list returns pushed=0 without committing."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)

    result = provider.push([], config)
    assert result["pushed"] == 0
    assert result["errors"] == []


def test_git_provider_push_records_error_on_exception(tmp_path):
    """Push captures per-file error when _git_in_repo raises."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)

    files = [{
        "relative_path": "test.yaml",
        "absolute_path": None,
        "content": b"data",
        "secret_findings": [],
    }]

    with patch.object(provider, "_git_in_repo", side_effect=Exception("git add failed")):
        result = provider.push(files, config)

    assert result["pushed"] == 0
    assert len(result["errors"]) == 1
    assert "git add failed" in result["errors"][0]["error"]


def test_push_to_remote_fallback_on_both_push_failures(tmp_path):
    """When both git push attempts fail, an error is appended."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo="/nonexistent")

    fail_rev = subprocess.CompletedProcess([], returncode=1, stdout="", stderr="")
    fail_push = subprocess.CompletedProcess([], returncode=1, stdout="", stderr="remote: denied")

    provider = GitProvider(local_dir=local)
    errors = []
    with patch("subprocess.run", side_effect=[fail_rev, fail_push, fail_push]):
        provider._push_to_remote(errors)

    assert len(errors) == 1
    assert "remote: denied" in errors[0]["error"]


def test_push_to_remote_fallback_uses_main_when_branch_is_master(tmp_path):
    """When current branch is 'master', fallback uses 'main'."""
    from lib.sync_git import GitProvider

    local = tmp_path / "local"
    provider = GitProvider(local_dir=local)

    ok_rev = subprocess.CompletedProcess([], returncode=0, stdout="master", stderr="")
    fail_push = subprocess.CompletedProcess([], returncode=1, stdout="", stderr="")
    ok_fallback = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")

    errors = []
    with patch("subprocess.run", side_effect=[ok_rev, fail_push, ok_fallback]) as mock_run:
        provider._push_to_remote(errors)

    assert errors == []
    # Third call should push HEAD:main (the fallback when branch is "master")
    third_call_args = mock_run.call_args_list[2][0][0]
    assert "HEAD:main" in third_call_args


def test_git_provider_default_local_dir():
    """GitProvider() with no args uses ~/.local/share/recall/sync."""
    from lib.sync_git import GitProvider
    provider = GitProvider()
    assert provider.local_dir == Path.home() / ".local" / "share" / "recall" / "sync"
