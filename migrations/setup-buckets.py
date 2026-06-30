#!/usr/bin/env python3
"""
Migration helper: generate ~/.claude/recall-buckets.json from existing projects.

Scans ~/.claude/projects/ and creates (or updates) the bucket config file
with all discovered project folders. Projects not yet assigned keep the
default bucket ('personal'). Existing assignments are preserved.

Usage:
  python3 migrations/setup-buckets.py [--dry-run]
"""

import json
import sys
from pathlib import Path


BUCKETS_CONFIG_PATH = Path.home() / ".claude" / "recall-buckets.json"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

BUILTIN_BUCKETS = {
    "personal": "Personal — learning, tools, side projects",
    "claude": "Claude — Claude Code functionality, tool behavior, workflow patterns",
}


def load_existing_config() -> dict:
    try:
        with open(BUCKETS_CONFIG_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    return {}


def discover_projects() -> list:
    """Return sorted list of project folder names that have a recall index."""
    if not PROJECTS_DIR.exists():
        return []
    found = []
    for p in PROJECTS_DIR.iterdir():
        if p.is_dir() and (p / "recall-index.json").exists():
            found.append(p.name)
    return sorted(found)


def main():
    dry_run = "--dry-run" in sys.argv

    projects = discover_projects()
    if not projects:
        print("No projects with recall indexes found in ~/.claude/projects/")
        print("Nothing to migrate.")
        return

    existing = load_existing_config()
    existing_map = existing.get("project_map", {})
    existing_buckets = existing.get("buckets", {})
    existing_default = existing.get("default_bucket", "personal")

    # Build updated project_map: preserve existing assignments, default new ones
    new_map = dict(existing_map)
    new_projects = []
    for proj in projects:
        if proj not in new_map:
            new_map[proj] = existing_default
            new_projects.append(proj)

    config = {
        "default_bucket": existing_default,
        "buckets": {**BUILTIN_BUCKETS, **existing_buckets},
        "project_map": new_map,
    }

    # Report
    print(f"Found {len(projects)} project(s) with recall indexes.")
    if new_projects:
        print(f"  {len(new_projects)} new project(s) will be mapped to '{existing_default}':")
        for p in new_projects:
            print(f"    {p}")
    else:
        print("  All projects already have bucket assignments.")

    print()
    print(f"Config path: {BUCKETS_CONFIG_PATH}")

    if dry_run:
        print()
        print("-- Dry run output (not written) --")
        print(json.dumps(config, indent=2))
        return

    if not new_projects and existing:
        print("No changes needed.")
        return

    BUCKETS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BUCKETS_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    print()
    if existing:
        print(f"Updated {BUCKETS_CONFIG_PATH}")
    else:
        print(f"Created {BUCKETS_CONFIG_PATH}")
    print()
    print("Edit that file to assign projects to specific buckets.")
    print("Available buckets:", ", ".join(config["buckets"].keys()))


if __name__ == "__main__":
    main()
