#!/usr/bin/env python3
"""
Heuristic knowledge extraction from session data.
Called by index-session.py at the end of each session.

Reads session data from stdin (JSON), proposes learnings based on patterns:
- Repeated failures with the same error category -> propose avoidance strategy
- Commands that failed then succeeded -> propose the working approach
- Tool usage patterns -> propose best practices

Usage:
  echo '{"session_id": "...", ...}' | python3 extract-knowledge.py - <project_folder>
"""

import json
import sys
from pathlib import Path
from collections import Counter

# Add lib to path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from knowledge import add_pending_learning, get_bucket_for_project, DEFAULT_BUCKET


def extract_failure_resolution_pairs(session_data: dict, project_bucket: str = None) -> list:
    if project_bucket is None:
        project_bucket = DEFAULT_BUCKET
    """Find failures followed by successful commands with similar patterns."""
    commands = session_data.get('commands', [])
    failures = session_data.get('failures', [])

    if not failures or not commands:
        return []

    proposals = []
    failed_commands = {f.get('command', '')[:50] for f in failures}

    # Look for commands that are similar to failed ones but appeared later
    for failure in failures:
        failed_cmd = failure.get('command', '')
        failed_prefix = failed_cmd.split()[0] if failed_cmd else ''
        failed_index = failure.get('index', 0)
        error_msg = failure.get('error', '')

        # Find a later command with the same prefix that isn't in failures
        for cmd in commands:
            cmd_text = cmd.get('command', '')
            cmd_prefix = cmd_text.split()[0] if cmd_text else ''
            cmd_index = cmd.get('index', 0)

            if (cmd_prefix == failed_prefix and
                cmd_index > failed_index and
                cmd_text[:50] not in failed_commands):
                # Found a resolution
                proposals.append({
                    'bucket': project_bucket,
                    'category': categorize_for_learning(error_msg),
                    'title': f"Fix for {failed_prefix} failure",
                    'description': f"Command `{failed_cmd[:80]}` failed with: {error_msg[:100]}",
                    'solution': f"Use instead: `{cmd_text[:100]}`",
                    'source': 'failure_resolution',
                    'session_id': session_data.get('session_id', '')
                })
                break

    return proposals


def extract_repeated_failure_patterns(session_data: dict) -> list:
    """Find failure categories that occurred multiple times in one session."""
    failures = session_data.get('failures', [])
    if len(failures) < 2:
        return []

    # Count error categories
    categories = Counter()
    category_examples = {}

    for failure in failures:
        error = failure.get('error', '')
        cat = categorize_for_learning(error)
        categories[cat] += 1
        if cat not in category_examples:
            category_examples[cat] = failure

    proposals = []
    for cat, count in categories.items():
        if count >= 3:  # Only if it happened 3+ times in one session
            example = category_examples[cat]
            proposals.append({
                'bucket': DEFAULT_BUCKET,
                'category': cat,
                'title': f"Recurring {cat} errors ({count}x in session)",
                'description': f"Hit {count} {cat} errors. Example: `{example.get('command', '')[:80]}`",
                'solution': f"Error pattern: {example.get('error', '')[:100]}",
                'source': 'repeated_pattern',
                'session_id': session_data.get('session_id', '')
            })

    return proposals


def categorize_for_learning(error_msg: str) -> str:
    """Map error message to a learning category."""
    error_lower = error_msg.lower()

    mappings = [
        ('shell', ['parse error', 'syntax error', 'unexpected token', 'unterminated', 'bad substitution']),
        ('permissions', ['permission denied', 'access denied', 'eacces']),
        ('paths', ['not found', 'no such file', 'enoent']),
        ('network', ['connection refused', 'timeout', 'econnrefused']),
        ('python', ['traceback', 'import error', 'no module named', 'typeerror']),
        ('git', ['fatal:', 'merge conflict', 'detached head']),
        ('npm', ['npm err', 'npm warn']),
        ('aws', ['expired', 'credentials', 'access denied', 'invalididentity']),
    ]

    for category, keywords in mappings:
        if any(kw in error_lower for kw in keywords):
            return category

    return 'general'


def main():
    # Read session data from stdin
    try:
        session_data = json.load(sys.stdin)
    except (json.JSONDecodeError, IOError):
        print(json.dumps({'proposals_added': 0, 'error': 'invalid input'}))
        sys.exit(0)

    # Get project folder from args
    project_folder = sys.argv[2] if len(sys.argv) > 2 else None
    if not project_folder:
        print(json.dumps({'proposals_added': 0, 'error': 'no project folder'}))
        sys.exit(0)

    # Determine bucket from project
    project_bucket = get_bucket_for_project(project_folder)

    proposals = []

    # Extract resolution pairs (failed then succeeded)
    proposals.extend(extract_failure_resolution_pairs(session_data, project_bucket))

    # Extract repeated failure patterns
    proposals.extend(extract_repeated_failure_patterns(session_data))

    # Add unique proposals to pending
    added = 0
    for proposal in proposals:
        if add_pending_learning(proposal, project_folder):
            added += 1

    print(json.dumps({'proposals_added': added}))


if __name__ == '__main__':
    main()
