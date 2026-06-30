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

from lib.shared import get_project_folder, get_project_dir  # noqa: E402


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
    print(f"Logged save comparison: {path}")
    print(f"Winner: {args.winner}")
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
