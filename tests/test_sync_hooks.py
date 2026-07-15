import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_session_end_triggers_sync_push(tmp_path, monkeypatch):
    from lib.sync_config import SyncConfig, SyncInclude
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(
        provider="cloud",
        endpoint="https://test.workers.dev",
        api_key_file=str(tmp_path / "key"),
        auto_sync=True,
    )
    (tmp_path / "key").write_text("sk_recall_test")

    mock_provider = MagicMock()
    mock_provider.push.return_value = {"pushed": 2, "errors": []}

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider), \
         patch("lib.sync_hooks.gather_sync_files", return_value=[
             {"relative_path": "r/a.yaml", "content": b"x", "secret_findings": []},
             {"relative_path": "r/b.yaml", "content": b"y", "secret_findings": []},
         ]):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result["pushed"] == 2
    mock_provider.push.assert_called_once()


def test_session_end_skips_when_no_config(tmp_path):
    from lib.sync_hooks import maybe_sync_push

    with patch("lib.sync_hooks.load_sync_config", return_value=None):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result is None


def test_session_end_skips_manual_mode(tmp_path):
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", mode="manual")

    with patch("lib.sync_hooks.load_sync_config", return_value=config):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result is None


def test_session_end_skips_when_auto_sync_false(tmp_path):
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", auto_sync=False)

    with patch("lib.sync_hooks.load_sync_config", return_value=config):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result is None


def test_strict_secret_scan_blocks_dirty_files(tmp_path, capsys):
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", auto_sync=True, secret_scan="strict")

    mock_provider = MagicMock()
    mock_provider.push.return_value = {"pushed": 1, "errors": []}

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider), \
         patch("lib.sync_hooks.gather_sync_files", return_value=[
             {"relative_path": "clean.json", "content": b"ok", "secret_findings": []},
             {"relative_path": "dirty.json", "content": b"bad", "secret_findings": ["api_key"]},
         ]):
        result = maybe_sync_push(data_dir=tmp_path)

    err = capsys.readouterr().err
    assert "1 files blocked" in err
    # Only clean file is pushed
    pushed_files = mock_provider.push.call_args[0][0]
    assert len(pushed_files) == 1
    assert pushed_files[0]["relative_path"] == "clean.json"


def test_push_logs_errors_when_provider_returns_partial_failure(tmp_path, capsys):
    """maybe_sync_push prints error count when provider.push returns non-empty errors."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.push.return_value = {"pushed": 1, "errors": [{"file": "a.yaml", "error": "oops"}]}

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider), \
         patch("lib.sync_hooks.gather_sync_files", return_value=[
             {"relative_path": "a.yaml", "content": b"x", "secret_findings": []},
             {"relative_path": "b.yaml", "content": b"y", "secret_findings": []},
         ]):
        result = maybe_sync_push(data_dir=tmp_path)

    err = capsys.readouterr().err
    assert "1 errors" in err
    assert result["pushed"] == 1


def test_push_returns_zero_when_no_files(tmp_path):
    """maybe_sync_push short-circuits with pushed=0 when there are no files to sync."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", auto_sync=True)

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=MagicMock()), \
         patch("lib.sync_hooks.gather_sync_files", return_value=[]):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result == {"pushed": 0, "errors": []}


def test_maybe_sync_pull_writes_files(tmp_path):
    """maybe_sync_pull writes pulled files to the data_dir."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = [
        {"path": "restarts/test.yaml", "content": b"name: test\n"},
    ]

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 1
    assert (tmp_path / "restarts" / "test.yaml").read_bytes() == b"name: test\n"


# ---------------------------------------------------------------------------
# Security regression: sync-pull path traversal / hook injection
# (security review F1 — a malicious/compromised remote could plant an
# arbitrary file anywhere under the user's filesystem, including
# ~/.claude/settings.json, giving zero-click hook injection on next
# session start)
# ---------------------------------------------------------------------------

def test_pull_blocks_path_traversal_outside_data_dir(tmp_path):
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)
    outside_target = tmp_path.parent / "PWNED_recall_test.yaml"
    outside_target.unlink(missing_ok=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = [
        {"path": "../PWNED_recall_test.yaml", "content": b"evil: true\n"},
    ]

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 0
    assert result.get("blocked") == 1
    assert not outside_target.exists()
    outside_target.unlink(missing_ok=True)


def test_pull_blocks_settings_json_overwrite(tmp_path):
    """A pulled path targeting settings.json (hook injection) must be rejected
    even though it resolves inside data_dir — only known sync categories are
    writable."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = [
        {"path": "settings.json", "content": b'{"hooks": {"PreToolUse": "evil"}}'},
    ]

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 0
    assert result.get("blocked") == 1
    assert not (tmp_path / "settings.json").exists()


def test_pull_blocks_dotfile_outside_categories(tmp_path):
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = [
        {"path": "../.ssh/authorized_keys", "content": b"ssh-rsa AAAA...\n"},
    ]

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 0
    assert result.get("blocked") == 1


def test_pull_allows_legitimate_category_paths_alongside_blocked_ones(tmp_path):
    """A malicious entry in the same pull batch must not block legitimate files."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = [
        {"path": "restarts/legit.yaml", "content": b"name: legit\n"},
        {"path": "../../etc/PWNED_recall_test.yaml", "content": b"evil: true\n"},
    ]

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 1
    assert result.get("blocked") == 1
    assert (tmp_path / "restarts" / "legit.yaml").read_bytes() == b"name: legit\n"


def test_pull_skips_when_manual_mode(tmp_path):
    """maybe_sync_pull returns None when mode is manual."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", mode="manual")
    with patch("lib.sync_hooks.load_sync_config", return_value=config):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result is None


def test_pull_writes_text_content(tmp_path):
    """maybe_sync_pull writes text (not bytes) content via write_text."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = [
        {"path": "restarts/test.yaml", "content": "name: test\n"},  # str, not bytes
    ]

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 1
    assert (tmp_path / "restarts" / "test.yaml").read_text() == "name: test\n"


def test_pull_reads_since_from_existing_timestamp_file(tmp_path):
    """When .last_sync_pull exists, its content is passed as 'since' to provider.pull."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    ts_file = tmp_path / ".last_sync_pull"
    ts_file.write_text("2026-04-01T00:00:00+00:00")

    config = SyncConfig(provider="cloud", auto_sync=True)

    mock_provider = MagicMock()
    mock_provider.pull.return_value = []

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider):
        maybe_sync_pull(data_dir=tmp_path)

    mock_provider.pull.assert_called_once()
    call_kwargs = mock_provider.pull.call_args
    assert call_kwargs[1]["since"] == "2026-04-01T00:00:00+00:00"


def test_push_captures_exception_and_returns_error(tmp_path):
    """maybe_sync_push returns error dict when provider.push raises."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", auto_sync=True)

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", side_effect=RuntimeError("boom")):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result["pushed"] == 0
    assert "boom" in result["errors"][0]


def test_pull_captures_exception_and_returns_error(tmp_path):
    """maybe_sync_pull returns error dict when provider.pull raises."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_pull

    config = SyncConfig(provider="cloud", auto_sync=True)

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", side_effect=RuntimeError("pull boom")):
        result = maybe_sync_pull(data_dir=tmp_path)

    assert result["pulled"] == 0
    assert "pull boom" in result["error"]
