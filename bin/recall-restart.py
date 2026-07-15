#!/usr/bin/env python3
"""
Recall restart engine — save, list, launch, and match restart entries.

Usage:
  recall-restart.py save <working_dir> <summary> [flags]
  recall-restart.py list
  recall-restart.py summary
  recall-restart.py show <number>
  recall-restart.py launch <number>
  recall-restart.py match [--launch] <text>
  recall-restart.py delete <number|name|text>

Manages agent restart entries stored in agents.json per-project.
"""

import sys
import os
import json
import re
import hashlib
import shlex
import subprocess
import time
import argparse
from pathlib import Path
from datetime import date
from collections import defaultdict

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import (
    get_project_folder,
    get_project_dir,
    get_restarts_dir,
    get_agents_file,
    load_agents,
    save_agents,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THEMES = [
    'Ocean', 'Homebrew', 'Night Owl', 'Gruvbox-Dark',
    'Nord', 'Cobalt2', 'Catppuccin-Mocha', 'Mariana',
]
ANSI = [
    '\033[36m',   # cyan
    '\033[32m',   # green
    '\033[35m',   # magenta
    '\033[33m',   # yellow
    '\033[34m',   # blue
    '\033[96m',   # bright cyan
    '\033[95m',   # bright magenta
    '\033[93m',   # bright yellow
]
RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'

TICKET_RE = re.compile(r'[A-Z]+-\d+')
SLUG_RE = re.compile(r'[^a-z0-9]+')


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def get_ticket_ids(text: str) -> set:
    """Extract Jira-style ticket IDs from the first 500 chars of text."""
    return set(TICKET_RE.findall(text[:500]))


def get_theme(ids: set, entry: dict) -> tuple:
    """Return a deterministic (theme_name, ansi_code) from ticket IDs or entry data."""
    # Build a stable key from sorted ticket IDs, falling back to summary
    key = ','.join(sorted(ids)) if ids else entry.get('summary', str(entry.get('id', '')))
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    idx = h % len(THEMES)
    return THEMES[idx], ANSI[idx]


def slugify(text: str, max_length: int = 72) -> str:
    """Return a compact lowercase command-friendly name."""
    slug = SLUG_RE.sub('-', text.lower()).strip('-')
    if len(slug) > max_length:
        truncated = slug[:max_length].rstrip('-')
        hyphen = truncated.rfind('-')
        if hyphen >= max_length // 2:
            truncated = truncated[:hyphen]
        slug = truncated
    return slug or 'restart-session'


def entry_session_name(entry: dict) -> str:
    """Return the named-session token users can pass to `/recall restart`."""
    explicit_name = entry.get('name', '')
    if explicit_name:
        return slugify(str(explicit_name))

    prompt_file = entry.get('prompt_file', '')
    if prompt_file:
        return slugify(Path(prompt_file).stem)

    return slugify(entry.get('summary', 'restart-session'))


def _resolve_unique_name(name: str, existing_tokens: set, entry_id) -> str:
    """Return a display name whose slug lookup token is unique.

    When ``slugify(name)`` already exists among *existing_tokens*, append a short
    deterministic suffix derived from *entry_id* until the slug is unique, so
    restart-by-name stays unambiguous (design §4.2).
    """
    if slugify(str(name)) not in existing_tokens:
        return str(name)
    digest = hashlib.md5(str(entry_id).encode()).hexdigest()
    for length in range(4, len(digest) + 1):
        candidate = f"{name}-{digest[:length]}"
        if slugify(candidate) not in existing_tokens:
            return candidate
    return f"{name}-{entry_id}"


def find_child_projects(project_folder: str) -> list:
    """Scan ~/.claude/projects/ for directories starting with project_folder prefix."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return []

    children = []
    for d in projects_dir.iterdir():
        if d.is_dir() and d.name.startswith(project_folder) and d.name != project_folder:
            children.append(d.name)
    return sorted(children)


def collect_all_entries(project_folder: str) -> list:
    """Load agents from the current project and all child projects.

    Returns list of (entry, project_folder) tuples.
    """
    results = []

    # Current project
    for entry in load_agents(project_folder):
        results.append((entry, project_folder))

    # Child projects
    for child in find_child_projects(project_folder):
        for entry in load_agents(child):
            results.append((entry, child))

    return results


# ---------------------------------------------------------------------------
# Union-find grouping
# ---------------------------------------------------------------------------

class UnionFind:
    """Simple union-find for grouping entries by shared identifiers."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def union_find_groups(entries_with_project: list) -> dict:
    """Group entries by shared ticket IDs and parent directories.

    Parameters
    ----------
    entries_with_project : list of (entry, project_folder) tuples

    Returns
    -------
    dict mapping group_key -> list of (entry, project_folder) tuples
    """
    if not entries_with_project:
        return {}

    uf = UnionFind()
    # Map each entry to an index key
    entry_keys = []
    for i, (entry, pf) in enumerate(entries_with_project):
        entry_keys.append(f"entry:{i}")
        uf.find(f"entry:{i}")

    # Build associations via ticket IDs
    ticket_to_entries = defaultdict(list)
    for i, (entry, pf) in enumerate(entries_with_project):
        # Gather text for ticket extraction
        text = entry.get('summary', '') + ' ' + entry.get('prompt_file', '') + ' ' + entry.get('working_directory', '')
        ids = get_ticket_ids(text)
        for tid in ids:
            ticket_to_entries[tid].append(i)

    # Union entries sharing the same ticket
    for tid, indices in ticket_to_entries.items():
        for j in range(1, len(indices)):
            uf.union(f"entry:{indices[0]}", f"entry:{indices[j]}")

    # Also group by parent directory (entries in same parent dir cluster together)
    parent_to_entries = defaultdict(list)
    for i, (entry, pf) in enumerate(entries_with_project):
        wd = entry.get('working_directory', '')
        if wd:
            parent = str(Path(wd).parent)
            parent_to_entries[parent].append(i)

    for parent, indices in parent_to_entries.items():
        for j in range(1, len(indices)):
            uf.union(f"entry:{indices[0]}", f"entry:{indices[j]}")

    # Collect groups
    groups = defaultdict(list)
    for i, (entry, pf) in enumerate(entries_with_project):
        root = uf.find(f"entry:{i}")
        groups[root].append((entry, pf))

    return dict(groups)


# ---------------------------------------------------------------------------
# Launch helpers
# ---------------------------------------------------------------------------

def _resolve_prompt_path(entry: dict, project_folder: str) -> str | None:
    """Return an absolute prompt path for *entry* when one is available."""
    prompt_file = entry.get('prompt_file', '')

    if prompt_file:
        candidate = get_project_dir(project_folder) / prompt_file
        if candidate.exists():
            return str(candidate)
        elif Path(prompt_file).is_absolute() and Path(prompt_file).exists():
            return prompt_file

    return None


def _applescript_string_literal(value: str) -> str:
    """Escape *value* for embedding in a double-quoted AppleScript string literal.

    ``shlex.quote()`` protects the shell layer but can itself introduce ``"``
    characters (its single-quote-escaping fallback); those must in turn be
    escaped for the outer AppleScript ``do script "..."`` literal, or a
    quote/backslash in stored entry data (working dir, summary, checkpoint,
    ...) breaks out of both layers and runs arbitrary shell commands.
    """
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _build_launch_command(entry: dict, project_folder: str) -> tuple[str, str | None]:
    """Build the shell command used by the explicit separate-window launcher."""
    working_dir = entry.get('working_directory', os.getcwd())
    prompt_path = _resolve_prompt_path(entry, project_folder)

    parts = ["unset CLAUDECODE"]
    parts.append(f"cd {shlex.quote(working_dir)}")

    team = entry.get('team', '')
    if team:
        parts.append(f"export CLAUDE_TEAM={shlex.quote(team)}")

    name = entry.get('name', '')
    claude_cmd = "claude"
    if name:
        claude_cmd = f"claude -n {shlex.quote(name)}"

    if prompt_path:
        parts.append(f"cat {shlex.quote(prompt_path)} | {claude_cmd}")
    else:
        summary = entry.get('summary', 'Restart session')
        parts.append(f"echo {shlex.quote(summary)} | {claude_cmd}")

    return ' && '.join(parts), prompt_path


def _print_restart_entry(entry: dict, project_folder: str, display_id=None):
    """Print restart context for loading into the current agent session."""
    summary = entry.get('summary', 'Restart session')
    working_dir = entry.get('working_directory', '')
    prompt_path = _resolve_prompt_path(entry, project_folder)

    id_label = f" {display_id}" if display_id is not None else ""
    print(f"Loading restart{id_label}: {summary}")
    if working_dir:
        print(f"Working directory: {working_dir}")

    if prompt_path:
        print(f"Prompt: {prompt_path}")
        try:
            content = Path(prompt_path).read_text()
        except (IOError, OSError) as exc:
            print(f"Warning: could not read prompt file: {exc}", file=sys.stderr)
            return

        print("\n--- Restart prompt ---")
        print(content.rstrip())
        print("--- End restart prompt ---")
    else:
        print("Prompt: <none>")
        print(f"Summary: {summary}")


def _launch_entry(entry: dict, project_folder: str):
    """Open a Terminal.app tab and launch claude with the entry's prompt."""
    cmd, _prompt_path = _build_launch_command(entry, project_folder)

    # Determine theme
    text = entry.get('summary', '') + ' ' + entry.get('prompt_file', '') + ' ' + entry.get('working_directory', '')
    ids = get_ticket_ids(text)
    theme_name, _ = get_theme(ids, entry)

    # AppleScript to open Terminal tab with theme
    applescript = f'''
    tell application "Terminal"
        activate
        set newTab to do script "{_applescript_string_literal(cmd)}"
        try
            set current settings of newTab to settings set "{theme_name}"
        end try
    end tell
    '''

    try:
        subprocess.run(['osascript', '-e', applescript], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Warning: AppleScript launch failed: {e.stderr.decode()}", file=sys.stderr)
        print(f"Manual command: {cmd}")


# ---------------------------------------------------------------------------
# Subcommand: save
# ---------------------------------------------------------------------------

def cmd_save(args):
    """Save a new restart entry."""
    working_dir = os.path.abspath(args.working_dir)
    summary = args.summary
    project_folder = get_project_folder(working_dir)

    # Load existing entries
    agents = load_agents(project_folder)

    # Compute next ID
    next_id = max((e.get('id', 0) for e in agents), default=0) + 1

    # Resolve a unique display name for named restarts (design §4.2, §6)
    resolved_name = args.name or ''
    if resolved_name:
        existing_tokens = {entry_session_name(e) for e in agents}
        resolved_name = _resolve_unique_name(resolved_name, existing_tokens, next_id)

    # Resolve flags with env var fallbacks
    prompt_file = args.prompt_file or os.environ.get('RESTART_PROMPT_FILE', '')
    role = args.role or os.environ.get('RESTART_ROLE', 'lead')
    platform = args.platform or 'claude-code'
    team = args.team or ''
    goal = args.goal or ''
    comms_file = args.comms_file or ''
    session_id = args.session_id or ''
    resume_checkpoint = args.resume_checkpoint or ''
    lead_id = args.lead_id
    workers = args.workers or []

    # Env var fallbacks for workers/lead
    if not workers:
        env_workers = os.environ.get('RESTART_WORKERS', '')
        if env_workers:
            workers = [w.strip() for w in env_workers.split(',') if w.strip()]

    env_lead = os.environ.get('RESTART_LEAD', '')
    if lead_id is None and env_lead:
        try:
            lead_id = int(env_lead)
        except ValueError:
            pass

    # Build entry
    entry = {
        'id': next_id,
        'date': str(date.today()),
        'session_id': session_id,
        'resume_checkpoint': resume_checkpoint,
        'working_directory': working_dir,
        'summary': summary,
        'name': resolved_name,
        'prompt_file': prompt_file,
        'platform': platform,
        'role': role,
        'team': team,
        'goal': goal,
        'comms_file': comms_file,
        'status': 'saved',
        'workers': workers,
        'lead_id': lead_id,
    }

    agents.append(entry)
    save_agents(agents, project_folder)

    # Confirmation
    print(f"Saved: {summary}")
    print(f"  Project: {project_folder}")
    print(f"  Role: {role} | Platform: {platform}")
    if prompt_file:
        print(f"  Prompt: {prompt_file}")
    print(f"\nRun '/recall restart' to see your saved sessions.")


# ---------------------------------------------------------------------------
# Shared ordering — used by both list and launch so numbers always match
# ---------------------------------------------------------------------------

def ordered_display_entries(project_folder: str) -> list:
    """Return all entries in a stable display order (newest first).

    Returns a flat list of (pos, entry, project_folder) where pos is the
    fresh 1..N display position.  The same ordering is used by both
    cmd_list and cmd_launch so numbers are always consistent.
    """
    all_entries = collect_all_entries(project_folder)

    # Sort: newest date first, then highest stored id as tiebreaker
    def sort_key(item):
        entry, _ = item
        return (entry.get('date', ''), entry.get('id', 0))

    sorted_entries = sorted(all_entries, key=sort_key, reverse=True)
    return [(pos, entry, pf) for pos, (entry, pf) in enumerate(sorted_entries, 1)]


def find_matching_entries(text: str, project_folder: str) -> list:
    """Return restart entries matching *text*.

    Exact named-session token matches win over broader summary/path/content
    matches so commands such as ``restart auth`` remain unambiguous when
    possible.
    """
    search_text = text.lower()
    all_entries = collect_all_entries(project_folder)

    exact_name_matches = []
    matches = []
    for entry, pf in all_entries:
        session_name = entry_session_name(entry)
        if search_text == session_name.lower():
            exact_name_matches.append((entry, pf))
            continue

        if search_text in session_name.lower():
            matches.append((entry, pf))
            continue

        if search_text in entry.get('prompt_file', '').lower():
            matches.append((entry, pf))
            continue

        # Search in summary
        if search_text in entry.get('summary', '').lower():
            matches.append((entry, pf))
            continue

        # Search in prompt file contents
        prompt_file = entry.get('prompt_file', '')
        if prompt_file:
            prompt_path = get_project_dir(pf) / prompt_file
            if prompt_path.exists():
                try:
                    content = prompt_path.read_text()[:2000]
                    if search_text in content.lower():
                        matches.append((entry, pf))
                        continue
                except (IOError, OSError):
                    pass

        # Search in goal
        if search_text in entry.get('goal', '').lower():
            matches.append((entry, pf))
            continue

    return exact_name_matches or matches


def _position_lookup(project_folder: str) -> dict:
    """Return ``(project_folder, internal id) -> display position`` for hints."""
    lookup = {}
    for pos, entry, pf in ordered_display_entries(project_folder):
        eid = entry.get('id')
        if eid is not None:
            lookup[(pf, eid)] = pos
    return lookup


def _print_match_choices(matches: list, project_folder: str):
    """Print compact restart choices with their current list positions."""
    positions = _position_lookup(project_folder)
    for entry, pf in matches:
        eid = entry_session_name(entry)
        pos = positions.get((pf, entry.get('id')))
        pos_label = f"{pos}  " if pos is not None else ""
        summary = entry.get('summary', '')
        role = entry.get('role', '')
        wd = entry.get('working_directory', '')
        home = str(Path.home())
        if wd.startswith(home):
            wd = '~' + wd[len(home):]
        print(f"  {pos_label}{eid}  [{role}]  {summary}")
        print(f"       {DIM}{wd}{RESET}")


def _same_restart_entry(candidate: dict, target: dict) -> bool:
    """Return whether *candidate* is the same stored restart entry as *target*."""
    candidate_id = candidate.get('id')
    target_id = target.get('id')
    if candidate_id is not None and target_id is not None:
        return candidate_id == target_id
    return candidate == target


def _remove_restart_entry(entry: dict, project_folder: str) -> bool:
    """Remove *entry* from *project_folder*'s agents.json."""
    agents = load_agents(project_folder)
    remaining = []
    removed = False
    for candidate in agents:
        if not removed and _same_restart_entry(candidate, entry):
            removed = True
            continue
        remaining.append(candidate)

    if removed:
        save_agents(remaining, project_folder)
    return removed


def _prompt_path_for_deletion(entry: dict, project_folder: str) -> tuple[Path | None, str]:
    """Return a safe prompt path to unlink, or a skip reason.

    Deletion is intentionally limited to files under this project's
    ``recall-restarts`` directory. Older entries may contain absolute prompt
    paths; those are left in place to avoid deleting unrelated files.
    """
    prompt_file = entry.get('prompt_file', '')
    if not prompt_file:
        return None, 'no prompt file recorded'

    prompt_path = _resolve_prompt_path(entry, project_folder)
    if not prompt_path:
        return None, 'prompt file not found'

    try:
        resolved = Path(prompt_path).resolve()
        restarts_dir = get_restarts_dir(project_folder).resolve()
    except OSError as exc:
        return None, f'could not resolve prompt path: {exc}'

    if resolved == restarts_dir or restarts_dir in resolved.parents:
        return resolved, ''

    return None, f'prompt path is outside recall-restarts: {resolved}'


def _delete_restart_prompt(entry: dict, project_folder: str) -> tuple[Path | None, str]:
    """Delete a restart prompt file when it is safe to do so."""
    prompt_path, skip_reason = _prompt_path_for_deletion(entry, project_folder)
    if prompt_path is None:
        return None, skip_reason

    try:
        prompt_path.unlink()
    except FileNotFoundError:
        return None, 'prompt file already missing'
    except OSError as exc:
        raise RuntimeError(f'could not delete prompt file {prompt_path}: {exc}') from exc

    return prompt_path, ''


def _resolve_delete_target(target: str, project_folder: str) -> tuple[dict, str, str]:
    """Resolve a delete target to ``(entry, project_folder, display_label)``."""
    if target.isdigit():
        target_pos = int(target)
        ordered = ordered_display_entries(project_folder)

        if not ordered:
            print("No restart entries found.", file=sys.stderr)
            print("Use '/recall save' to save a session first.", file=sys.stderr)
            sys.exit(1)

        for pos, entry, pf in ordered:
            if pos == target_pos:
                return entry, pf, str(pos)

        print(f"Error: No entry at position {target_pos}.", file=sys.stderr)
        print(f"Run '/recall restart' to see the current list ({len(ordered)} entries).", file=sys.stderr)
        sys.exit(1)

    matches = find_matching_entries(target, project_folder)
    if not matches:
        print(f"No entries matching '{target}'.", file=sys.stderr)
        sys.exit(1)

    if len(matches) > 1:
        print(f"Delete target '{target}' matched {len(matches)} entries:\n")
        _print_match_choices(matches, project_folder)
        print(f"\nUse '/recall restart delete <number>' or a unique named session token.")
        sys.exit(1)

    entry, pf = matches[0]
    return entry, pf, entry_session_name(entry)


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------

def cmd_list(args):
    """List all restart entries with fresh 1..N positional numbers."""
    project_folder = get_project_folder()
    ordered = ordered_display_entries(project_folder)

    if not ordered:
        print("No restart entries found.")
        print(f"  Project: {project_folder}")
        print(f"\nUse '/recall save' to save a session before closing it.")
        return

    # Build worker_map keyed by internal id for nesting display
    all_entries = [(e, pf) for _, e, pf in ordered]
    worker_map = {}
    for entry, pf in all_entries:
        lid = entry.get('lead_id')
        if lid is not None:
            worker_map.setdefault(lid, []).append((entry, pf))

    # Build internal-id → display position map
    pos_map = {entry.get('id'): pos for pos, entry, pf in ordered}

    # Group for display
    groups = union_find_groups(all_entries)

    print(f"{BOLD}Saved Sessions{RESET} ({len(ordered)} total)\n")

    displayed_ids = set()

    for group_key, group_entries in groups.items():
        combined_text = ' '.join(
            e.get('summary', '') + ' ' + e.get('prompt_file', '') + ' ' + e.get('working_directory', '')
            for e, _ in group_entries
        )
        combined_ids = get_ticket_ids(combined_text)
        theme_name, ansi = get_theme(combined_ids, group_entries[0][0])

        ticket_str = ', '.join(sorted(combined_ids)) if combined_ids else 'ungrouped'
        print(f"{ansi}{BOLD}[{ticket_str}]{RESET}  {DIM}theme: {theme_name}{RESET}")

        for entry, pf in group_entries:
            eid = entry.get('id')
            if eid in displayed_ids:
                continue
            displayed_ids.add(eid)

            pos = pos_map.get(eid, '?')
            status = entry.get('status', 'saved')
            role = entry.get('role', '')
            summary = entry.get('summary', '')
            name = entry_session_name(entry)
            wd = entry.get('working_directory', '')

            home = str(Path.home())
            wd_display = ('~' + wd[len(home):]) if wd.startswith(home) else wd

            role_badge = f" [{role}]" if role else ""
            status_icon = {'saved': '+', 'running': '>', 'done': '-'}.get(status, ' ')

            print(f"  {ansi}{status_icon} {pos}{RESET}{role_badge}  {name}")
            if summary and summary != name:
                print(f"    {summary}")
            print(f"    {DIM}{wd_display}{RESET}")

            if eid in worker_map:
                for w_entry, w_pf in worker_map[eid]:
                    wid = w_entry.get('id')
                    if wid in displayed_ids:
                        continue
                    displayed_ids.add(wid)
                    w_pos = pos_map.get(wid, '?')
                    w_name = entry_session_name(w_entry)
                    w_summary = w_entry.get('summary', '')
                    w_role = w_entry.get('role', '')
                    print(f"    {ansi}  -> {w_pos}{RESET} [{w_role}]  {w_name} - {w_summary}")

        print()

    print(f"{DIM}Restart with: /recall restart <number>{RESET}")
    print(f"{DIM}Restart by name: /recall restart <name>{RESET}")
    print(f"{DIM}Open separate windows with: /recall restart --launch <number>{RESET}")
    print(f"{DIM}Review compact list: /recall restart summary{RESET}")
    print(f"{DIM}Delete old prompts: /recall restart delete <number|name>{RESET}")


# ---------------------------------------------------------------------------
# Subcommand: summary
# ---------------------------------------------------------------------------

def cmd_summary(args):
    """Print a compact numbered summary for reviewing or deleting restarts."""
    project_folder = get_project_folder()
    ordered = ordered_display_entries(project_folder)

    if not ordered:
        print("No restart entries found.")
        print(f"  Project: {project_folder}")
        print(f"\nUse '/recall save' to save a session before closing it.")
        return

    print(f"{BOLD}Restart Summary{RESET} ({len(ordered)} total)\n")

    for pos, entry, pf in ordered:
        name = entry_session_name(entry)
        summary = entry.get('summary', '')
        role = entry.get('role', '')
        date_str = entry.get('date', '')
        wd = entry.get('working_directory', '')
        home = str(Path.home())
        wd_display = ('~' + wd[len(home):]) if wd.startswith(home) else wd
        prompt_status = 'prompt: yes' if _resolve_prompt_path(entry, pf) else 'prompt: missing'
        role_badge = f" [{role}]" if role else ""

        print(f"  {pos}  {date_str}  {name}{role_badge}")
        if summary and summary != name:
            print(f"     {summary}")
        print(f"     {DIM}{wd_display}  {prompt_status}{RESET}")

    print(f"\n{DIM}Load: /recall restart <number|name>{RESET}")
    print(f"{DIM}Delete: /recall restart delete <number|name>{RESET}")


# ---------------------------------------------------------------------------
# Subcommand: show
# ---------------------------------------------------------------------------

def cmd_show(args):
    """Print a restart entry by display position without opening a new window."""
    target_pos = args.number
    project_folder = get_project_folder()
    ordered = ordered_display_entries(project_folder)

    if not ordered:
        print("No restart entries found.", file=sys.stderr)
        print("Use '/recall save' to save a session first.", file=sys.stderr)
        sys.exit(1)

    for pos, entry, pf in ordered:
        if pos == target_pos:
            _print_restart_entry(entry, pf, display_id=pos)
            return

    print(f"Error: No entry at position {target_pos}.", file=sys.stderr)
    print(f"Run '/recall restart' to see the current list ({len(ordered)} entries).", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: launch
# ---------------------------------------------------------------------------

def cmd_launch(args):
    """Launch a restart entry by its display position (1..N from /recall restart list)."""
    target_pos = args.number
    project_folder = get_project_folder()
    ordered = ordered_display_entries(project_folder)

    if not ordered:
        print("No restart entries found.", file=sys.stderr)
        print("Use '/recall save' to save a session first.", file=sys.stderr)
        sys.exit(1)

    # Resolve fresh position → entry (same ordering as cmd_list)
    match = None
    match_pf = None
    for pos, entry, pf in ordered:
        if pos == target_pos:
            match = entry
            match_pf = pf
            break

    if not match:
        print(f"Error: No entry at position {target_pos}.", file=sys.stderr)
        print(f"Run '/recall restart' to see the current list ({len(ordered)} entries).", file=sys.stderr)
        sys.exit(1)

    internal_id = match.get('id')
    print(f"Launching {target_pos}: {match.get('summary', '')}")
    _launch_entry(match, match_pf)

    # If this is a lead with workers, launch them too
    workers_list = match.get('workers', [])
    if workers_list:
        all_entries = [(e, pf) for _, e, pf in ordered]
        worker_entries = [
            (e, pf) for e, pf in all_entries
            if e.get('lead_id') == internal_id
        ]
        for w_entry, w_pf in worker_entries:
            time.sleep(1)
            print(f"  Launching worker: {w_entry.get('summary', '')}")
            _launch_entry(w_entry, w_pf)


# ---------------------------------------------------------------------------
# Subcommand: match
# ---------------------------------------------------------------------------

def cmd_match(args):
    """Search entries by text and load or launch if exactly one match."""
    project_folder = get_project_folder()
    matches = find_matching_entries(args.text, project_folder)

    if not matches:
        print(f"No entries matching '{args.text}'.", file=sys.stderr)
        sys.exit(1)

    if len(matches) == 1:
        entry, pf = matches[0]
        session_name = entry_session_name(entry)
        if args.launch:
            print(f"One match found — launching {session_name}: {entry.get('summary', '')}")
            _launch_entry(entry, pf)
        else:
            print(f"One match found — loading {session_name}: {entry.get('summary', '')}")
            _print_restart_entry(entry, pf, display_id=session_name)
        return

    # Multiple matches — display and let user pick
    print(f"Found {len(matches)} matches for '{args.text}':\n")
    _print_match_choices(matches, project_folder)

    print(f"\nUse '/recall restart <name>' to load an exact named session.")
    print(f"Use '/recall restart <number>' to load a specific entry.")
    print(f"Use '/recall restart --launch <number>' to open it in a separate window.")
    print(f"Use '/recall restart delete <number>' to delete an old prompt.")


# ---------------------------------------------------------------------------
# Subcommand: delete
# ---------------------------------------------------------------------------

def cmd_delete(args):
    """Delete a restart entry and its stored prompt file when safe."""
    target = args.target.strip()
    if not target:
        print("Error: delete requires a number, name, or unique text target.", file=sys.stderr)
        sys.exit(1)

    project_folder = get_project_folder()
    entry, entry_project, label = _resolve_delete_target(target, project_folder)
    summary = entry.get('summary', '')

    try:
        deleted_prompt, prompt_note = _delete_restart_prompt(entry, entry_project)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not _remove_restart_entry(entry, entry_project):
        print("Error: restart entry disappeared before it could be deleted.", file=sys.stderr)
        sys.exit(1)

    print(f"Deleted restart {label}: {summary}")
    print(f"  Project: {entry_project}")
    if deleted_prompt is not None:
        print(f"  Prompt file deleted: {deleted_prompt}")
    elif prompt_note:
        print(f"  Prompt file skipped: {prompt_note}")


# ---------------------------------------------------------------------------
# Subcommand: resume
# ---------------------------------------------------------------------------

def _launch_resume_entry(entry: dict):
    """Open a Terminal.app tab running claude --resume <checkpoint>."""
    working_dir = entry.get('working_directory', os.getcwd())
    checkpoint = entry.get('resume_checkpoint', '')

    if not checkpoint:
        print(f"Error: no resume checkpoint stored for this entry.", file=sys.stderr)
        return

    cmd = f"cd {shlex.quote(working_dir)} && claude --resume {shlex.quote(checkpoint)}"

    text = entry.get('summary', '') + ' ' + entry.get('working_directory', '')
    ids = get_ticket_ids(text)
    theme_name, _ = get_theme(ids, entry)

    applescript = f'''
    tell application "Terminal"
        activate
        set newTab to do script "{_applescript_string_literal(cmd)}"
        try
            set current settings of newTab to settings set "{theme_name}"
        end try
    end tell
    '''

    try:
        subprocess.run(['osascript', '-e', applescript], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Warning: AppleScript launch failed: {e.stderr.decode()}", file=sys.stderr)
        print(f"Manual command: {cmd}")


def cmd_resume(args):
    """List entries with native resume tokens, or launch one by position."""
    project_folder = get_project_folder()
    ordered = ordered_display_entries(project_folder)

    resumable = [
        (pos, entry, pf) for pos, entry, pf in ordered
        if entry.get('resume_checkpoint')
    ]

    if not resumable:
        print("No resume tokens saved.")
        print("Run '/recall save' while inside cmux to capture claude session tokens.")
        return

    if args.number is None:
        print(f"{BOLD}Resume Tokens{RESET} ({len(resumable)} sessions)\n")
        for i, (orig_pos, entry, pf) in enumerate(resumable, 1):
            summary = entry.get('summary', '')
            checkpoint = entry.get('resume_checkpoint', '')
            wd = entry.get('working_directory', '')
            date_str = entry.get('date', '')
            home = str(Path.home())
            wd_display = ('~' + wd[len(home):]) if wd.startswith(home) else wd
            text = summary + ' ' + wd
            _, ansi = get_theme(get_ticket_ids(text), entry)
            print(f"  {ansi}{i}{RESET}  {summary}")
            print(f"     {DIM}{wd_display}  {date_str}  checkpoint: {checkpoint[:8]}...{RESET}")
        print(f"\n{DIM}Launch: /recall resume <number>{RESET}")
        return

    if args.number < 1 or args.number > len(resumable):
        print(
            f"Error: No entry at position {args.number}. "
            f"Found {len(resumable)} resumable session(s).",
            file=sys.stderr,
        )
        sys.exit(1)

    _orig_pos, entry, pf = resumable[args.number - 1]
    summary = entry.get('summary', '')
    checkpoint = entry.get('resume_checkpoint', '')
    print(f"Launching resume {args.number}: {summary}")
    print(f"  checkpoint: {checkpoint[:12]}...")
    _launch_resume_entry(entry)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Recall restart engine — save, list, launch, match, and delete restart entries.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest='command', help='Subcommand')

    # save
    save_parser = subparsers.add_parser('save', help='Save a new restart entry')
    save_parser.add_argument('working_dir', help='Working directory for the entry')
    save_parser.add_argument('summary', help='One-line description')
    save_parser.add_argument('--prompt-file', default='', help='Path to prompt file (relative to project dir)')
    save_parser.add_argument('--platform', default='', help='Platform (default: claude-code)')
    save_parser.add_argument('--role', default='', help='Role (default: lead)')
    save_parser.add_argument('--team', default='', help='Team name')
    save_parser.add_argument('--goal', default='', help='Goal description')
    save_parser.add_argument('--comms-file', default='', help='Communications file path')
    save_parser.add_argument('--session-id', default='', help='Session ID')
    save_parser.add_argument('--resume-checkpoint', default='', help='Claude session UUID for native --resume')
    save_parser.add_argument('--lead-id', type=int, default=None, help='Lead agent ID (for workers)')
    save_parser.add_argument('--workers', nargs='*', default=[], help='Worker names/IDs')
    save_parser.add_argument('--name', default='', help='Display name for the restart entry')
    save_parser.set_defaults(func=cmd_save)

    # list
    list_parser = subparsers.add_parser('list', help='List all restart entries')
    list_parser.set_defaults(func=cmd_list)

    # summary
    summary_parser = subparsers.add_parser('summary', help='Print a compact numbered restart summary')
    summary_parser.set_defaults(func=cmd_summary)

    # show
    show_parser = subparsers.add_parser('show', help='Print a restart entry without launching a new window')
    show_parser.add_argument('number', type=int, help='Display position to load')
    show_parser.set_defaults(func=cmd_show)

    # launch
    launch_parser = subparsers.add_parser('launch', help='Launch a restart entry in a separate window')
    launch_parser.add_argument('number', type=int, help='Display position to launch')
    launch_parser.set_defaults(func=cmd_launch)

    # match
    match_parser = subparsers.add_parser('match', help='Search and load a matching entry')
    match_parser.add_argument('--launch', action='store_true', help='Open a matching entry in a separate window')
    match_parser.add_argument('text', help='Text to search for')
    match_parser.set_defaults(func=cmd_match)

    # delete
    delete_parser = subparsers.add_parser('delete', aliases=['rm', 'remove'], help='Delete a restart entry and stored prompt')
    delete_parser.add_argument('target', help='Display number, exact name, or unique text to delete')
    delete_parser.set_defaults(func=cmd_delete)

    # resume
    resume_parser = subparsers.add_parser('resume', help='List or launch sessions by native claude --resume token')
    resume_parser.add_argument('number', type=int, nargs='?', default=None, help='Position to launch (omit to list)')
    resume_parser.set_defaults(func=cmd_resume)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
