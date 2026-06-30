#!/usr/bin/env python3
"""
Recall past Claude Code sessions for a project.
Uses unified index for fast queries, falls back to JSONL parsing.

Usage:
  recall-sessions.py <project_path> [command]

Commands:
  (none)           - List recent sessions
  last             - Show previous session details
  failures         - Show failure patterns and learnings
  stats            - Show skill and learning usage statistics
  export [file]    - Export index to file (default: recall-backup.json)
  import <file>    - Import index from file
  reset            - Reset to empty index (keeps backup)
  cleanup [--dry-run|--execute|--noise|--sensitive|--jsonl|--dedup]
  <search_term>    - Search for term in past sessions
"""

import sys
import os


def _early_fast_binary_supports(argv):
    remaining = [arg for arg in argv[2:] if arg != '--json']
    if not remaining:
        return True
    command = ' '.join(remaining)
    cmd_name = command.split(None, 1)[0].lower() if command else ''
    return cmd_name not in {'export', 'import', 'reset', 'cleanup', 'learn', 'knowledge'}


def _early_maybe_exec_fast_binary():
    if __name__ != '__main__' or os.environ.get('RECALL_NO_FAST') == '1':
        return
    if len(sys.argv) < 2 or not _early_fast_binary_supports(sys.argv):
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in (
        os.path.join('target', 'release', 'recall-sessions-rs'),
        os.path.join('target', 'debug', 'recall-sessions-rs'),
    ):
        binary = os.path.join(root, rel)
        if os.path.exists(binary) and os.access(binary, os.X_OK):
            os.execv(binary, [binary, *sys.argv[1:]])


_early_maybe_exec_fast_binary()

import json
from pathlib import Path
from datetime import datetime
import re

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import (
    get_project_folder,
    get_session_details_dir,
    load_session_details,
    get_index_path,
    load_index,
    save_index,
)
from lib.recall_format import (
    _matches_terms,
    compile_regex_query,
    format_date,
    matches_search_query,
    show_stats,
    show_failures,
)
from lib.text_rank import rank_query_texts


SEARCH_SCAN_LIMIT = 40
SEARCH_RESULT_LIMIT = 8
SEARCH_SNIPPET_LIMIT = 180


def list_all_project_indices() -> list:
    """List all project folders with recall indices."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return []

    projects = []
    for proj_dir in projects_dir.iterdir():
        if proj_dir.is_dir():
            index_file = proj_dir / 'recall-index.json'
            if index_file.exists():
                projects.append(proj_dir.name)
    return projects


def _clip(text: str, limit: int = SEARCH_SNIPPET_LIMIT) -> str:
    """Compact whitespace and truncate text for token-efficient output."""
    compact = ' '.join((text or '').split())
    if len(compact) <= limit:
        return compact
    return compact[:limit - 1].rstrip() + '…'


def _make_search_result(
    *,
    project: str,
    session_id: str,
    session_summary: dict,
    source: str,
    text: str,
) -> dict:
    """Create a normalized search result record."""
    summary = session_summary.get('summary', '') if session_summary else ''
    return {
        'project': project,
        'id': session_id,
        'date': session_summary.get('date', '') if session_summary else '',
        'summary': summary,
        'source': source,
        'text': text,
        'snippet': _clip(text),
        'message_count': session_summary.get('message_count', 0) if session_summary else 0,
        'failure_count': session_summary.get('failure_count', 0) if session_summary else 0,
    }


def _candidate_texts_from_details(details: dict) -> list:
    """Return ``(source, text)`` candidates from a detail payload."""
    candidates = []
    for msg in details.get('user_messages', []):
        content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
        if content:
            candidates.append(('msg', content))

    for cmd in details.get('commands', []):
        cmd_text = cmd.get('command', '')
        if cmd_text:
            candidates.append(('cmd', cmd_text))

    for fail in details.get('failures', []):
        command = fail.get('command', '')
        error = fail.get('error', '')
        text = f"{command} -> {error}".strip()
        if text:
            candidates.append(('fail', text))

    for skill in details.get('skills_used', []):
        skill_name = skill.get('skill', '')
        if skill_name:
            candidates.append(('skill', skill_name))

    return candidates


def _rank_search_results(search_term: str, results: list, limit: int = SEARCH_RESULT_LIMIT) -> list:
    """Rank normalized search results locally."""
    texts = [
        f"{result.get('summary', '')} {result.get('source', '')} {result.get('text', '')}"
        for result in results
    ]
    ranked_indexes = rank_query_texts(search_term, texts, limit=limit)
    if not ranked_indexes:
        return [
            {**dict(result), 'score': 1.0}
            for result in results[:limit]
        ]
    ranked = []
    for index, score in ranked_indexes:
        result = dict(results[index])
        result['score'] = round(float(score), 4)
        ranked.append(result)
    return ranked


def collect_search_results(
    search_term: str,
    index: dict,
    project_folder: str,
    *,
    session_limit: int = SEARCH_SCAN_LIMIT,
    result_limit: int = SEARCH_RESULT_LIMIT,
) -> list:
    """Collect and rank search results from one project index."""
    if not index:
        return []

    candidates = []
    _, query_error = compile_regex_query(search_term)
    if query_error:
        return []
    sorted_sessions = sorted(
        index.get('sessions', {}).items(),
        key=lambda x: x[1].get('date', ''),
        reverse=True,
    )

    for session_id, session_summary in sorted_sessions[:session_limit]:
        summary = session_summary.get('summary', '')
        if summary and matches_search_query(summary, search_term):
            candidates.append(_make_search_result(
                project=project_folder,
                session_id=session_id,
                session_summary=session_summary,
                source='summary',
                text=summary,
            ))

        details = load_session_details(project_folder, session_id)
        if details:
            for source, text in _candidate_texts_from_details(details):
                if matches_search_query(text, search_term):
                    candidates.append(_make_search_result(
                        project=project_folder,
                        session_id=session_id,
                        session_summary=session_summary,
                        source=source,
                        text=text,
                    ))

    for pattern, failures in index.get('failure_patterns', {}).items():
        for failure in failures:
            text = f"{pattern} {failure.get('command', '')} -> {failure.get('error', '')}"
            if matches_search_query(text, search_term):
                candidates.append({
                    'project': project_folder,
                    'id': failure.get('session_id', ''),
                    'date': failure.get('date', ''),
                    'summary': pattern,
                    'source': 'failure_pattern',
                    'text': text,
                    'snippet': _clip(text),
                    'message_count': 0,
                    'failure_count': failure.get('count', 1),
                })

    return _rank_search_results(search_term, candidates, limit=result_limit)


def _format_search_result(result: dict) -> str:
    source = result.get('source', 'match')
    if source == 'cmd':
        body = f"cmd: `{_clip(result.get('text', ''))}`"
    elif source == 'fail':
        body = f"fail: {_clip(result.get('text', ''))}"
    elif source == 'skill':
        body = f"skill: {result.get('snippet', '')}"
    elif source == 'failure_pattern':
        body = f"Failure Patterns: {result.get('snippet', '')}"
    elif source == 'summary':
        body = f"summary: {result.get('snippet', '')}"
    else:
        body = f"msg: {result.get('snippet', '')}"
    return body


def export_index(index: dict, project_folder: str, export_path: str = None):
    """Export index to a file for backup/testing."""
    if not index:
        print("No index to export.")
        return

    # Default export path
    if not export_path:
        export_path = f"recall-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    # Make path absolute if relative
    export_file = Path(export_path)
    if not export_file.is_absolute():
        export_file = Path.cwd() / export_file

    # Add metadata
    export_data = {
        'exported_at': datetime.now().isoformat(),
        'project_folder': project_folder,
        'index': index
    }

    with open(export_file, 'w') as f:
        json.dump(export_data, f, indent=2, default=str)

    print(f"## Exported Recall Index")
    print(f"**File:** `{export_file}`")
    print()
    print("Contents:")
    print(f"  - {len(index.get('sessions', {}))} sessions")
    print(f"  - {len(index.get('learnings', []))} learnings")
    print(f"  - {len(index.get('failure_patterns', {}))} failure pattern categories")
    skills = index.get('usage', {}).get('skills', {})
    print(f"  - {len(skills)} skills tracked")
    print()
    print("Use `/recall import <file>` to restore this backup.")

def import_index(project_folder: str, import_path: str):
    """Import index from a backup file."""
    import_file = Path(import_path)
    if not import_file.is_absolute():
        import_file = Path.cwd() / import_file

    if not import_file.exists():
        print(f"Error: File not found: {import_file}")
        return

    try:
        with open(import_file, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in file: {e}")
        return

    # Handle both direct index and wrapped export format
    if 'index' in data and 'exported_at' in data:
        # Wrapped export format
        index = data['index']
        print(f"Importing from backup created: {data.get('exported_at', 'unknown')}")
    else:
        # Direct index format
        index = data

    # Backup current index first
    current_index_path = get_index_path(project_folder)
    if current_index_path.exists():
        backup_path = current_index_path.with_suffix('.json.bak')
        import shutil
        shutil.copy(current_index_path, backup_path)
        print(f"Current index backed up to: {backup_path}")

    # Save imported index
    save_index(index, project_folder)

    print()
    print(f"## Imported Recall Index")
    print(f"**From:** `{import_file}`")
    print()
    print("Imported:")
    print(f"  - {len(index.get('sessions', {}))} sessions")
    print(f"  - {len(index.get('learnings', []))} learnings")
    print(f"  - {len(index.get('failure_patterns', {}))} failure pattern categories")

def reset_index(index: dict, project_folder: str):
    """Reset index to empty state, keeping a backup."""
    index_path = get_index_path(project_folder)

    # Backup current index
    if index and index_path.exists():
        backup_path = f"recall-backup-pre-reset-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        export_index(index, project_folder, backup_path)
        print()

    # Create empty index
    empty_index = {
        'version': 2,
        'project': project_folder,
        'sessions': {},
        'failure_patterns': {},
        'learnings': [],
        'usage': {
            'skills': {},
            'learnings_shown': {}
        }
    }

    save_index(empty_index, project_folder)

    print("## Index Reset")
    print("Created empty index. Previous data backed up above.")
    print()
    print("The index will rebuild as you use sessions.")
    print("Use `/recall import <file>` to restore from backup.")

def find_session_files(project_folder: str) -> list:
    """Find all session files for a project, sorted by modification time."""
    claude_dir = Path.home() / '.claude' / 'projects' / project_folder
    if not claude_dir.exists():
        return []

    sessions = []
    for f in claude_dir.glob('*.jsonl'):
        if not f.name.startswith('agent-'):
            sessions.append(f)

    sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return sessions

def parse_session(session_file: Path, search_term: str = None) -> dict:
    """Parse a session file and extract key information (fallback when no index)."""
    result = {
        'file': session_file.name,
        'session_id': session_file.stem,
        'date': datetime.fromtimestamp(session_file.stat().st_mtime),
        'user_messages': [],
        'matches': []
    }

    try:
        with open(session_file, 'r') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get('type') == 'user':
                        msg = obj.get('message', {})
                        if isinstance(msg, dict):
                            content = msg.get('content', '')
                            if isinstance(content, str) and content:
                                if not content.startswith('<'):
                                    result['user_messages'].append(content[:500])
                                    if search_term and matches_search_query(content, search_term):
                                        result['matches'].append(content[:300])
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        result['error'] = str(e)

    return result

def cleanup_noise_sessions(index: dict, project_folder: str):
    """Remove low-value sessions (< 3 messages, no failures) from index."""
    sessions_data = index.get('sessions', {})
    removed = []

    for sid in list(sessions_data.keys()):
        session = sessions_data[sid]
        if session.get('message_count', 0) < 3 and session.get('failure_count', 0) == 0:
            removed.append(sid)
            del sessions_data[sid]
            # Also remove detail file
            detail_file = get_session_details_dir(project_folder) / f"{sid}.json"
            if detail_file.exists():
                detail_file.unlink()

    if removed:
        save_index(index, project_folder)
        print(f"Removed {len(removed)} low-value sessions from index")
    else:
        print("No low-value sessions to remove")


def cleanup_sensitive_sessions(index: dict, project_folder: str):
    """Remove sessions containing sensitive data from index and detail files."""
    sessions_data = index.get('sessions', {})
    sensitive_patterns = ['BEGIN OPENSSH', 'BEGIN RSA', 'API_KEY=', 'SECRET=', 'TOKEN=', 'password', 'PRIVATE KEY']
    removed = []

    for sid in list(sessions_data.keys()):
        session = sessions_data[sid]
        summary = session.get('summary', '')

        # Check summary text
        is_sensitive = any(p.lower() in summary.lower() for p in sensitive_patterns)

        # Also check detail file
        if not is_sensitive:
            details = load_session_details(project_folder, sid)
            if details:
                for msg in details.get('user_messages', []):
                    content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
                    if any(p.lower() in content.lower() for p in sensitive_patterns):
                        is_sensitive = True
                        break

        if is_sensitive:
            removed.append(sid)
            del sessions_data[sid]
            detail_file = get_session_details_dir(project_folder) / f"{sid}.json"
            if detail_file.exists():
                detail_file.unlink()

    if removed:
        save_index(index, project_folder)
        print(f"Removed {len(removed)} sessions with sensitive data")
    else:
        print("No sessions with sensitive data found")


def cleanup_jsonl_files(project_folder: str):
    """Remove old raw .jsonl files to reclaim disk space."""
    from datetime import timedelta

    claude_dir = Path.home() / '.claude' / 'projects' / project_folder
    if not claude_dir.exists():
        print("No project directory found")
        return

    now = datetime.now()
    session_max_age = timedelta(days=30)
    agent_max_age = timedelta(days=7)
    freed = 0
    removed_count = 0

    # find_session_files handles glob + agent-prefix filter + mtime sort
    session_files = find_session_files(project_folder)
    agent_files = [f for f in claude_dir.glob('*.jsonl') if f.name.startswith('agent-')]

    # Keep 5 most recent session files, remove old ones
    for f in session_files[5:]:
        try:
            age = now - datetime.fromtimestamp(f.stat().st_mtime)
            if age > session_max_age:
                size = f.stat().st_size
                f.unlink()
                freed += size
                removed_count += 1
        except (OSError, IOError):
            pass

    # Remove agent files older than 7 days
    for f in agent_files:
        try:
            age = now - datetime.fromtimestamp(f.stat().st_mtime)
            if age > agent_max_age:
                size = f.stat().st_size
                f.unlink()
                freed += size
                removed_count += 1
        except (OSError, IOError):
            pass

    if freed > 0:
        print(f"Removed {removed_count} files, freed {freed / 1024 / 1024:.1f} MB")
    else:
        print("No old .jsonl files to remove (sessions <30d, agents <7d)")


def cleanup_dedup_failures(index: dict, project_folder: str):
    """Deduplicate failure patterns in the index."""
    failure_patterns = index.get('failure_patterns', {})
    total_before = sum(len(v) for v in failure_patterns.values())
    deduped = 0

    for pattern in list(failure_patterns.keys()):
        entries = failure_patterns[pattern]
        seen = {}
        unique = []

        for entry in entries:
            cmd_key = entry.get('command', '')[:50]
            if cmd_key in seen:
                # Merge into existing
                seen[cmd_key]['count'] = seen[cmd_key].get('count', 1) + entry.get('count', 1)
                seen[cmd_key]['date'] = max(seen[cmd_key].get('date', ''), entry.get('date', ''))
                deduped += 1
            else:
                seen[cmd_key] = entry
                unique.append(entry)

        failure_patterns[pattern] = unique[-15:]  # Keep last 15

    if deduped > 0:
        save_index(index, project_folder)
        total_after = sum(len(v) for v in failure_patterns.values())
        print(f"Deduplicated failures: {total_before} -> {total_after} entries ({deduped} merged)")
    else:
        print("No duplicate failure patterns found")


def show_cleanup_analysis(index: dict, sessions: list, project_folder: str, action: str = None):
    """Analyze recall data and optionally perform cleanup actions.

    Flags: --dry-run (analysis only, default), --execute (run all actions),
           --noise, --sensitive, --jsonl, --dedup (run specific action),
           --all (alias for --execute).
    """
    # If an action flag is given, perform that cleanup
    if action:
        action = action.strip().lstrip('-')
        if action in ('execute', 'all'):
            print("## Running all cleanup actions")
            print()
            cleanup_sensitive_sessions(index, project_folder)
            cleanup_noise_sessions(index, project_folder)
            cleanup_dedup_failures(index, project_folder)
            cleanup_jsonl_files(project_folder)
            print()
            print("Cleanup complete.")
            return
        elif action == 'noise':
            cleanup_noise_sessions(index, project_folder)
            return
        elif action == 'sensitive':
            cleanup_sensitive_sessions(index, project_folder)
            return
        elif action == 'jsonl':
            cleanup_jsonl_files(project_folder)
            return
        elif action == 'dedup':
            cleanup_dedup_failures(index, project_folder)
            return
        # --dry-run falls through to analysis mode

    # Default: analysis mode
    print("## Recall Cleanup Analysis")
    print()

    index_file = Path.home() / '.claude' / 'projects' / project_folder / 'recall-index.json'
    print(f"**Index:** `{index_file}`")
    print()

    if not index:
        print("No index found. Nothing to clean.")
        return

    # Analyze sessions
    sessions_data = index.get('sessions', {})
    noise_sessions = []
    sensitive_sessions = []
    useful_sessions = []

    sensitive_patterns = ['BEGIN OPENSSH', 'BEGIN RSA', 'API_KEY=', 'SECRET=', 'TOKEN=', 'password', 'PRIVATE KEY']

    for sid, session in sessions_data.items():
        msg_count = session.get('message_count', 0)
        summary = session.get('summary', '')

        # Check for sensitive data in summary
        has_sensitive = any(p.lower() in summary.lower() for p in sensitive_patterns)

        if has_sensitive:
            sensitive_sessions.append((sid, session))
        elif msg_count < 3 and session.get('failure_count', 0) == 0:
            noise_sessions.append((sid, session))
        else:
            useful_sessions.append((sid, session))

    # Report
    print(f"### Sessions: {len(sessions_data)} total")
    print(f"  - Useful: {len(useful_sessions)}")
    print(f"  - Low-value (< 3 msgs, no failures): {len(noise_sessions)}")
    print(f"  - Contains sensitive data: {len(sensitive_sessions)}")
    print()

    if sensitive_sessions:
        print("### Sessions with sensitive data:")
        for sid, session in sensitive_sessions:
            print(f"  - `{sid[:8]}...` ({format_date(session.get('date', ''))})")
        print()

    if noise_sessions:
        print("### Low-value sessions:")
        for sid, session in noise_sessions[:5]:
            summary = session.get('summary', 'No summary')[:60]
            print(f"  - `{sid[:8]}...`: {summary}")
        if len(noise_sessions) > 5:
            print(f"  ... and {len(noise_sessions) - 5} more")
        print()

    # Analyze failure patterns
    failure_patterns = index.get('failure_patterns', {})
    total_failures = sum(len(v) for v in failure_patterns.values())
    # Count potential duplicates
    dup_count = 0
    for entries in failure_patterns.values():
        seen_cmds = set()
        for e in entries:
            cmd_key = e.get('command', '')[:50]
            if cmd_key in seen_cmds:
                dup_count += 1
            seen_cmds.add(cmd_key)

    print(f"### Failure Patterns: {len(failure_patterns)} categories, {total_failures} entries")
    if dup_count > 0:
        print(f"  {dup_count} duplicate entries found")
    print()

    # Check learnings
    learnings = index.get('learnings', [])
    pending = index.get('pending_learnings', [])
    print(f"### Learnings: {len(learnings)} approved, {len(pending)} pending")
    if learnings:
        categories = set(l.get('category', 'unknown') for l in learnings if isinstance(l, dict))
        print(f"  Categories: {', '.join(sorted(categories))}")
    print()

    # Disk usage
    claude_dir = Path.home() / '.claude' / 'projects' / project_folder
    total_size = 0
    session_count = 0
    agent_count = 0
    agent_size = 0

    for f in claude_dir.glob('*.jsonl'):
        size = f.stat().st_size
        total_size += size
        if f.name.startswith('agent-'):
            agent_count += 1
            agent_size += size
        else:
            session_count += 1

    print(f"### Disk Usage")
    print(f"  - {session_count} session files, {agent_count} agent files")
    print(f"  - {total_size / 1024 / 1024:.1f} MB total ({agent_size / 1024 / 1024:.1f} MB agents)")
    print()

    # Show available cleanup actions
    print("---")
    print("### Cleanup Commands")
    print("  `/recall cleanup --dry-run`    - Re-show this analysis (default)")
    print("  `/recall cleanup --execute`    - Run all cleanup actions")
    print("  `/recall cleanup --noise`      - Remove {0} low-value sessions".format(len(noise_sessions)))
    print("  `/recall cleanup --sensitive`  - Remove {0} sessions with sensitive data".format(len(sensitive_sessions)))
    print("  `/recall cleanup --jsonl`      - Remove old .jsonl files (>30d sessions, >7d agents)")
    print("  `/recall cleanup --dedup`      - Deduplicate {0} failure pattern entries".format(dup_count))

def show_last_session(index: dict, sessions: list, project_folder: str):
    """Show previous session details.

    Uses tiered storage: loads full details from session file if available.
    """
    # Try index first to identify the previous session
    if index and index.get('sessions'):
        sorted_sessions = sorted(
            index['sessions'].items(),
            key=lambda x: x[1].get('date', ''),
            reverse=True
        )

        # Skip current (first), show previous
        if len(sorted_sessions) >= 2:
            session_id, session_summary = sorted_sessions[1]

            # Try to load full details from separate file
            details = load_session_details(project_folder, session_id)

            print("## Previous Session")
            print(f"**Date:** {format_date(session_summary.get('date', ''))}")
            print(f"**Session:** {session_id[:8]}...")
            print(f"**Stats:** {session_summary.get('message_count', 0)} messages, {session_summary.get('command_count', 0)} commands, {session_summary.get('failure_count', 0)} failures")
            print()

            # Use details file if available (has full content)
            if details:
                print("### User Messages:")
                for i, msg in enumerate(details.get('user_messages', [])[:15], 1):
                    content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
                    clean_msg = content.replace('\n', ' ').strip()[:200]
                    if clean_msg:
                        print(f"{i}. {clean_msg}")

                # Show failures if any
                failures = details.get('failures', [])
                if failures:
                    print()
                    print("### Failures:")
                    for f in failures[:5]:
                        cmd = f.get('command', '')[:80]
                        error = f.get('error', '')[:150]
                        print(f"  - `{cmd}`")
                        print(f"    {error}")
            else:
                # Fallback to summary from index
                print("### Summary:")
                print(f"  {session_summary.get('summary', 'No summary')}")
                print()
                print("_(Full details not available - session was indexed before tiered storage)_")
            return

    # Fallback to JSONL parsing
    if len(sessions) < 2:
        print("No previous session found (only current session exists)")
        return

    session = sessions[1]
    data = parse_session(session)

    print("## Previous Session")
    print(f"**Date:** {format_date(data['date'])}")
    print(f"**File:** {data['file']}")
    print()
    print("### User Messages:")
    for i, msg in enumerate(data['user_messages'][:15], 1):
        clean_msg = msg.replace('\n', ' ').strip()
        if clean_msg and not clean_msg.startswith('<'):
            print(f"{i}. {clean_msg[:200]}")

def search_sessions(search_term: str, index: dict, sessions: list, project_folder: str):
    """Search for term across sessions.

    Searches index summaries, detail files, and failure patterns, then ranks
    results locally so the agent does not have to triage broad output.
    """
    print(f"## Top Matches: '{search_term}'")
    print()
    _, query_error = compile_regex_query(search_term)
    if query_error:
        print(f"Invalid regex search: {query_error}")
        print("Use slash-delimited regex like `/.*\\.p8/`, or quote a literal term like `'.p8'`.")
        return

    local_results = collect_search_results(search_term, index, project_folder)
    if local_results:
        for result in local_results:
            session_id = result.get('id', '')
            session = f" ({session_id[:8]}...)" if session_id else ""
            score = result.get('score', 0)
            print(f"### {format_date(result.get('date', ''))}{session} score={score:.3f}")
            print(f"  > {_format_search_result(result)}")
            print()
        return

    # Fallback to JSONL search
    found = False
    for session in sessions[:10]:
        data = parse_session(session, search_term)
        if data['matches']:
            found = True
            print(f"### {format_date(data['date'])} ({data['file'][:8]}...)")
            for match in data['matches'][:3]:
                print(f"  > {match[:200]}...")
            print()

    if found:
        return

    # No local results - search other projects
    print(f"No results in current project ({project_folder}).")
    print()

    all_projects = list_all_project_indices()
    other_projects = [p for p in all_projects if p != project_folder]

    if not other_projects:
        print("No other projects to search.")
        return

    global_results = []

    for proj in other_projects:
        proj_index = load_index(proj)
        if not proj_index:
            continue

        matches = collect_search_results(search_term, proj_index, proj, result_limit=5)
        if matches:
            global_results.append({
                'project': proj,
                'matches': matches,
            })

    if global_results:
        print(f"Found matches in {len(global_results)} other project(s):")
        print()
        for result in global_results:
            proj_name = result['project'].split('-')[-1] if '-' in result['project'] else result['project']
            matches = result.get('matches', [])
            print(f"### {proj_name} ({len(matches)} ranked matches)")
            for match in matches[:3]:
                date = match.get('date', '')[:10]
                print(f"  > [{date}] {_format_search_result(match)[:150]}")
            if len(matches) > 3:
                print(f"  ... and {len(matches) - 3} more ranked matches")
            print()
    else:
        print(f"No matches found for '{search_term}' in any project.")

def list_sessions(index: dict, sessions: list, project_folder: str):
    """List recent sessions with summaries."""
    print("## Recent Sessions")
    print()

    # Use index if available
    if index and index.get('sessions'):
        sorted_sessions = sorted(
            index['sessions'].items(),
            key=lambda x: x[1].get('date', ''),
            reverse=True
        )

        for i, (session_id, session) in enumerate(sorted_sessions[:7]):
            current = " (current)" if i == 0 else ""
            date = format_date(session.get('date', ''))
            summary = session.get('summary', 'No summary')[:150]
            stats = f"[{session.get('message_count', 0)} msgs, {session.get('failure_count', 0)} fails]"

            print(f"**{date}**{current} {stats}")
            print(f"  {summary}")
            print()
        return

    # Fallback to JSONL parsing
    for i, session in enumerate(sessions[:7]):
        data = parse_session(session)
        messages = data['user_messages'][:5]
        summary = "No user messages found"
        for msg in messages:
            if len(msg) > 20:
                summary = msg[:150] + "..." if len(msg) > 150 else msg
                break

        current = " (current)" if i == 0 else ""
        print(f"**{format_date(data['date'])}**{current}")
        print(f"  {summary}")
        print()

def _output_json(data: dict):
    """Write *data* as compact JSON to stdout."""
    print(json.dumps(data, default=str))


def show_knowledge(project_folder: str):
    """Show knowledge loaded from learnings and CLAUDE.md paths."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
        from knowledge import get_learnings, GLOBAL_CLAUDE_MD, get_project_claude_md
    except ImportError as e:
        print(f"Knowledge library not found: {e}")
        return

    print("## Current Knowledge")
    print()
    print(f"**Global:** `{GLOBAL_CLAUDE_MD}`")
    print(f"**Project:** `{get_project_claude_md()}`")
    print()

    learnings = get_learnings(project_folder)
    by_cat = {}
    for lrn in learnings:
        if isinstance(lrn, dict):
            cat = lrn.get('category', 'general')
            by_cat.setdefault(cat, []).append(lrn)

    for cat, cat_learnings in sorted(by_cat.items()):
        print(f"### {cat}")
        for lrn in cat_learnings:
            title = lrn.get('title', 'Unknown')
            fix = lrn.get('fix', '')
            solution = lrn.get('solution', '')
            guidance = fix or solution
            if guidance:
                first_line = guidance.split('\n')[0]
                suffix = '...' if '\n' in guidance else ''
                print(f"  - **{title}**")
                print(f"    {first_line}{suffix}")
            else:
                print(f"  - {title}")
        print()

    if not by_cat:
        print("No knowledge loaded yet.")
        print("Use `/recall learn` to review and approve pending learnings.")


def show_help():
    """Print concise /recall command help."""
    print("## /recall Help")
    print()
    print("`/recall` is one command with script-backed subcommands and search fallback.")
    print()
    print("### Core")
    print("  `/recall`                    List recent sessions")
    print("  `/recall list`               List recent sessions")
    print("  `/recall last`               Show the previous session")
    print("  `/recall <term>`             Search messages, commands, failures, skills")
    print("  `/recall '.p8'`              Search for a literal token or filename fragment")
    print("  `/recall /.*\\.p8/`           Regex search")
    print("  `/recall /*\\.p8/`            Forgiving regex shorthand for the same search")
    print()
    print("### Workflow")
    print("  `/recall save`               Save current work as a restart prompt")
    print("  `/recall restart`            List saved restart prompts")
    print("  `/recall restart <n|text>`   Load by list number, or match by text")
    print("  `/recall restart --launch <n|text>`")
    print("                              Open the restart in a separate window")
    print("  `/recall learn`              Review pending learnings")
    print("  `/recall failures`           Show failure patterns and approved learnings")
    print()
    print("### Maintenance")
    print("  `/recall stats`              Show usage stats")
    print("  `/recall knowledge`          Show loaded knowledge")
    print("  `/recall cleanup`            Analyze cleanup opportunities")
    print("  `/recall help`               Show this help")


def main():
    if len(sys.argv) < 2:
        print("Usage: recall-sessions.py <project_path> [search_term|last|failures]")
        sys.exit(1)

    cwd = sys.argv[1]
    # Strip --json flag before building command string
    remaining_args = [a for a in sys.argv[2:] if a != '--json']
    json_mode = '--json' in sys.argv[2:]
    command = ' '.join(remaining_args) if remaining_args else None
    if command:
        cmd_name = command.split(None, 1)[0].lower()
        if cmd_name in ('help', '--help', '-h'):
            if json_mode:
                _output_json({"commands": [
                    "list", "last", "search", "save", "restart", "learn",
                    "failures", "stats", "knowledge", "cleanup", "help",
                ]})
            else:
                show_help()
            return

    project_folder = get_project_folder(cwd)
    sessions = find_session_files(project_folder)
    index = load_index(project_folder)

    if not sessions and not index:
        print(f"No sessions found for project: {cwd}")
        print(f"Looking in: ~/.claude/projects/{project_folder}")
        sys.exit(0)

    # Handle commands
    if command:
        cmd_lower = command.lower()
        cmd_parts = command.split(None, 1)  # Split into command and argument
        cmd_name = cmd_parts[0].lower()
        cmd_arg = cmd_parts[1] if len(cmd_parts) > 1 else None
        cmd_args = remaining_args[1:]

        if cmd_name == 'list':
            if json_mode and index and index.get('sessions'):
                session_list = [
                    {
                        'id': sid,
                        'date': s.get('date', ''),
                        'summary': s.get('summary', ''),
                        'message_count': s.get('message_count', 0),
                        'failure_count': s.get('failure_count', 0),
                        'topics': s.get('topics', []),
                    }
                    for sid, s in sorted(
                        index['sessions'].items(),
                        key=lambda x: x[1].get('date', ''),
                        reverse=True,
                    )
                ]
                _output_json({"project": project_folder, "sessions": session_list})
            else:
                list_sessions(index, sessions, project_folder)
        elif cmd_name == 'last':
            show_last_session(index, sessions, project_folder)
        elif cmd_name == 'failures':
            if index:
                if json_mode:
                    _output_json({
                        "project": project_folder,
                        "failure_patterns": index.get('failure_patterns', {}),
                        "learnings": index.get('learnings', []),
                    })
                else:
                    show_failures(index, project_folder)
            else:
                print("No index available. Run a session to completion to build the index.")
        elif cmd_name == 'stats':
            if index:
                show_stats(index, project_folder)
            else:
                print("No index available. Run a session to completion to build the index.")
        elif cmd_name == 'export':
            if index:
                export_index(index, project_folder, cmd_arg)
            else:
                print("No index available to export.")
        elif cmd_name == 'import':
            if cmd_arg:
                import_index(project_folder, cmd_arg)
            else:
                print("Usage: /recall import <file>")
                print("Example: /recall import recall-backup.json")
        elif cmd_name == 'reset':
            reset_index(index, project_folder)
        elif cmd_name == 'cleanup':
            show_cleanup_analysis(index, sessions, project_folder, cmd_arg)
        elif cmd_name == 'learn':
            # Run the learn script
            learn_script = Path(__file__).parent / 'recall-learn.py'
            if learn_script.exists():
                import subprocess
                args = ['python3', str(learn_script)]
                args.extend(cmd_args)
                env = os.environ.copy()
                env['CLAUDE_PROJECT_DIR'] = cwd
                subprocess.run(args, env=env)
            else:
                print("Learn script not found. Check installation.")
        elif cmd_name == 'knowledge':
            show_knowledge(project_folder)
        else:
            # Search
            if json_mode and index and index.get('sessions'):
                matches = collect_search_results(command, index, project_folder)
                _output_json({"search_term": command, "matches": matches})
            else:
                search_sessions(command, index, sessions, project_folder)
    else:
        if json_mode and index and index.get('sessions'):
            session_list = [
                {
                    'id': sid,
                    'date': s.get('date', ''),
                    'summary': s.get('summary', ''),
                    'message_count': s.get('message_count', 0),
                    'failure_count': s.get('failure_count', 0),
                    'topics': s.get('topics', []),
                }
                for sid, s in sorted(
                    index['sessions'].items(),
                    key=lambda x: x[1].get('date', ''),
                    reverse=True,
                )
            ]
            _output_json({"project": project_folder, "sessions": session_list})
        else:
            list_sessions(index, sessions, project_folder)


if __name__ == '__main__':
    main()
