#!/usr/bin/env python3
"""
SessionEnd hook: Index session data for /recall.

Uses tiered storage:
- recall-index.json: Lightweight summaries (always under token limit)
- recall-sessions/: Full session details stored separately

This ensures the main index stays readable while preserving all data.
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
import re

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.shared import (
    get_project_folder,
    get_project_folders,
    get_session_details_dir,
    load_index as _shared_load_index,
    save_index as _shared_save_index,
    categorize_error,
)

# Index size limits
MAX_SESSIONS_IN_INDEX = 50  # Keep summaries for last 50 sessions
MAX_INDEX_SIZE_KB = 60      # Target max size for main index

# Topic stop words: capitalised English words to skip when extracting topics from message
# text. Using a flat set gives O(1) membership tests; a trie would only help with prefix
# matching or thousands of entries — neither applies here (~80 words, exact match only).
TOPIC_STOP_WORDS = {
    'The', 'This', 'That', 'These', 'Those', 'There', 'Then', 'They',
    'What', 'When', 'Where', 'Which', 'While', 'Who', 'Why', 'How',
    'And', 'But', 'For', 'Not', 'With', 'From', 'Into', 'Over',
    'Can', 'Could', 'Would', 'Should', 'Will', 'May', 'Might',
    'Use', 'Used', 'Using', 'Make', 'Made', 'Get', 'Got', 'Set',
    'Run', 'Let', 'See', 'Try', 'Add', 'Check', 'Show', 'Find',
    'Create', 'Update', 'Delete', 'Remove', 'Change', 'Move',
    'Yes', 'No', 'Ok', 'Sure', 'Thanks', 'Please', 'Also',
    'Here', 'Now', 'Just', 'All', 'Any', 'Some', 'Each', 'Every',
    'New', 'Old', 'First', 'Last', 'Next', 'Other', 'More', 'Most',
    'Need', 'Want', 'Like', 'Look', 'Take', 'Give', 'Keep', 'Put',
    'Does', 'Did', 'Has', 'Have', 'Had', 'Was', 'Were', 'Are',
    'Fix', 'Help', 'Start', 'Stop', 'Open', 'Close', 'Read', 'Write',
}

# Trivial messages to skip in summary generation
TRIVIAL_MESSAGES = {'yes', 'no', 'ok', 'okay', 'sure', 'thanks', 'y', 'n', 'continue', 'go ahead', 'do it'}

# Failure markers for tool results that did NOT report is_error (e.g. exit
# code masked by a pipe). High-precision only: substrings that rarely appear
# in successful output, plus line-anchored markers so quoted code in diff or
# cat output ('+  assert "not found" ...') is not misread as a failure.
FAILURE_SUBSTRINGS = (
    'command not found',
    'permission denied',
    'no such file or directory',
    'traceback (most recent call last)',
)
FAILURE_LINE_RE = re.compile(
    r'^\s*(?:error\b\s*:|fatal:|failed\b|\d+ failed\b|exception\b\s*:)',
    re.IGNORECASE | re.MULTILINE,
)


def looks_like_failure_output(text: str) -> bool:
    """Detect failure output when the platform did not flag is_error."""
    lower = text.lower()
    if any(marker in lower for marker in FAILURE_SUBSTRINGS):
        return True
    return bool(FAILURE_LINE_RE.search(text))


def _find_sessions_in_folder(project_folder: str) -> list:
    """Return session JSONL files in a project folder, sorted newest first."""
    claude_dir = Path.home() / '.claude' / 'projects' / project_folder
    if not claude_dir.exists():
        return []
    sessions = [f for f in claude_dir.glob('*.jsonl') if not f.name.startswith('agent-')]
    sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return sessions


def find_current_session(project_folder: str, also_check_folder: str = None) -> Path:
    """Find the most recent session file.

    Searches *project_folder* first.  When *also_check_folder* is provided
    and differs from *project_folder*, also searches there — this handles
    worktrees where Claude Code writes JSONLs to the worktree-specific
    folder while recall resolves to the main repo's folder.
    """
    sessions = _find_sessions_in_folder(project_folder)
    if sessions:
        return sessions[0]

    if also_check_folder and also_check_folder != project_folder:
        sessions = _find_sessions_in_folder(also_check_folder)
        if sessions:
            return sessions[0]

    return None

def parse_session_full(session_file: Path) -> dict:
    """Parse session file and extract comprehensive data."""
    result = {
        'session_id': session_file.stem,
        'date': datetime.fromtimestamp(session_file.stat().st_mtime).isoformat(),
        'user_messages': [],
        'commands': [],
        'failures': [],
        'failure_patterns': {},
        'topics': set(),
        'summary': '',
        'skills_used': []  # Track skill invocations
    }

    try:
        with open(session_file, 'r') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)

                # Extract user messages
                if obj.get('type') == 'user':
                    msg = obj.get('message', {})
                    if isinstance(msg, dict):
                        content = msg.get('content', '')
                        if isinstance(content, str) and content and not content.startswith('<'):
                            result['user_messages'].append({
                                'index': i,
                                'content': content[:200],  # Reduced from 500
                                'timestamp': obj.get('timestamp', '')
                            })
                            # Extract potential topics (capitalized words, technical terms, file paths)
                            words = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b|\b[a-z]+(?:_[a-z]+)+\b', content)
                            filtered = [w for w in words if w not in TOPIC_STOP_WORDS]
                            result['topics'].update(filtered[:10])
                            # Also extract file paths and technical identifiers
                            paths = re.findall(r'[\w./~-]+\.(?:py|js|ts|json|sh|md|env|yml|yaml)\b', content)
                            result['topics'].update(p.split('/')[-1] for p in paths[:5])

                # Extract tool calls (bash commands and skill invocations)
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', {})
                    if isinstance(msg, dict):
                        content = msg.get('content', [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get('type') == 'tool_use':
                                    tool_name = block.get('name', '')

                                    # Track Bash commands
                                    if tool_name == 'Bash':
                                        cmd_input = block.get('input', {})
                                        command = cmd_input.get('command', '')
                                        if command:
                                            result['commands'].append({
                                                'index': i,
                                                'tool_id': block.get('id', ''),
                                                'command': command[:150]  # Reduced from 300
                                            })

                                    # Track Skill invocations
                                    elif tool_name == 'Skill':
                                        skill_input = block.get('input', {})
                                        skill_name = skill_input.get('skill', '')
                                        if skill_name:
                                            result['skills_used'].append({
                                                'skill': skill_name,
                                                'timestamp': obj.get('timestamp', '')
                                            })

                # Extract tool results (to find failures)
                if obj.get('type') == 'user':
                    msg = obj.get('message', {})
                    if isinstance(msg, dict):
                        content = msg.get('content', [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get('type') == 'tool_result':
                                    tool_content = block.get('content', '')
                                    is_error = block.get('is_error', False)

                                    # Check for error indicators
                                    if is_error or (isinstance(tool_content, str) and looks_like_failure_output(tool_content)):
                                        tool_id = block.get('tool_use_id', '')
                                        # Find the command that caused this
                                        for cmd in result['commands']:
                                            if cmd.get('tool_id') == tool_id:
                                                error_msg = tool_content[:200] if isinstance(tool_content, str) else str(tool_content)[:200]  # Reduced from 500
                                                result['failures'].append({
                                                    'command': cmd['command'],
                                                    'error': error_msg,
                                                    'index': i
                                                })

                                                # Categorize failure pattern
                                                pattern = categorize_error(error_msg)
                                                if pattern:
                                                    if pattern not in result['failure_patterns']:
                                                        result['failure_patterns'][pattern] = []
                                                    result['failure_patterns'][pattern].append({
                                                        'command': cmd['command'][:100],
                                                        'error': error_msg[:200]
                                                    })
                                                break

            except json.JSONDecodeError:
                continue
    except Exception as e:
        result['error'] = str(e)

    # Generate smarter summary
    if result['user_messages']:
        # Filter out trivial and system messages
        meaningful = [
            m['content'] for m in result['user_messages']
            if m['content'].strip().lower() not in TRIVIAL_MESSAGES
            and not m['content'].startswith('/')  # Skip slash commands
            and len(m['content'].strip()) > 10    # Skip very short messages
        ]

        if meaningful:
            # Use first substantial message as primary summary
            primary = meaningful[0][:150]
            # Add skill tag if any skills were used
            if result['skills_used']:
                skill_tag = result['skills_used'][0]['skill'].split(':')[-1]
                result['summary'] = f"[{skill_tag}] {primary}"
            else:
                result['summary'] = primary
            # Append second message if short enough and adds context
            if len(meaningful) > 1 and len(result['summary']) < 120:
                result['summary'] += f" | {meaningful[1][:60]}"
        else:
            # Fallback to old behavior
            first_msgs = [m['content'] for m in result['user_messages'][:3]]
            result['summary'] = ' | '.join(m[:100] for m in first_msgs)

    # Convert topics set to list for JSON serialization
    result['topics'] = list(result['topics'])[:20]

    return result

def load_index(project_folder: str) -> dict:
    """Load existing index or create new one."""
    return _shared_load_index(project_folder, create_if_missing=True)

def save_session_details(project_folder: str, session_id: str, details: dict):
    """Save full session details to a separate file.

    This preserves all data while keeping the main index lightweight.
    """
    details_dir = get_session_details_dir(project_folder)
    details_dir.mkdir(parents=True, exist_ok=True)

    details_file = details_dir / f"{session_id}.json"
    with open(details_file, 'w') as f:
        json.dump(details, f, indent=2, default=str)


def create_session_summary(session_data: dict) -> dict:
    """Create a lightweight summary for the main index.

    Only includes essential info - full details in separate file.
    Uses the pre-computed smart summary from parse_session_full.
    """
    summary_text = session_data.get('summary', '')
    if not summary_text:
        # Fallback
        first_msgs = [m['content'][:80] for m in session_data.get('user_messages', [])[:3]]
        summary_text = ' | '.join(first_msgs)

    return {
        'date': session_data['date'],
        'summary': summary_text[:200],  # Keep summary short
        'message_count': len(session_data.get('user_messages', [])),
        'command_count': len(session_data.get('commands', [])),
        'failure_count': len(session_data.get('failures', [])),
        'skill_count': len(session_data.get('skills_used', [])),
        'topics': session_data.get('topics', [])[:10],  # Limit topics
        'has_details': True  # Flag indicating detail file exists
    }


def prune_index(index: dict, max_sessions: int = MAX_SESSIONS_IN_INDEX, max_index_size_kb: int = MAX_INDEX_SIZE_KB):
    """Prune old session summaries from index to keep under size limits.

    Note: This only removes summaries from index, detail files are preserved.
    """
    sessions = index.get('sessions', {})
    if not sessions:
        return index

    # Sort sessions by date, newest first
    sorted_sessions = sorted(
        sessions.items(),
        key=lambda x: x[1].get('date', ''),
        reverse=True
    )

    # First pass: enforce max sessions limit
    if len(sorted_sessions) > max_sessions:
        keep_sessions = dict(sorted_sessions[:max_sessions])
        index['sessions'] = keep_sessions
        sorted_sessions = list(keep_sessions.items())

    # Second pass: check size and prune further if needed
    index_size = len(json.dumps(index, default=str))
    target_size = max_index_size_kb * 1024

    while index_size > target_size and len(sorted_sessions) > 10:
        # Remove oldest session from index (detail file preserved)
        oldest_id = sorted_sessions[-1][0]
        del index['sessions'][oldest_id]
        sorted_sessions = sorted_sessions[:-1]
        index_size = len(json.dumps(index, default=str))

    return index


def cleanup_old_detail_files(project_folder: str, keep_count: int = 100):
    """Remove oldest detail files to prevent unbounded growth.

    Keeps the most recent `keep_count` session detail files.
    """
    details_dir = get_session_details_dir(project_folder)
    if not details_dir.exists():
        return

    detail_files = sorted(details_dir.glob('*.json'), key=lambda f: f.stat().st_mtime, reverse=True)

    # Remove files beyond keep_count
    for f in detail_files[keep_count:]:
        try:
            f.unlink()
        except (OSError, IOError):
            pass


def cleanup_old_jsonl_files(project_folder: str):
    """Remove old raw .jsonl files to reclaim disk space.

    - Session .jsonl files older than 30 days are removed
    - Agent/subagent .jsonl files older than 7 days are removed
    - The most recent 5 session files are always kept regardless of age
    """
    claude_dir = Path.home() / '.claude' / 'projects' / project_folder
    if not claude_dir.exists():
        return

    now = datetime.now()
    session_max_age = timedelta(days=30)
    agent_max_age = timedelta(days=7)
    freed = 0

    # _find_sessions_in_folder handles glob + agent-prefix filter + mtime sort
    session_files = _find_sessions_in_folder(project_folder)
    agent_files = [f for f in claude_dir.glob('*.jsonl') if f.name.startswith('agent-')]

    # Keep most recent 5 session files regardless of age
    for f in session_files[5:]:  # Skip 5 most recent
        try:
            age = now - datetime.fromtimestamp(f.stat().st_mtime)
            if age > session_max_age:
                size = f.stat().st_size
                f.unlink()
                freed += size
        except (OSError, IOError):
            pass

    # Clean old agent files (more aggressive - 7 days)
    for f in agent_files:
        try:
            age = now - datetime.fromtimestamp(f.stat().st_mtime)
            if age > agent_max_age:
                size = f.stat().st_size
                f.unlink()
                freed += size
        except (OSError, IOError):
            pass

    if freed > 0:
        print(f"  Cleaned {freed / 1024 / 1024:.1f} MB of old session files", file=sys.stderr)


def save_index(project_folder: str, index: dict):
    """Save index to disk, pruning if necessary."""
    _shared_save_index(index, project_folder, prune_fn=prune_index)

def main():
    # Get project path from environment or argument
    cwd = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    if len(sys.argv) > 1:
        cwd = sys.argv[1]

    # resolved = main repo folder (for index storage)
    # raw = literal path folder (where Claude Code writes JSONLs)
    project_folder, raw_folder = get_project_folders(cwd)
    session_file = find_current_session(project_folder, also_check_folder=raw_folder)

    if not session_file:
        print(f"No session found for project: {cwd}", file=sys.stderr)
        sys.exit(0)

    # Parse session (full data)
    session_data = parse_session_full(session_file)
    session_id = session_data['session_id']

    # === TIERED STORAGE ===
    # 1. Save full details to separate file (preserves all data)
    full_details = {
        'session_id': session_id,
        'date': session_data['date'],
        'summary': session_data['summary'],
        'topics': session_data['topics'],
        'user_messages': session_data['user_messages'][:30],  # Full content, up to 30
        'commands': session_data['commands'][:50],  # Up to 50 commands
        'failures': session_data['failures'][:20],  # Up to 20 failures
        'failure_patterns': session_data['failure_patterns'],
        'skills_used': session_data['skills_used'][:30]
    }
    save_session_details(project_folder, session_id, full_details)

    # 2. Store only lightweight summary in main index
    index = load_index(project_folder)
    index['sessions'][session_id] = create_session_summary(session_data)

    # Ensure usage section exists (for older indices)
    if 'usage' not in index:
        index['usage'] = {'skills': {}, 'learnings_shown': {}}

    # Update skill usage stats (kept in main index for quick access)
    for skill_use in session_data['skills_used']:
        skill_name = skill_use['skill']
        if skill_name not in index['usage']['skills']:
            index['usage']['skills'][skill_name] = {
                'count': 0,
                'sessions': [],
                'first_used': session_data['date'],
                'last_used': session_data['date']
            }
        index['usage']['skills'][skill_name]['count'] += 1
        index['usage']['skills'][skill_name]['last_used'] = session_data['date']
        if session_id not in index['usage']['skills'][skill_name]['sessions']:
            index['usage']['skills'][skill_name]['sessions'].append(session_id)
            # Keep only last 10 sessions per skill
            index['usage']['skills'][skill_name]['sessions'] = index['usage']['skills'][skill_name]['sessions'][-10:]

    # Merge failure patterns into global patterns with deduplication
    for pattern, failures in session_data['failure_patterns'].items():
        if pattern not in index['failure_patterns']:
            index['failure_patterns'][pattern] = []

        existing = index['failure_patterns'][pattern]
        existing_cmds = {f.get('command', '')[:50] for f in existing[-5:]}

        for f in failures:
            f['session_id'] = session_id
            f['date'] = session_data['date']
            cmd_prefix = f.get('command', '')[:50]

            # Deduplicate: if same command prefix in recent entries, increment count instead
            if cmd_prefix in existing_cmds:
                for entry in reversed(existing):
                    if entry.get('command', '')[:50] == cmd_prefix:
                        entry['count'] = entry.get('count', 1) + 1
                        entry['date'] = session_data['date']  # Update to latest
                        break
            else:
                f['count'] = 1
                existing.append(f)
                existing_cmds.add(cmd_prefix)

        # Keep only last 15 of each pattern in index
        index['failure_patterns'][pattern] = existing[-15:]

    # Save updated index
    save_index(project_folder, index)

    # === KNOWLEDGE EXTRACTION (v2) ===
    try:
        # Prepare session data for extraction
        extraction_data = {
            'session_id': session_id,
            'summary': session_data['summary'],
            'user_messages': session_data['user_messages'],
            'commands': session_data['commands'],
            'failures': session_data['failures']
        }

        # Run local heuristic extraction
        extract_script = Path(__file__).parent.parent.parent / 'bin' / 'extract-knowledge.py'
        if extract_script.exists():
            import subprocess
            result = subprocess.run(
                ['python3', str(extract_script), '-', project_folder],
                input=json.dumps(extraction_data),
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                extract_result = json.loads(result.stdout)
                proposals = extract_result.get('proposals_added', 0)
                if proposals > 0:
                    print(f"  Proposed {proposals} learnings (run /recall learn to review)", file=sys.stderr)
    except Exception as e:
        # Don't fail indexing if extraction fails
        pass

    # Periodic cleanup (every ~10 sessions)
    import random
    if random.random() < 0.1:
        cleanup_old_detail_files(project_folder)
        cleanup_old_jsonl_files(project_folder)

    # Sync push (if configured)
    try:
        from lib.sync_hooks import maybe_sync_push
        maybe_sync_push()
    except Exception:
        pass  # Never fail indexing due to sync

    skills_msg = f", {len(session_data['skills_used'])} skills" if session_data['skills_used'] else ""
    print(
        f"Indexed session {session_id[:8]}... ({len(session_data['user_messages'])} messages, "
        f"{len(session_data['commands'])} commands, {len(session_data['failures'])} failures{skills_msg})",
        file=sys.stderr,
    )

    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionEnd"}}))

if __name__ == '__main__':
    main()
