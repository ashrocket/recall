#!/usr/bin/env python3
"""
SessionStart hook: Surface relevant context from past sessions.
Shows recent session summary and any recurring failure patterns.

Kept dependency-light because this hook runs before every interactive session.
The shell wrapper uses the Rust fast path when compiled; this Python path is the
portable fallback.
"""

import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime


def _normalize_path(cwd: str) -> str:
    return cwd.replace('/', '-')


def _resolve_worktree_by_path(cwd: str):
    match = re.search(r'^(.+)/\.(?:claude-)?worktrees/[^/]+/?$', cwd)
    if match and Path(match.group(1)).is_dir():
        return match.group(1)
    return None


def resolve_worktree_root(cwd: str):
    """Fast worktree root detection without shelling out to git."""
    git_path = Path(cwd) / '.git'
    if git_path.is_file():
        try:
            content = git_path.read_text().strip()
            if content.startswith('gitdir:'):
                gitdir = content[len('gitdir:'):].strip()
                marker = '/.git/worktrees/'
                if marker in gitdir:
                    return gitdir.split(marker, 1)[0]
        except OSError:
            pass
    return _resolve_worktree_by_path(cwd)


def get_project_folder(cwd: str) -> str:
    return _normalize_path(resolve_worktree_root(cwd) or cwd)


def get_project_folders(cwd: str):
    return get_project_folder(cwd), _normalize_path(cwd)


def load_index(project_folder: str):
    index_file = Path.home() / '.claude' / 'projects' / project_folder / 'recall-index.json'
    try:
        with open(index_file, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _sync_configured() -> bool:
    return bool(os.environ.get('RECALL_SYNC_REPO')) or (Path.home() / '.config' / 'recall' / 'sync.yaml').exists()


def _maybe_sync_pull():
    if not _sync_configured():
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from lib.sync_hooks import maybe_sync_pull
        maybe_sync_pull()
    except Exception:
        pass  # Never block session start due to sync


def _title_label(key: str) -> str:
    return ' '.join(part[:1].upper() + part[1:] for part in str(key).replace('_', ' ').split())


def _format_knowledge_summary(index: dict) -> str:
    learnings = index.get('learnings', []) if index else []
    buckets = {}
    for learning in learnings:
        if not isinstance(learning, dict):
            continue
        bucket = learning.get('bucket', 'personal')
        cat = learning.get('category', 'general')
        buckets.setdefault(bucket, {}).setdefault(cat, 0)
        buckets[bucket][cat] += 1

    lines = []
    for bucket in sorted(buckets.keys(), key=lambda k: (k in {'personal', 'claude'}, k)):
        cats = buckets[bucket]
        if cats:
            total = sum(cats.values())
            cat_names = ', '.join(sorted(cats.keys()))
            lines.append(f"  **{_title_label(bucket)}**: {total} learnings ({cat_names})")
    return '\n'.join(lines)


def _plural(count, singular, plural=None):
    return singular if count == 1 else (plural or f"{singular}s")


def _significant_failure_patterns(failure_patterns: dict) -> list:
    significant = []
    for pattern, failures in failure_patterns.items():
        if len(failures) >= 2:  # Pattern occurred multiple times
            significant.append((pattern, len(failures), failures[-1]))
    return sorted(significant, key=lambda x: -x[1])


def _truthy_env(name: str) -> bool:
    value = os.environ.get(name, '').strip().lower()
    return value in {'1', 'true', 'yes', 'on', 'full', 'verbose'}


def format_time_ago(date_str: str) -> str:
    """Format date as relative time."""
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        now = datetime.now()
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)

        diff = now - dt

        if diff.days > 0:
            return f"{diff.days}d ago"
        elif diff.seconds > 3600:
            return f"{diff.seconds // 3600}h ago"
        elif diff.seconds > 60:
            return f"{diff.seconds // 60}m ago"
        else:
            return "just now"
    except (ValueError, TypeError, AttributeError):
        return date_str[:10]


def format_compact_context(index: dict, sorted_sessions: list) -> str:
    last_session = sorted_sessions[0][1]
    time_ago = format_time_ago(last_session.get('date', ''))
    total_sessions = len(index.get('sessions', {}))
    pending = len(index.get('pending_learnings', []))
    issue_count = len(_significant_failure_patterns(index.get('failure_patterns', {})))

    parts = [
        f"{total_sessions} {_plural(total_sessions, 'session')} indexed",
        f"last {time_ago}",
    ]
    if pending > 0:
        parts.append(f"{pending} pending {_plural(pending, 'learning')}")
    if issue_count > 0:
        parts.append(f"{issue_count} recurring {_plural(issue_count, 'issue')} available")

    detail_commands = ["/recall last"]
    if pending > 0:
        detail_commands.append("/recall learn")
    if issue_count > 0:
        detail_commands.append("/recall failures")

    return f"Recall: {'; '.join(parts)}. Details: {' | '.join(detail_commands)}."


def format_verbose_context(index: dict, sorted_sessions: list) -> str:
    sessions = index.get('sessions', {})
    failure_patterns = index.get('failure_patterns', {})
    output = []
    output.append("## Session Context from /recall")
    output.append("")

    # Show last session summary
    last_session_id, last_session = sorted_sessions[0]
    time_ago = format_time_ago(last_session.get('date', ''))

    output.append(f"**Last session** ({time_ago}): {last_session.get('summary', 'No summary')[:150]}")

    # Show stats
    total_sessions = len(sessions)
    total_failures = sum(s.get('failure_count', 0) for s in sessions.values())

    if total_sessions > 1:
        output.append(f"**History**: {total_sessions} sessions, {total_failures} total failures")

    knowledge_summary = _format_knowledge_summary(index)
    if knowledge_summary:
        output.append("")
        output.append("**Knowledge loaded:**")
        output.append(knowledge_summary)

    pending = len(index.get('pending_learnings', []))
    if pending > 0:
        output.append("")
        output.append(f"**Pending:** {pending} learnings awaiting review (`/recall learn`)")

    # Show recurring failure patterns (if any)
    significant_patterns = _significant_failure_patterns(failure_patterns)

    if significant_patterns:
        output.append("")
        output.append("**Recurring issues** (use `/recall failures` for details):")
        for pattern, count, last_failure in significant_patterns[:3]:
            pattern_name = pattern.replace('_', ' ').title()
            output.append(f"  - {pattern_name}: {count}x (last: `{last_failure.get('command', 'unknown')[:50]}...`)")

    # Show incomplete tasks hint from last session
    last_messages = last_session.get('user_messages', [])
    if last_messages:
        last_msg = last_messages[-1].get('content', '')
        if any(word in last_msg.lower() for word in ['todo', 'next', 'later', 'continue', 'finish']):
            output.append("")
            output.append(f"**Possible continuation**: \"{last_msg[:100]}...\"")

    output.append("")
    output.append("_Use `/recall` to search past sessions, `/recall last` for full previous session_")
    output.append("")

    return '\n'.join(output)


def format_session_context(index: dict, sorted_sessions: list) -> str:
    if _truthy_env('RECALL_SESSION_START_VERBOSE'):
        return format_verbose_context(index, sorted_sessions)
    return format_compact_context(index, sorted_sessions)


def main():
    # Get project path — resolve worktrees to main repo for shared index
    cwd = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    if len(sys.argv) > 1:
        cwd = sys.argv[1]

    project_folder, _raw_folder = get_project_folders(cwd)

    # Sync pull only when configured; importing PyYAML/sync providers otherwise
    # dominates startup time and most installs have no sync config.
    _maybe_sync_pull()

    index = load_index(project_folder)

    if not index or not index.get('sessions'):
        # No history — show picker if this is a non-git directory
        git_path = Path(cwd) / '.git'
        if not git_path.exists():
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
                from session_start_helpers import collect_todays_sessions, format_session_picker
                today_sessions = collect_todays_sessions()
                if today_sessions:
                    print(format_session_picker(today_sessions))
            except Exception:
                pass
        sys.exit(0)

    sessions = index.get('sessions', {})
    # Sort sessions by date
    sorted_sessions = sorted(
        sessions.items(),
        key=lambda x: x[1].get('date', ''),
        reverse=True
    )

    # Only show context if there's something meaningful
    if not sorted_sessions:
        sys.exit(0)

    print(format_session_context(index, sorted_sessions))

if __name__ == '__main__':
    main()
