#!/usr/bin/env python3
"""Helpers for logging LLM-vs-local recall save comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.shared import (  # noqa: E402
    get_project_folder,
    get_project_dir,
    load_agents,
    save_agents,
)


WINNERS = {"local", "llm", "tie"}


def prompt_stats(path: str) -> dict:
    """Return basic deterministic prompt stats."""
    prompt_path = Path(path)
    text = prompt_path.read_text()
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {
        "path": str(prompt_path),
        "sha256": digest,
        "chars": len(text),
        "words": len(re.findall(r"\S+", text)),
    }


def eval_log_path(project_folder: str) -> Path:
    """Return the JSONL log path for save comparison records."""
    project_dir = get_project_dir(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / "recall-save-evals.jsonl"


def unique_llm_prompt_path(local_prompt: str) -> Path:
    """Return a sibling path for the LLM-generated comparison candidate."""
    local_path = Path(local_prompt)
    parent = local_path.parent
    stem = local_path.stem
    candidate = parent / f"{stem}.llm.prompt"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 100):
        candidate = parent / f"{stem}.llm-{suffix}.prompt"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}.llm-{os.getpid()}.prompt"


def registry_prompt_value(project_folder: str, prompt: str) -> str:
    """Return the prompt path form stored in agents.json."""
    prompt_path = Path(prompt)
    if not prompt_path.is_absolute():
        return str(prompt_path)

    try:
        return str(prompt_path.relative_to(get_project_dir(project_folder)))
    except ValueError:
        return str(prompt_path)


def prompt_matches_registry(project_folder: str, entry_prompt: str, prompt: str) -> bool:
    """Return whether an agents.json prompt entry points at prompt."""
    if not entry_prompt:
        return False
    if entry_prompt == prompt:
        return True
    if entry_prompt == registry_prompt_value(project_folder, prompt):
        return True

    project_dir = get_project_dir(project_folder)
    entry_path = Path(entry_prompt)
    prompt_path = Path(prompt)
    if not entry_path.is_absolute():
        entry_path = project_dir / entry_path
    if not prompt_path.is_absolute():
        prompt_path = project_dir / prompt_path
    return entry_path == prompt_path


def promote_llm_winner(project_folder: str, local_prompt: str, llm_prompt: str) -> int:
    """Point matching restart registry entries at the LLM prompt."""
    agents = load_agents(project_folder)
    replacement = registry_prompt_value(project_folder, llm_prompt)
    changed = 0
    for entry in agents:
        if prompt_matches_registry(project_folder, entry.get("prompt_file", ""), local_prompt):
            if entry.get("prompt_file") != replacement:
                entry["prompt_file"] = replacement
                changed += 1
    if changed:
        save_agents(agents, project_folder)
    return changed


def build_log_entry(
    *,
    working_dir: str,
    local_prompt: str,
    llm_prompt: str,
    winner: str,
    reason: str,
) -> dict:
    if winner not in WINNERS:
        raise ValueError(f"winner must be one of: {', '.join(sorted(WINNERS))}")

    return {
        "date": datetime.now(timezone.utc).isoformat(),
        "working_directory": os.path.abspath(working_dir),
        "judge": "llm",
        "winner": winner,
        "reason": reason,
        "local": prompt_stats(local_prompt),
        "llm": prompt_stats(llm_prompt),
    }


def append_log(project_folder: str, entry: dict) -> Path:
    path = eval_log_path(project_folder)
    with open(path, "a") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return path


def cmd_candidate(args) -> int:
    path = unique_llm_prompt_path(args.local_prompt)
    path.parent.mkdir(parents=True, exist_ok=True)
    print(path)
    return 0


def cmd_log(args) -> int:
    project_folder = get_project_folder(args.working_dir)
    try:
        entry = build_log_entry(
            working_dir=args.working_dir,
            local_prompt=args.local_prompt,
            llm_prompt=args.llm_prompt,
            winner=args.winner,
            reason=args.reason,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = append_log(project_folder, entry)
    promoted = 0
    if args.winner == "llm":
        promoted = promote_llm_winner(project_folder, args.local_prompt, args.llm_prompt)

    print(f"Logged save comparison: {path}")
    print(f"Winner: {args.winner}")
    if promoted:
        print(f"Promoted LLM prompt in restart registry: {promoted} entry(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Log LLM-vs-local recall save comparisons.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidate = subparsers.add_parser("candidate", help="Print a path for the LLM comparison prompt")
    candidate.add_argument("--local-prompt", required=True)
    candidate.set_defaults(func=cmd_candidate)

    log = subparsers.add_parser("log", help="Append a save comparison JSONL record")
    log.add_argument("working_dir")
    log.add_argument("--local-prompt", required=True)
    log.add_argument("--llm-prompt", required=True)
    log.add_argument("--winner", required=True, choices=sorted(WINNERS))
    log.add_argument("--reason", required=True)
    log.set_defaults(func=cmd_log)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
