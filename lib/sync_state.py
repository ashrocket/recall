"""
Per-endpoint sync state: the content_sha256 recall last saw on the server for each path.

This is the local half of optimistic-concurrency sync. When recall pushes a file it sends
``If-Match: <base sha>`` — "only overwrite if the server still holds the version I edited
from." The base sha is whatever we recorded the last time we pulled or successfully pushed
that path. Without it, two machines editing the same learning silently clobber; with it,
the second writer gets a 412 and is told to pull instead of losing the other machine's edit.

State lives at ``~/.config/recall/sync-state/<endpoint-hash>.json`` so distinct endpoints
never share a manifest. It is a cache, not a source of truth: deleting it just means the
next push falls back to create-only semantics.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional


def _state_root() -> Path:
    """State directory. ``RECALL_STATE_DIR`` overrides it (tests, isolated homes)."""
    override = os.environ.get("RECALL_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "recall" / "sync-state"


def _endpoint_slug(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


def _state_path(endpoint: str) -> Path:
    return _state_root() / f"{_endpoint_slug(endpoint)}.json"


def content_sha256(content: bytes) -> str:
    """The same digest the worker computes over the raw bytes."""
    return hashlib.sha256(content).hexdigest()


def is_sha256(value: object) -> bool:
    """True only for a real 64-char hex digest — guards state against junk values."""
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


class SyncState:
    """A path -> base-sha manifest for one endpoint."""

    def __init__(self, endpoint: str):
        self._endpoint = endpoint
        self._path = _state_path(endpoint)
        self._bases: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
            bases = raw.get("bases", {})
            if isinstance(bases, dict):
                self._bases = {str(k): str(v) for k, v in bases.items()}
        except (IOError, ValueError):
            self._bases = {}

    def base(self, relative_path: str) -> Optional[str]:
        """The sha recall believes the server holds for *relative_path*, or None."""
        return self._bases.get(relative_path)

    def record(self, relative_path: str, sha: str) -> None:
        self._bases[relative_path] = sha

    def forget(self, relative_path: str) -> None:
        self._bases.pop(relative_path, None)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"bases": self._bases}, indent=2))
        except IOError:
            pass
