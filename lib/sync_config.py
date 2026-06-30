"""
Sync configuration loader.

Reads ~/.config/recall/sync.yaml and provides typed access
to sync settings. Supports env var override (RECALL_SYNC_REPO).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "recall" / "sync.yaml"


@dataclass
class SyncInclude:
    restarts: bool = True
    learnings: bool = True
    sops: bool = True
    adm: bool = True
    session_metadata: bool = True
    agent_configs: bool = True
    transcripts: bool = False


@dataclass
class SyncConfig:
    provider: str = "github"
    repo: Optional[str] = None
    endpoint: Optional[str] = None
    api_key_file: Optional[str] = None
    tier: str = "lite"
    auto_sync: bool = True
    mode: str = "auto"
    secret_scan: str = "warn"
    include: SyncInclude = field(default_factory=SyncInclude)


def load_sync_config(config_path: Path = None) -> Optional[SyncConfig]:
    """Load sync config from YAML, with env var fallback."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    env_repo = os.environ.get("RECALL_SYNC_REPO")
    if env_repo:
        return SyncConfig(
            provider=_detect_provider(env_repo),
            repo=env_repo,
        )

    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except (yaml.YAMLError, IOError):
        return None

    if not raw or "sync" not in raw:
        return None

    s = raw["sync"]
    include_raw = s.get("include", {})

    return SyncConfig(
        provider=s.get("provider", "github"),
        repo=s.get("repo"),
        endpoint=s.get("endpoint"),
        api_key_file=s.get("api_key_file"),
        tier=s.get("tier", "lite"),
        auto_sync=s.get("auto_sync", True),
        mode=s.get("mode", "auto"),
        secret_scan=s.get("secret_scan", "warn"),
        include=SyncInclude(
            restarts=include_raw.get("restarts", True),
            learnings=include_raw.get("learnings", True),
            sops=include_raw.get("sops", True),
            adm=include_raw.get("adm", True),
            session_metadata=include_raw.get("session_metadata", True),
            agent_configs=include_raw.get("agent_configs", True),
            transcripts=include_raw.get("transcripts", False),
        ),
    )


def _detect_provider(repo_url: str) -> str:
    """Guess provider from repo URL."""
    if "github.com" in repo_url:
        return "github"
    if "gitlab.com" in repo_url:
        return "gitlab"
    if "bitbucket.org" in repo_url:
        return "bitbucket"
    return "github"
