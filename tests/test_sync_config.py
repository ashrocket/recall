import pytest
import json
import yaml
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_load_sync_config_from_yaml(tmp_path):
    """Load sync config from YAML file."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text("""
sync:
  provider: cloud
  endpoint: https://recall-api.workers.dev
  api_key_file: ~/.env/recall/api-key
  tier: lite
  auto_sync: true
  include:
    restarts: true
    learnings: true
    sops: true
    adm: true
    session_metadata: true
    agent_configs: true
    transcripts: false
""")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config.provider == "cloud"
    assert config.endpoint == "https://recall-api.workers.dev"
    assert config.tier == "lite"
    assert config.auto_sync is True
    assert config.include.restarts is True
    assert config.include.transcripts is False


def test_load_sync_config_missing_file():
    """Return None when config file doesn't exist."""
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=Path("/nonexistent/sync.yaml"))
    assert config is None


def test_load_sync_config_defaults(tmp_path):
    """Missing keys get sensible defaults."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text("""
sync:
  provider: github
  repo: git@github.com:user/recall-data.git
""")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config.provider == "github"
    assert config.auto_sync is True  # default
    assert config.tier == "lite"  # default
    assert config.include.restarts is True  # default
    assert config.include.transcripts is False  # default


def test_sync_config_env_override(tmp_path, monkeypatch):
    """RECALL_SYNC_REPO env var overrides config file."""
    monkeypatch.setenv("RECALL_SYNC_REPO", "git@github.com:env/repo.git")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=Path("/nonexistent"))
    assert config is not None
    assert config.repo == "git@github.com:env/repo.git"


def test_load_sync_config_returns_none_for_corrupt_yaml(tmp_path):
    """Corrupt YAML returns None (fails silently)."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text(": invalid: yaml: {{{")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config is None


def test_load_sync_config_returns_none_when_no_sync_key(tmp_path):
    """Valid YAML without a 'sync' key returns None."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text("other_key: value\n")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config is None


def test_load_sync_config_returns_none_when_file_is_empty(tmp_path):
    """Empty YAML file (safe_load returns None) returns None."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text("")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config is None


def test_detect_provider_gitlab():
    """gitlab.com URL maps to gitlab provider."""
    from lib.sync_config import _detect_provider
    assert _detect_provider("https://gitlab.com/user/repo.git") == "gitlab"


def test_detect_provider_unknown_defaults_to_github():
    """Unknown domain defaults to github provider."""
    from lib.sync_config import _detect_provider
    assert _detect_provider("https://custom-host.example.com/repo") == "github"


def test_detect_provider_bitbucket():
    """bitbucket.org URL maps to bitbucket provider."""
    from lib.sync_config import _detect_provider
    assert _detect_provider("https://bitbucket.org/user/repo.git") == "bitbucket"


def test_load_sync_config_uses_default_path_when_not_given(monkeypatch, tmp_path):
    """When config_path is None, DEFAULT_CONFIG_PATH is used."""
    from lib.sync_config import load_sync_config
    from pathlib import Path
    from unittest.mock import patch

    monkeypatch.delenv("RECALL_SYNC_REPO", raising=False)
    nonexistent = tmp_path / "no-such-sync.yaml"

    with patch("lib.sync_config.DEFAULT_CONFIG_PATH", nonexistent):
        result = load_sync_config()  # no config_path argument

    assert result is None
