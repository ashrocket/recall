"""
Sync engine core.

Provides the provider adapter pattern and file gathering logic.
Providers (git, cloud) implement the SyncProvider interface.
"""

import abc
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Optional, Dict

from lib.sync_config import SyncConfig
from lib.sync_ignore import load_ignore_patterns, should_ignore
from lib.sync_scan import scan_file


SYNC_CATEGORIES = {
    "restarts": "restarts",
    "learnings": "learnings",
    "sops": "sops",
    "adm": "adm",
    "session_metadata": "sessions",
    "agent_configs": "agent-configs",
    "transcripts": "transcripts",
}


@dataclass
class SyncFile:
    relative_path: str
    absolute_path: Path
    content: bytes
    secret_findings: List[dict]


class SyncProvider(abc.ABC):
    @abc.abstractmethod
    def push(self, files: List[SyncFile], config: SyncConfig) -> dict:
        """Push files to remote. Returns {pushed: int, errors: list}."""

    @abc.abstractmethod
    def pull(self, since: Optional[str], config: SyncConfig) -> List[dict]:
        """Pull files changed since timestamp. Returns list of {path, content}."""

    @abc.abstractmethod
    def status(self, config: SyncConfig) -> dict:
        """Return remote status."""


_providers: Dict[str, type] = {}


def register_provider(name: str, cls: type):
    _providers[name] = cls


def get_provider(name: str) -> type:
    if name not in _providers:
        raise ValueError(f"Unknown sync provider: {name}. Available: {list(_providers.keys())}")
    return _providers[name]


_PULL_ALLOWED_PREFIXES = tuple(f"{subdir}/" for subdir in SYNC_CATEGORIES.values())


def is_safe_pull_relative_path(relative_path: str) -> bool:
    """Return whether *relative_path* is a legitimate sync-pull target.

    Pulled paths come from a remote (a shared git repo or cloud bucket) and
    must never be trusted to place files outside recall's own sync
    categories. A safe path: is relative, has no ``..`` traversal component,
    lives under one of the known ``SYNC_CATEGORIES`` subdirectories, and is a
    ``.yaml`` file — the same shape ``gather_sync_files`` produces on push.
    Anything else (``settings.json``, dotfiles, absolute paths, symlink
    escapes) is rejected so a malicious/compromised remote cannot plant hook
    config or overwrite files outside the sync tree.
    """
    if not relative_path or not relative_path.endswith(".yaml"):
        return False
    if PurePosixPath(relative_path).is_absolute():
        return False
    if ".." in PurePosixPath(relative_path).parts:
        return False
    return relative_path.startswith(_PULL_ALLOWED_PREFIXES)


def gather_sync_files(
    data_dir: Path,
    config: SyncConfig,
    ignore_path: Path = None,
) -> List[dict]:
    if ignore_path is None:
        ignore_path = data_dir / ".recallignore"
    patterns = load_ignore_patterns(ignore_path)

    files = []
    include = config.include

    for category, subdir in SYNC_CATEGORIES.items():
        if not getattr(include, category, False):
            continue

        category_dir = data_dir / subdir
        if not category_dir.exists():
            continue

        for file_path in category_dir.rglob("*.yaml"):
            relative = f"{subdir}/{file_path.name}"

            if should_ignore(relative, patterns):
                continue

            findings = scan_file(file_path) if config.secret_scan != "off" else []

            files.append({
                "relative_path": relative,
                "absolute_path": file_path,
                "content": file_path.read_bytes(),
                "secret_findings": findings,
            })

    return files
