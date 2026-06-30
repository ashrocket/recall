#!/usr/bin/env python3
"""
Migration: Add tiered storage for recall index.

Extracts full session details into separate files,
leaving only lightweight summaries in the main index.
This keeps the index under Claude's Read tool token limit.
"""

import json
from pathlib import Path

VERSION_FROM = "1.0.0"
VERSION_TO = "1.1.0"


def get_index_files():
    """Find all recall-index.json files across projects."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return []
    return list(projects_dir.glob('*/recall-index.json'))


def check_needed() -> bool:
    """Return True if any index needs migration."""
    for index_file in get_index_files():
        try:
            with open(index_file) as f:
                index = json.load(f)

            # Check if any session has user_messages (old format)
            for session in index.get('sessions', {}).values():
                if 'user_messages' in session and session['user_messages']:
                    # Check if it's full content vs summary
                    if not session.get('has_details'):
                        return True
        except (json.JSONDecodeError, IOError, OSError):
            continue
    return False


def migrate() -> bool:
    """Run the migration. Return True on success."""
    migrated_count = 0

    for index_file in get_index_files():
        try:
            with open(index_file) as f:
                index = json.load(f)

            project_folder = index_file.parent.name
            details_dir = index_file.parent / 'recall-sessions'
            details_dir.mkdir(exist_ok=True)

            sessions = index.get('sessions', {})

            for session_id, session_data in sessions.items():
                # Skip if already migrated
                if session_data.get('has_details'):
                    continue

                has_messages = 'user_messages' in session_data and session_data['user_messages']
                has_failures = 'failures' in session_data and session_data['failures']

                if has_messages or has_failures:
                    # Save full details to separate file
                    details = {
                        'session_id': session_id,
                        'date': session_data.get('date', ''),
                        'summary': session_data.get('summary', ''),
                        'topics': session_data.get('topics', []),
                        'user_messages': session_data.get('user_messages', []),
                        'failures': session_data.get('failures', []),
                        'skills_used': session_data.get('skills_used', [])
                    }

                    details_file = details_dir / f"{session_id}.json"
                    with open(details_file, 'w') as f:
                        json.dump(details, f, indent=2, default=str)

                    # Slim down session in index
                    first_msgs = [
                        m.get('content', '')[:80] if isinstance(m, dict) else str(m)[:80]
                        for m in session_data.get('user_messages', [])[:3]
                    ]
                    summary_text = ' | '.join(first_msgs)

                    sessions[session_id] = {
                        'date': session_data.get('date', ''),
                        'summary': summary_text[:200],
                        'message_count': session_data.get('message_count', len(session_data.get('user_messages', []))),
                        'command_count': session_data.get('command_count', 0),
                        'failure_count': session_data.get('failure_count', len(session_data.get('failures', []))),
                        'skill_count': session_data.get('skill_count', len(session_data.get('skills_used', []))),
                        'topics': session_data.get('topics', [])[:10],
                        'has_details': True
                    }
                    migrated_count += 1

            # Update version and save
            index['version'] = 3
            index['sessions'] = sessions

            with open(index_file, 'w') as f:
                json.dump(index, f, indent=2, default=str)

        except Exception as e:
            print(f"Error migrating {index_file}: {e}")
            return False

    print(f"Migrated {migrated_count} sessions to tiered storage")
    return True


def rollback() -> bool:
    """Rollback not supported for this migration."""
    print("Rollback not supported - detail files are preserved")
    return False


if __name__ == "__main__":
    if check_needed():
        print("Running tiered storage migration...")
        if migrate():
            print("Migration complete")
        else:
            print("Migration failed")
    else:
        print("Migration not needed")
