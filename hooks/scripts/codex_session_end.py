#!/usr/bin/env python3
"""
Codex session indexer for recall.

Reads a Codex rollout JSONL file and indexes it into recall-index.json
using the same schema as session-end.py.

Codex session format (each line is one JSON entry):
  {"type": "session_meta", "payload": {"id": "...", "cwd": "...", "timestamp": "..."}}
  {"type": "response_item", "payload": {"type": "message", "role": "user",
     "content": [{"type": "input_text", "text": "..."}]}}
  {"type": "response_item", "payload": {"type": "function_call",
     "name": "exec_command", "arguments": '{"cmd":"..."}', "call_id": "..."}}
  {"type": "response_item", "payload": {"type": "function_call_output",
     "call_id": "...", "output": "...Process exited with code 1..."}}

Usage:
    # Index most recent Codex session
    python3 codex_session_end.py --latest

    # Index a specific session file
    python3 codex_session_end.py --file ~/.codex/sessions/2026/03/20/rollout-*.jsonl

    # Specify project dir (overrides cwd from session_meta)
    python3 codex_session_end.py --latest /path/to/project
"""

import sys
import os
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from lib.shared import get_project_folders, load_index, save_index, get_session_details_dir, categorize_error


# ---------------------------------------------------------------------------
# Inlined helpers (mirrors session-end.py to avoid importing hyphenated files)
# ---------------------------------------------------------------------------

MAX_SESSIONS_IN_INDEX = 50
MAX_INDEX_SIZE_KB = 60


def create_session_summary(session_data: dict) -> dict:
    summary_text = session_data.get("summary", "")
    if not summary_text:
        first_msgs = [m["content"][:80] for m in session_data.get("user_messages", [])[:3]]
        summary_text = " | ".join(first_msgs)
    return {
        "date": session_data["date"],
        "summary": summary_text[:200],
        "message_count": len(session_data.get("user_messages", [])),
        "command_count": len(session_data.get("commands", [])),
        "failure_count": len(session_data.get("failures", [])),
        "skill_count": len(session_data.get("skills_used", [])),
        "topics": session_data.get("topics", [])[:10],
        "has_details": True,
        "platform": "codex",
    }


def prune_index(index: dict) -> dict:
    sessions = index.get("sessions", {})
    if not sessions:
        return index
    sorted_sessions = sorted(sessions.items(), key=lambda x: x[1].get("date", ""), reverse=True)
    if len(sorted_sessions) > MAX_SESSIONS_IN_INDEX:
        index["sessions"] = dict(sorted_sessions[:MAX_SESSIONS_IN_INDEX])
        sorted_sessions = list(index["sessions"].items())
    index_size = len(json.dumps(index, default=str))
    target = MAX_INDEX_SIZE_KB * 1024
    while index_size > target and len(sorted_sessions) > 10:
        oldest_id = sorted_sessions[-1][0]
        del index["sessions"][oldest_id]
        sorted_sessions = sorted_sessions[:-1]
        index_size = len(json.dumps(index, default=str))
    return index


def save_session_details(project_folder: str, session_id: str, details: dict) -> bool:
    """Persist the full session details file without failing the hook."""
    try:
        details_dir = get_session_details_dir(project_folder)
        details_dir.mkdir(parents=True, exist_ok=True)
        details_file = details_dir / f"{session_id}.json"
        with open(details_file, "w") as f:
            json.dump(details, f, indent=2, default=str)
        return True
    except OSError as exc:
        print(f"Recall SessionEnd skipped: {exc}", file=sys.stderr)
        return False


def save_index_safely(index: dict, project_folder: str) -> bool:
    """Persist the summary index without failing the hook."""
    try:
        save_index(index, project_folder, prune_fn=prune_index)
        return True
    except OSError as exc:
        print(f"Recall SessionEnd skipped: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Codex session parsing — real JSONL format
# ---------------------------------------------------------------------------

def find_latest_codex_session() -> Optional[Path]:
    """Return the most recently modified rollout JSONL in ~/.codex/sessions/YYYY/MM/DD/."""
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        return None
    candidates = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _extract_exit_code(output: str) -> Optional[int]:
    """Parse 'Process exited with code N' from Codex command output."""
    m = re.search(r"Process exited with code (\d+)", output)
    return int(m.group(1)) if m else None


GOAL_OBJECTIVE_RE = re.compile(r"<objective>\s*(.*?)\s*</objective>", re.DOTALL)


def _normalize_user_text(text: str) -> str:
    """Keep user intent while dropping injected session scaffolding."""
    stripped = (text or "").strip()
    if not stripped:
        return ""
    if stripped.startswith("# AGENTS.md instructions"):
        return ""

    objective = GOAL_OBJECTIVE_RE.search(stripped)
    if stripped.startswith("<goal_context>") and objective:
        return " ".join(objective.group(1).split())

    # Codex injects environment/context blocks as user messages.  Keep this
    # narrow so real user-provided XML-ish prompts are not dropped wholesale.
    if stripped.startswith("<environment_context>"):
        return ""

    return stripped


def parse_codex_rollout(lines: list) -> dict:
    """Parse Codex rollout JSONL lines into recall's session schema."""
    result = {
        "session_id": f"codex-{int(datetime.now().timestamp())}",
        "date": datetime.now().isoformat(),
        "cwd": None,
        "user_messages": [],
        "commands": [],
        "failures": [],
        "failure_patterns": {},
        "topics": [],
        "summary": "",
        "skills_used": [],
    }

    pending_calls: dict = {}  # call_id → command string

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        entry_type = obj.get("type", "")
        payload = obj.get("payload", {})

        # ---- Session metadata -----------------------------------------------
        if entry_type == "session_meta":
            result["session_id"] = f"codex-{payload.get('id', result['session_id'])}"
            ts = payload.get("timestamp", "")
            if ts:
                result["date"] = ts.replace("Z", "+00:00")
            if payload.get("cwd"):
                result["cwd"] = payload["cwd"]

        # ---- Response items -------------------------------------------------
        elif entry_type == "response_item":
            ptype = payload.get("type", "")

            # User messages
            if ptype == "message" and payload.get("role") == "user":
                for block in payload.get("content") or []:
                    text = block.get("text", "") if isinstance(block, dict) else ""
                    text = _normalize_user_text(text)
                    if not text:
                        continue
                    if len(text.strip()) > 10:
                        result["user_messages"].append({
                            "index": len(result["user_messages"]),
                            "content": text[:200],
                            "timestamp": obj.get("timestamp", ""),
                        })

            # Tool calls (commands)
            elif ptype == "function_call" and payload.get("name") == "exec_command":
                try:
                    args = json.loads(payload.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
                command = args.get("cmd", "")
                call_id = payload.get("call_id", "")
                if command:
                    result["commands"].append({
                        "index": len(result["commands"]),
                        "tool_id": call_id,
                        "command": command[:150],
                    })
                    if call_id:
                        pending_calls[call_id] = command

            # Tool outputs (detect failures)
            elif ptype == "function_call_output":
                call_id = payload.get("call_id", "")
                output = payload.get("output", "") or ""
                exit_code = _extract_exit_code(output)
                is_failure = exit_code is not None and exit_code != 0

                if not is_failure:
                    # Also catch error keywords even if exit code is missing
                    is_failure = any(
                        kw in output.lower()
                        for kw in ["error:", "traceback", "exception", "permission denied",
                                   "no such file", "command not found"]
                    )

                if is_failure and call_id in pending_calls:
                    command = pending_calls[call_id]
                    result["failures"].append({
                        "command": command,
                        "error": output[:200],
                        "index": len(result["failures"]),
                    })
                    pattern = categorize_error(output)
                    result["failure_patterns"].setdefault(pattern, []).append({
                        "command": command[:100],
                        "error": output[:200],
                    })

    # Generate summary
    trivial = {"yes", "no", "ok", "okay", "sure", "thanks", "y", "n"}
    meaningful = [
        m["content"] for m in result["user_messages"]
        if m["content"].strip().lower() not in trivial
    ]
    if meaningful:
        result["summary"] = meaningful[0][:150]
        if len(meaningful) > 1 and len(result["summary"]) < 120:
            result["summary"] += f" | {meaningful[1][:60]}"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Index a Codex session into recall-index.json")
    parser.add_argument("project_dir", nargs="?", help="Project directory (default: from session or cwd)")
    parser.add_argument("--file", help="Path to a Codex rollout JSONL file")
    parser.add_argument("--latest", action="store_true", help="Auto-find and index latest Codex session")
    args = parser.parse_args()

    # Load JSONL lines
    lines = None
    if args.file:
        lines = Path(args.file).read_text().splitlines()
    elif args.latest:
        session_file = find_latest_codex_session()
        if not session_file:
            print("No Codex session files found in ~/.codex/sessions/", file=sys.stderr)
            sys.exit(0)
        lines = session_file.read_text().splitlines()
    elif not sys.stdin.isatty():
        lines = sys.stdin.read().splitlines()

    if not lines:
        print("No session data to index.", file=sys.stderr)
        sys.exit(0)

    session_data = parse_codex_rollout(lines)

    # Determine project dir: CLI arg > session_meta.cwd > env > cwd
    cwd = args.project_dir or session_data.get("cwd") or os.environ.get("CODEX_PROJECT") or os.getcwd()
    project_folder, _ = get_project_folders(cwd)

    # Save full details, but never fail the hook when the detail path is
    # unavailable in the current sandbox or runtime environment.
    save_session_details(project_folder, session_data["session_id"], session_data)

    # Update index
    index = load_index(project_folder, create_if_missing=True)
    index["sessions"][session_data["session_id"]] = create_session_summary(session_data)

    for pattern, failures in session_data["failure_patterns"].items():
        index["failure_patterns"].setdefault(pattern, []).extend([
            {**fl, "session_id": session_data["session_id"], "date": session_data["date"], "count": 1}
            for fl in failures
        ])
        index["failure_patterns"][pattern] = index["failure_patterns"][pattern][-15:]

    save_index_safely(index, project_folder)
    print(
        f"Indexed Codex session {session_data['session_id']} "
        f"({len(session_data['user_messages'])} messages, "
        f"{len(session_data['commands'])} commands, "
        f"{len(session_data['failures'])} failures)"
    )


if __name__ == "__main__":
    main()
