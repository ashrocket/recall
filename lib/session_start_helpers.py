#!/usr/bin/env python3
"""
Session-start helper functions for the session picker.

When SessionStart fires in a directory with no recall history (and not a git repo),
these functions scan all projects for today's sessions and format a picker prompt
so the user can resume context from another project.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def _project_short_name(project_folder: str) -> str:
    """Extract a readable short name from a project_folder string.

    The folder looks like ``-Users-alice-myapp`` (the project's absolute path
    with every ``/`` replaced by ``-``).
    Since dashes encode both path separators and literal dashes in directory
    names, we try to resolve the real filesystem path first.  If the
    original directory exists, we use its actual basename (which preserves
    hyphens like ``recall``).  Otherwise we fall back to the last
    dash-separated segment.
    """
    # Strip leading dash, convert dashes back to slashes
    cleaned = project_folder.lstrip("-")
    naive_path = Path("/" + cleaned.replace("-", "/"))

    # Greedy filesystem resolution: walk from root, at each level try
    # joining remaining segments with dashes to match real dir names.
    parts = cleaned.split("-")
    current = Path("/")
    i = 0
    while i < len(parts):
        # Try progressively longer dash-joined names at this level
        matched = False
        for end in range(len(parts), i, -1):
            candidate_name = "-".join(parts[i:end])
            candidate = current / candidate_name
            if candidate.is_dir():
                current = candidate
                i = end
                matched = True
                break
        if not matched:
            break

    if current != Path("/") and i == len(parts):
        # Fully resolved — use the real directory name
        return current.name

    # Fallback: last dash-separated segment
    return parts[-1] if parts else project_folder


def collect_todays_sessions(projects_dir: Path = None) -> List[dict]:
    """Scan all project directories for sessions from today.

    Parameters
    ----------
    projects_dir : Path, optional
        Root directory containing project folders.  Defaults to
        ``~/.claude/projects``.

    Returns
    -------
    list of dict
        Each dict has keys: ``project_folder``, ``session_count``, ``summary``.
        Sorted by session_count descending.
    """
    if projects_dir is None:
        projects_dir = Path.home() / ".claude" / "projects"

    if not projects_dir.is_dir():
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    results = []

    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue

        index_file = entry / "recall-index.json"
        if not index_file.exists():
            continue

        try:
            with open(index_file, "r") as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            continue

        sessions = index.get("sessions", {})
        if not sessions:
            continue

        # Filter to today's sessions
        today_sessions = []
        for sid, session in sessions.items():
            date_str = session.get("date", "")
            if date_str[:10] == today:
                today_sessions.append((sid, session))

        if not today_sessions:
            continue

        # Sort by date to find the most recent
        today_sessions.sort(key=lambda x: x[1].get("date", ""), reverse=True)
        most_recent = today_sessions[0][1]
        summary = most_recent.get("summary", "No summary")[:80]

        results.append({
            "project_folder": entry.name,
            "session_count": len(today_sessions),
            "summary": summary,
        })

    # Sort by session_count descending
    results.sort(key=lambda x: x["session_count"], reverse=True)
    return results


def format_session_picker(sessions: List[dict]) -> str:
    """Format the session picker output.

    Parameters
    ----------
    sessions : list of dict
        Output from :func:`collect_todays_sessions`.

    Returns
    -------
    str
        Formatted picker text, or empty string if no sessions.
    """
    if not sessions:
        return ""

    lines = [
        "No session history for this directory.",
        "",
        "Today's sessions:",
    ]

    for i, s in enumerate(sessions, start=1):
        short_name = _project_short_name(s["project_folder"])
        count = s["session_count"]
        summary = s["summary"]
        lines.append(f"  {i}. {short_name} [{count} sessions] — {summary}")

    lines.append("")
    lines.append("Resume context from which project? (number, or Enter to skip)")

    return "\n".join(lines)
