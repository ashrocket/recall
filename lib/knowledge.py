#!/usr/bin/env python3
"""
Knowledge management library for the recall system.
Handles loading, saving, and formatting learnings from recall-index.json.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Support being imported as both 'knowledge' (lib/ on sys.path) and 'lib.knowledge'
try:
    from lib.shared import (
        get_project_folder,
        get_index_path,
        load_index as _shared_load_index,
        save_index,
    )
except ImportError:
    from shared import (
        get_project_folder,
        get_index_path,
        load_index as _shared_load_index,
        save_index,
    )


GLOBAL_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"

# Config file for user-defined buckets and project mappings.
# Create ~/.claude/recall-buckets.json to customise; see README for schema.
BUCKETS_CONFIG_PATH = Path.home() / ".claude" / "recall-buckets.json"

# Built-in buckets — generic, shipped with the tool
BUILTIN_BUCKETS = {
    'personal': 'Personal — learning, tools, side projects',
    'claude': 'Claude — Claude Code functionality, tool behavior, workflow patterns',
}


def _load_buckets_config() -> dict:
    """Load ~/.claude/recall-buckets.json, returning {} on missing/corrupt."""
    try:
        with open(BUCKETS_CONFIG_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    return {}


# Load once per process (scripts are short-lived; re-import to refresh)
_buckets_config = _load_buckets_config()

# Merged buckets: builtin + user-defined (user can override builtin labels)
BUCKETS = {**BUILTIN_BUCKETS, **_buckets_config.get("buckets", {})}

# Default bucket for projects not listed in project_map
DEFAULT_BUCKET: str = _buckets_config.get("default_bucket", "personal")

# project folder → bucket (e.g. {"-Users-alice-myapp": "work"})
# Populated entirely from config — no user paths in source
PROJECT_BUCKET_MAP: dict = _buckets_config.get("project_map", {})


def get_bucket_for_project(project_folder: str = None) -> str:
    """Determine which bucket a project belongs to."""
    if not project_folder:
        project_folder = get_project_folder()
    return PROJECT_BUCKET_MAP.get(project_folder, DEFAULT_BUCKET)


def get_project_claude_md() -> Optional[Path]:
    """Find project-level CLAUDE.md by walking up from cwd."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / "CLAUDE.md"
        if candidate.exists():
            return candidate
    return None


def load_index(project_folder: str = None) -> dict:
    """Load recall index (creates empty structure if missing)."""
    return _shared_load_index(project_folder, create_if_missing=True)


def get_learnings(project_folder: str = None) -> list:
    """Get approved learnings from index."""
    index = load_index(project_folder)
    return index.get('learnings', [])


def get_pending_learnings(project_folder: str = None) -> list:
    """Get pending learnings awaiting approval."""
    index = load_index(project_folder)
    return index.get('pending_learnings', [])


# Rejection tombstones cap: enough to remember every triage decision a user
# plausibly makes, small enough to keep the index file lean.
MAX_REJECTED_TOMBSTONES = 200


def _normalize_key(text: str) -> str:
    """Collapse digit runs so occurrence counts ("5x in session", "Hit 7
    errors") don't change a learning's identity between proposals."""
    return re.sub(r'\d+', '#', text)


def _learning_key(learning: dict) -> str:
    """Stable identity for a proposed learning: title plus the start of its
    description, so a *new* failure that happens to share a generic title
    ("Fix for cat failure") is still proposable after an older one was
    rejected. Digits are normalized before truncation so varying counts
    produce the same key."""
    title = _normalize_key(learning.get('title', ''))
    description = _normalize_key(learning.get('description') or '')[:80]
    return f"{title}|{description}"


def add_pending_learning(learning: dict, project_folder: str = None):
    """Add a learning to the pending queue."""
    index = load_index(project_folder)
    if 'pending_learnings' not in index:
        index['pending_learnings'] = []

    # Check for duplicates by title
    existing_titles = {l.get('title', '') for l in index['pending_learnings']}
    approved_titles = {l.get('title', '') for l in index.get('learnings', [])}
    # Previously rejected proposals stay rejected (keyed on title+description).
    # Tombstones written before key normalization are raw strings, so
    # normalize stored entries at check time too.
    tombstones = {_normalize_key(t) for t in index.get('rejected_learnings', [])}
    if _learning_key(learning) in tombstones:
        return False

    if learning.get('title') not in existing_titles and learning.get('title') not in approved_titles:
        index['pending_learnings'].append(learning)
        save_index(index, project_folder)
        return True
    return False


def approve_learning(index: int, project_folder: str = None) -> Optional[dict]:
    """Move a pending learning to approved. Returns the learning or None."""
    idx = load_index(project_folder)
    pending = idx.get('pending_learnings', [])

    if 0 <= index < len(pending):
        learning = pending.pop(index)
        if 'learnings' not in idx:
            idx['learnings'] = []
        idx['learnings'].append(learning)
        save_index(idx, project_folder)
        return learning
    return None


def reject_learning(index: int, project_folder: str = None) -> Optional[dict]:
    """Remove a pending learning and tombstone it so the same proposal is
    not re-extracted on the next save/session-end. Returns the learning or
    None."""
    idx = load_index(project_folder)
    pending = idx.get('pending_learnings', [])

    if 0 <= index < len(pending):
        learning = pending.pop(index)
        tombstones = idx.setdefault('rejected_learnings', [])
        tombstones.append(_learning_key(learning))
        if len(tombstones) > MAX_REJECTED_TOMBSTONES:
            del tombstones[:-MAX_REJECTED_TOMBSTONES]
        save_index(idx, project_folder)
        return learning
    return None


def approve_all_pending(project_folder: str = None) -> int:
    """Approve all pending learnings. Returns count approved."""
    idx = load_index(project_folder)
    pending = idx.get('pending_learnings', [])

    if not pending:
        return 0

    if 'learnings' not in idx:
        idx['learnings'] = []

    count = len(pending)
    idx['learnings'].extend(pending)
    idx['pending_learnings'] = []
    save_index(idx, project_folder)
    return count


def get_all_knowledge(project_folder: str = None) -> dict:
    """Get all knowledge organized by category."""
    learnings = get_learnings(project_folder)
    categories = {}

    for learning in learnings:
        if isinstance(learning, dict):
            cat = learning.get('category', 'general')
            if cat not in categories:
                categories[cat] = []
            title = learning.get('title', 'Unknown')
            solution = learning.get('solution', '')
            categories[cat].append(f"{title}: {solution}" if solution else title)

    return categories


def get_knowledge_by_bucket(project_folder: str = None) -> dict:
    """Get all knowledge organized by bucket then category."""
    learnings = get_learnings(project_folder)
    buckets = {}

    for learning in learnings:
        if isinstance(learning, dict):
            bucket = learning.get('bucket', DEFAULT_BUCKET)
            cat = learning.get('category', 'general')
            if bucket not in buckets:
                buckets[bucket] = {}
            if cat not in buckets[bucket]:
                buckets[bucket][cat] = []
            title = learning.get('title', 'Unknown')
            solution = learning.get('solution', '')
            buckets[bucket][cat].append(f"{title}: {solution}" if solution else title)

    return buckets


def format_knowledge_summary(knowledge: dict) -> str:
    """Format knowledge for session start display."""
    lines = []
    for cat, items in sorted(knowledge.items()):
        lines.append(f"  [{cat}] {len(items)} learnings")
    return '\n'.join(lines) if lines else "  No learnings yet"


def format_bucketed_summary(buckets: dict) -> str:
    """Format knowledge grouped by bucket for session start display."""
    lines = []
    # Show all buckets that have learnings, sorted with businesses first
    for bucket_key in sorted(buckets.keys(), key=lambda k: (k in BUILTIN_BUCKETS, k)):
        cats = buckets.get(bucket_key, {})
        if cats:
            total = sum(len(items) for items in cats.values())
            cat_names = ', '.join(sorted(cats.keys()))
            label = bucket_key.title()
            lines.append(f"  **{label}**: {total} learnings ({cat_names})")
    return '\n'.join(lines) if lines else "  No learnings yet"
