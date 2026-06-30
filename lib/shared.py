#!/usr/bin/env python3
"""
Shared utilities for the recall system.

Centralizes duplicated path helpers, index I/O, and session detail I/O
that were previously copy-pasted across bin/ scripts and lib/ modules.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Callable, Tuple


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

WORKTREE_REGISTRY_PATH = Path.home() / '.claude' / 'recall-worktrees.json'


def _load_worktree_registry() -> dict:
    """Load ``~/.claude/recall-worktrees.json``.

    Returns ``{"projects": {}}`` if the file is missing or corrupt.
    """
    try:
        with open(WORKTREE_REGISTRY_PATH, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    return {"projects": {}}


def _save_worktree_registry(registry: dict):
    """Save *registry* to ``~/.claude/recall-worktrees.json``, creating parents."""
    WORKTREE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WORKTREE_REGISTRY_PATH, 'w') as f:
        json.dump(registry, f, indent=2, default=str)


def _resolve_worktree_by_path(cwd: str) -> Optional[str]:
    """Fallback worktree detection via path pattern matching.

    Catches worktrees even after cleanup (when .git file is gone).
    Matches paths like:
        /repo/.worktrees/branch-name
        /repo/.claude-worktrees/branch-name
    """
    match = re.search(r'^(.+)/\.(?:claude-)?worktrees/[^/]+/?$', cwd)
    if match:
        parent = match.group(1)
        # Verify the parent looks like a real repo (has .git dir)
        if Path(parent).is_dir():
            return parent
    return None


def resolve_worktree_root(cwd: str) -> Optional[str]:
    """Detect whether *cwd* is a git worktree and return the main repo path.

    Uses two strategies:
    1. Git-based: checks for ``.git`` file (standard worktree indicator)
    2. Path-based: matches ``/.worktrees/`` or ``/.claude-worktrees/`` in path
       (handles cleaned-up worktrees where .git is gone)
    """
    git_path = Path(cwd) / '.git'

    # Strategy 1: .git file detection (live worktrees)
    if git_path.exists() and git_path.is_file():
        try:
            result = subprocess.run(
                ['git', 'worktree', 'list', '--porcelain'],
                capture_output=True, text=True, cwd=cwd, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith('worktree '):
                        return line[len('worktree '):]
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    # Strategy 2: path pattern fallback (cleaned-up worktrees)
    path_result = _resolve_worktree_by_path(cwd)
    if path_result is not None:
        return path_result

    return None


def update_worktree_registry(main_repo: str, worktree_path: str, branch: str = None):
    """Add or update a worktree entry in the registry.

    Stores ``created``, ``last_seen``, and optional ``branch`` under
    ``registry["projects"][main_repo]["worktrees"][worktree_path]``.
    """
    registry = _load_worktree_registry()
    now = datetime.now(timezone.utc).isoformat()

    if main_repo not in registry["projects"]:
        registry["projects"][main_repo] = {
            "project_folder": main_repo.replace("/", "-"),
            "worktrees": {},
        }

    worktrees = registry["projects"][main_repo]["worktrees"]

    if worktree_path in worktrees:
        worktrees[worktree_path]["last_seen"] = now
        if branch is not None:
            worktrees[worktree_path]["branch"] = branch
    else:
        entry = {"created": now, "last_seen": now}
        if branch is not None:
            entry["branch"] = branch
        worktrees[worktree_path] = entry

    _save_worktree_registry(registry)


def lookup_worktree_project(worktree_path: str) -> Optional[str]:
    """Return the project_folder for a worktree, or None if not found.

    Iterates every project in the registry and checks whether
    *worktree_path* appears in that project's ``worktrees`` dict.
    """
    registry = _load_worktree_registry()
    for _repo_path, project_data in registry.get("projects", {}).items():
        if worktree_path in project_data.get("worktrees", {}):
            return project_data.get("project_folder")
    return None


def list_project_worktrees(repo_path: str) -> dict:
    """Return the worktrees dict for *repo_path*, or ``{}`` if unknown."""
    registry = _load_worktree_registry()
    project = registry.get("projects", {}).get(repo_path)
    if project is not None:
        return project.get("worktrees", {})
    return {}


def prune_stale_worktrees(max_age_days: int = 30) -> int:
    """Remove worktree entries older than *max_age_days*.

    Also removes project entries that have zero worktrees remaining.
    Returns the count of removed worktree entries.
    """
    registry = _load_worktree_registry()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = 0
    empty_projects = []

    for repo_path, project_data in registry.get("projects", {}).items():
        worktrees = project_data.get("worktrees", {})
        stale_keys = []
        for wt_path, wt_entry in worktrees.items():
            last_seen_str = wt_entry.get("last_seen", "")
            try:
                last_seen = datetime.fromisoformat(last_seen_str)
                # Ensure timezone-aware comparison
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                if last_seen < cutoff:
                    stale_keys.append(wt_path)
            except (ValueError, TypeError):
                # Unparseable last_seen — treat as stale
                stale_keys.append(wt_path)

        for key in stale_keys:
            del worktrees[key]
            removed += 1

        if not worktrees:
            empty_projects.append(repo_path)

    for repo_path in empty_projects:
        del registry["projects"][repo_path]

    if removed > 0:
        _save_worktree_registry(registry)

    return removed


def _resolve_cwd(cwd: str = None) -> str:
    """Resolve *cwd* from argument, env, or os.getcwd()."""
    if cwd is None:
        return os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    return cwd


def _normalize_path(cwd: str) -> str:
    """Convert an absolute filesystem path to Claude's project-folder convention.

    Claude Code stores per-project data under ``~/.claude/projects/<slug>``
    where ``<slug>`` is the full path with every ``/`` replaced by ``-``.
    Extracting this as a pure function makes it trivially testable and removes
    duplication between ``get_project_folder`` and ``get_project_folders``.
    """
    return cwd.replace('/', '-')


def get_project_folder(cwd: str = None) -> str:
    """Convert a working directory to Claude's project-folder naming convention.

    Falls back to CLAUDE_PROJECT_DIR env var, then os.getcwd().
    When *cwd* is inside a git worktree, resolves to the main repo path so
    that all worktrees share the same recall index.
    """
    cwd = _resolve_cwd(cwd)

    # Worktree resolution: if cwd is a worktree, use the main repo path
    main_repo = resolve_worktree_root(cwd)
    if main_repo is not None:
        # Try to extract branch name from the .git file
        branch = None
        git_file = Path(cwd) / '.git'
        try:
            content = git_file.read_text().strip()
            # Format: gitdir: /main/repo/.git/worktrees/<branch>
            if content.startswith('gitdir:'):
                parts = content.split('/')
                # Last component after "worktrees/" is the branch name
                if 'worktrees' in parts:
                    wt_idx = parts.index('worktrees')
                    if wt_idx + 1 < len(parts):
                        branch = parts[wt_idx + 1]
        except (IOError, OSError):
            pass

        update_worktree_registry(main_repo, cwd, branch)
        cwd = main_repo

    return _normalize_path(cwd)


def get_project_folders(cwd: str = None) -> Tuple[str, str]:
    """Return ``(resolved_folder, raw_folder)`` for *cwd*.

    ``resolved_folder`` — the main repo's project folder (for storing index data).
    ``raw_folder`` — the literal path-based folder (where Claude Code writes JSONLs).

    When *cwd* is NOT a worktree, both values are identical.
    """
    cwd = _resolve_cwd(cwd)
    raw_folder = _normalize_path(cwd)
    resolved_folder = get_project_folder(cwd)
    return resolved_folder, raw_folder


def get_project_dir(project_folder: str = None) -> Path:
    """Return ``~/.claude/projects/<project_folder>``."""
    if project_folder is None:
        project_folder = get_project_folder()
    return Path.home() / '.claude' / 'projects' / project_folder


def get_index_path(project_folder: str = None) -> Path:
    """Return the path to ``recall-index.json`` for *project_folder*."""
    return get_project_dir(project_folder) / 'recall-index.json'


def get_session_details_dir(project_folder: str = None) -> Path:
    """Return the directory used for per-session detail JSON files."""
    return get_project_dir(project_folder) / 'recall-sessions'


def get_restarts_dir(project_folder: str = None) -> Path:
    """Return the directory for restart checkpoint files."""
    return get_project_dir(project_folder) / 'recall-restarts'


def get_agents_file(project_folder: str = None, filename: str = 'agents.json') -> Path:
    """Return the path to an agents metadata file."""
    return get_project_dir(project_folder) / filename


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------

_EMPTY_INDEX_TEMPLATE = {
    'version': 2,
    'sessions': {},
    'failure_patterns': {},
    'learnings': [],
    'pending_learnings': [],
    'usage': {
        'skills': {},
        'learnings_shown': {},
    },
}


def _new_empty_index(project_folder: str = None) -> dict:
    """Return a fresh empty index dict, including the project key."""
    idx = dict(_EMPTY_INDEX_TEMPLATE)
    # Deep-copy mutable values
    idx['sessions'] = {}
    idx['failure_patterns'] = {}
    idx['learnings'] = []
    idx['pending_learnings'] = []
    idx['usage'] = {'skills': {}, 'learnings_shown': {}}
    idx['project'] = project_folder or get_project_folder()
    return idx


def load_index(project_folder: str = None, create_if_missing: bool = False) -> Optional[dict]:
    """Load the recall index from disk.

    Parameters
    ----------
    project_folder : str, optional
        Project folder name.  Derived automatically when *None*.
    create_if_missing : bool
        When *True* an empty index structure is returned if the file does
        not exist (used by index-session.py and knowledge.py).
        When *False* (the default) *None* is returned — the behaviour used
        by recall-sessions.py and session-context.py.
    """
    index_file = get_index_path(project_folder)
    if index_file.exists():
        try:
            with open(index_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if create_if_missing:
        return _new_empty_index(project_folder)
    return None


def save_index(index: dict, project_folder: str = None, prune_fn: Callable = None):
    """Persist the recall index to disk.

    Parameters
    ----------
    index : dict
        The index payload.
    project_folder : str, optional
        Target project folder.  Derived automatically when *None*.
    prune_fn : callable, optional
        If provided, called as ``prune_fn(index)`` before writing.
        index-session.py passes its ``prune_index`` function here.
    """
    if project_folder is None:
        project_folder = get_project_folder()

    index_dir = get_project_dir(project_folder)
    index_dir.mkdir(parents=True, exist_ok=True)

    if prune_fn is not None:
        index = prune_fn(index)

    index_file = index_dir / 'recall-index.json'
    with open(index_file, 'w') as f:
        json.dump(index, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Session detail I/O
# ---------------------------------------------------------------------------

def load_session_details(project_folder: str, session_id: str) -> Optional[dict]:
    """Load full session details from a per-session JSON file.

    Returns *None* when the file does not exist or cannot be parsed.
    """
    details_file = get_session_details_dir(project_folder) / f"{session_id}.json"
    if details_file.exists():
        try:
            with open(details_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def read_session_title(transcript_path) -> Optional[str]:
    """Return the most recent user-given ``customTitle`` from a Claude transcript.

    Claude Code transcripts (``~/.claude/projects/<folder>/<uuid>.jsonl``) record a
    ``{"type": "custom-title", "customTitle": "<name>", ...}`` line whenever the user
    names the session. Returns the *last* such title in the file (the current name),
    or ``None`` when the file is missing, unreadable, or has no custom title.
    Auto-generated ``ai-title`` lines are deliberately ignored.
    """
    title = None
    try:
        with open(transcript_path, 'r') as handle:
            for raw in handle:
                if '"custom-title"' not in raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get('type') == 'custom-title':
                    custom = obj.get('customTitle')
                    if custom:
                        title = custom
    except (OSError, IOError):
        return None
    return title


# ---------------------------------------------------------------------------
# Agents I/O (for restart support)
# ---------------------------------------------------------------------------

def load_agents(project_folder: str = None, filename: str = 'agents.json') -> list:
    """Load agents metadata. Returns an empty list when the file is absent."""
    agents_file = get_agents_file(project_folder, filename)
    if agents_file.exists():
        try:
            with open(agents_file, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_agents(agents: list, project_folder: str = None, filename: str = 'agents.json'):
    """Persist agents metadata to disk."""
    agents_file = get_agents_file(project_folder, filename)
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    with open(agents_file, 'w') as f:
        json.dump(agents, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Error categorization (shared by session-end.py and codex_session_end.py)
# ---------------------------------------------------------------------------

_ERROR_PATTERNS = [
    ('permission_denied', ['permission denied', 'access denied', 'eacces']),
    ('not_found', ['not found', 'no such file', 'enoent', 'command not found']),
    ('syntax_error', ['syntax error', 'parse error', 'unexpected token']),
    ('connection_error', ['connection refused', 'timeout', 'econnrefused', 'network']),
    ('import_error', ['import error', 'module not found', 'no module named']),
    ('type_error', ['typeerror', 'type error']),
    ('git_error', ['fatal:', 'git']),
    ('npm_error', ['npm err', 'npm warn']),
    ('python_error', ['traceback', 'exception']),
]


def categorize_error(error_msg: str) -> str:
    """Categorize a shell/tool error message into a pattern type."""
    error_lower = error_msg.lower()
    for pattern_name, keywords in _ERROR_PATTERNS:
        if any(kw in error_lower for kw in keywords):
            return pattern_name
    return 'other_error'
