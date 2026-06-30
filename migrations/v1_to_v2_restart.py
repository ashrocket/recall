#!/usr/bin/env python3
"""
Migration: v1 (scope-based restarts.json) -> v2 (per-project agents.json)

Reads old restart data from the scope-based system and writes it into the
new recall plugin format.  Prompt files are *copied* (never moved/deleted)
to their new home under ~/.claude/projects/<project_folder>/restarts/.

Old locations read:
  - ~/.claude/restart.json              (scope list — defaults to ~/2code, ~/ashcode)
  - <scope>/restarts.json               (entry array)
  - <scope>/.claude/restarts/<relpath>/<filename>   (prompt files)

New locations written:
  - ~/.claude/projects/<project_folder>/agents.json
  - ~/.claude/projects/<project_folder>/restarts/<filename>

Safety: old files are NEVER deleted.  Pass --cleanup to print what can be
removed manually after verifying the migration.

Usage:
  python3 migrations/v1_to_v2_restart.py                # dry-run (default)
  python3 migrations/v1_to_v2_restart.py --apply         # write new files
  python3 migrations/v1_to_v2_restart.py --apply --cleanup  # write + list old files to delete
"""

import sys
import os
import json
import shutil
import argparse
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Import shared helpers from lib/
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import get_project_folder, get_project_dir, load_agents, save_agents


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOME = Path.home()
SCOPE_CONFIG = HOME / '.claude' / 'restart.json'
DEFAULT_SCOPES = [HOME / '2code', HOME / 'ashcode']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_scope_dirs() -> list[Path]:
    """Read scope directories from ~/.claude/restart.json or fall back to defaults."""
    if SCOPE_CONFIG.exists():
        try:
            with open(SCOPE_CONFIG) as f:
                data = json.load(f)
            dirs = data.get('directories', [])
            return [Path(d).expanduser() for d in dirs]
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: could not parse {SCOPE_CONFIG}: {e}")
    return list(DEFAULT_SCOPES)


def load_old_entries(scope: Path) -> list[dict]:
    """Load entries from <scope>/restarts.json."""
    restarts_file = scope / 'restarts.json'
    if not restarts_file.exists():
        return []
    try:
        with open(restarts_file) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Warning: could not parse {restarts_file}: {e}")
        return []


def resolve_old_prompt_path(entry: dict, scope: Path) -> Path | None:
    """Find the old prompt file on disk.

    The old system stored prompt files at:
        <scope>/.claude/restarts/<relpath>/<filename>
    where relpath = os.path.relpath(working_directory, scope).

    Entries may use either ``prompt_file`` (bare filename) or ``file``
    (sometimes with a ``restarts/`` prefix).  We try multiple strategies.
    """
    # Get the raw reference from whichever field is present
    raw = entry.get('prompt_file') or entry.get('file') or ''
    if not raw:
        return None

    filename = os.path.basename(raw)
    if not filename:
        return None

    wd = entry.get('working_directory', '')
    relpath = os.path.relpath(wd, str(scope)) if wd else '.'

    # Strategy 1: <scope>/.claude/restarts/<relpath>/<filename>
    candidate = scope / '.claude' / 'restarts' / relpath / filename
    if candidate.exists():
        return candidate

    # Strategy 2: <scope>/.claude/<raw>  (for entries where file = "restarts/xxx.md")
    candidate = scope / '.claude' / raw
    if candidate.exists():
        return candidate

    # Strategy 3: <scope>/.claude/restarts/<filename>  (flat fallback)
    candidate = scope / '.claude' / 'restarts' / filename
    if candidate.exists():
        return candidate

    return None


def get_new_prompt_filename(entry: dict) -> str:
    """Derive the prompt filename for the new system.

    Always returns just the basename (no directory prefix).
    """
    raw = entry.get('prompt_file') or entry.get('file') or ''
    if raw:
        return os.path.basename(raw)
    return ''


def map_entry(entry: dict) -> dict:
    """Convert a v1 entry dict to v2 format."""
    prompt_filename = get_new_prompt_filename(entry)
    prompt_ref = f'restarts/{prompt_filename}' if prompt_filename else ''

    return {
        'id': entry.get('number', 0),
        'date': entry.get('date', ''),
        'session_id': entry.get('session_id') or '',
        'working_directory': entry.get('working_directory', ''),
        'summary': entry.get('summary', ''),
        'prompt_file': prompt_ref,
        'platform': 'claude-code',
        'role': entry.get('role', 'lead'),
        'team': entry.get('worker_name', ''),
        'goal': '',
        'comms_file': entry.get('coord_file', ''),
        'status': 'saved',
        'workers': entry.get('workers', []),
        'lead_id': entry.get('lead') if entry.get('lead') is not None else None,
    }


def group_by_project(entries: list[dict], scope: Path) -> dict[str, list[dict]]:
    """Group old entries by their target project_folder."""
    groups = defaultdict(list)
    for entry in entries:
        wd = entry.get('working_directory', str(scope))
        project_folder = get_project_folder(wd)
        groups[project_folder].append(entry)
    return dict(groups)


def deduplicate_ids(agents: list[dict]) -> list[dict]:
    """Reassign IDs where duplicates exist, preserving lead_id references."""
    seen = {}
    remapped = {}  # old_id -> new_id for entries that were renumbered

    # First pass: find the max existing ID
    max_id = max((e.get('id', 0) for e in agents), default=0)

    for entry in agents:
        eid = entry['id']
        if eid in seen:
            max_id += 1
            remapped[id(entry)] = max_id  # use object id to track this specific entry
            entry['id'] = max_id
        else:
            seen[eid] = True

    return agents


# ---------------------------------------------------------------------------
# Migration engine
# ---------------------------------------------------------------------------

def run_migration(apply: bool = False, cleanup: bool = False):
    """Run the v1 -> v2 restart migration.

    Parameters
    ----------
    apply : bool
        When False (default), runs in dry-run mode — no files are written.
    cleanup : bool
        When True (and apply is True), prints old files that can be removed.
    """
    scopes = load_scope_dirs()
    print(f"{'=' * 60}")
    print(f"  Restart Migration: v1 (scope) -> v2 (per-project)")
    print(f"  Mode: {'APPLY' if apply else 'DRY RUN'}")
    print(f"{'=' * 60}\n")

    print(f"Scope config: {SCOPE_CONFIG} ({'exists' if SCOPE_CONFIG.exists() else 'not found, using defaults'})")
    print(f"Scopes: {[str(s) for s in scopes]}\n")

    # Accumulate stats
    total_entries = 0
    total_projects = 0
    total_prompts_copied = 0
    total_prompts_missing = 0
    old_files_to_clean = []
    all_new_agents = defaultdict(list)  # project_folder -> list of mapped entries

    for scope in scopes:
        print(f"--- Scope: {scope} ---")

        if not scope.exists():
            print(f"  Scope directory does not exist, skipping.\n")
            continue

        entries = load_old_entries(scope)
        if not entries:
            print(f"  No entries in {scope / 'restarts.json'}\n")
            continue

        print(f"  Found {len(entries)} entries")
        old_files_to_clean.append(scope / 'restarts.json')

        # Group by project
        by_project = group_by_project(entries, scope)
        print(f"  Mapping to {len(by_project)} project(s):\n")

        for project_folder, project_entries in sorted(by_project.items()):
            print(f"  Project: {project_folder}")
            project_dir = get_project_dir(project_folder)
            restarts_dir = project_dir / 'restarts'

            for old_entry in project_entries:
                total_entries += 1
                new_entry = map_entry(old_entry)

                # Resolve old prompt file
                old_prompt = resolve_old_prompt_path(old_entry, scope)
                prompt_filename = get_new_prompt_filename(old_entry)
                new_prompt_path = restarts_dir / prompt_filename if prompt_filename else None

                eid = new_entry['id']
                summary = new_entry['summary'][:60]
                role = new_entry['role']

                if old_prompt and new_prompt_path:
                    print(f"    #{eid:3d} [{role:6s}] {summary}")
                    print(f"         prompt: {old_prompt.name} -> {new_prompt_path}")
                    total_prompts_copied += 1

                    if apply:
                        restarts_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(old_prompt), str(new_prompt_path))

                    old_files_to_clean.append(old_prompt)

                elif prompt_filename and not old_prompt:
                    print(f"    #{eid:3d} [{role:6s}] {summary}")
                    print(f"         prompt: {prompt_filename} NOT FOUND on disk (skipping copy)")
                    total_prompts_missing += 1

                else:
                    print(f"    #{eid:3d} [{role:6s}] {summary}")
                    print(f"         (no prompt file)")

                all_new_agents[project_folder].append(new_entry)

            print()

    # Merge with any existing agents.json and deduplicate IDs
    for project_folder, new_entries in all_new_agents.items():
        existing = load_agents(project_folder) if apply else []
        existing_ids = {e.get('id') for e in existing}

        # Only add entries whose IDs don't already exist
        to_add = [e for e in new_entries if e['id'] not in existing_ids]
        combined = existing + to_add
        combined = deduplicate_ids(combined)

        total_projects += 1

        if apply:
            save_agents(combined, project_folder)
            agents_path = get_project_dir(project_folder) / 'agents.json'
            print(f"  Wrote {agents_path} ({len(combined)} entries)")

    # Add scope config to cleanup list
    if SCOPE_CONFIG.exists():
        old_files_to_clean.append(SCOPE_CONFIG)

    # Add old .claude/restarts/ directories
    for scope in scopes:
        restarts_dir = scope / '.claude' / 'restarts'
        if restarts_dir.exists():
            old_files_to_clean.append(restarts_dir)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    print(f"  Entries migrated:    {total_entries}")
    print(f"  Projects written to: {total_projects}")
    print(f"  Prompts copied:      {total_prompts_copied}")
    print(f"  Prompts missing:     {total_prompts_missing}")
    print(f"  Mode:                {'APPLIED' if apply else 'DRY RUN (use --apply to write)'}")

    if cleanup and old_files_to_clean:
        print(f"\n  Old files to clean up (delete manually after verifying):")
        for f in sorted(set(old_files_to_clean)):
            marker = 'dir ' if f.is_dir() else 'file'
            print(f"    [{marker}] {f}")
    elif not cleanup and old_files_to_clean:
        print(f"\n  {len(set(old_files_to_clean))} old files/dirs can be cleaned up (pass --cleanup to list)")

    print()
    return total_entries


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Migrate restart data from v1 scope-based system to v2 per-project agents.json.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 migrations/v1_to_v2_restart.py                # dry-run
  python3 migrations/v1_to_v2_restart.py --apply         # write new files
  python3 migrations/v1_to_v2_restart.py --apply --cleanup  # write + list cleanup targets
        """,
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='Actually write new files (default is dry-run)',
    )
    parser.add_argument(
        '--cleanup', action='store_true',
        help='Print old files that can be deleted after migration',
    )

    args = parser.parse_args()

    if args.cleanup and not args.apply:
        print("Warning: --cleanup without --apply just shows what WOULD be listed.\n")

    run_migration(apply=args.apply, cleanup=args.cleanup)


if __name__ == '__main__':
    main()
