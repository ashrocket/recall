"""Locked, idempotent index commits for durable SessionEnd jobs."""

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.shared import get_project_dir, get_session_details_dir, load_index, save_index

ROOT = Path(__file__).resolve().parent.parent
MAX_SESSIONS = 50


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "hooks" / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_source(platform: str, source: Path) -> dict:
    if platform == "claude":
        return _load_script("recall_claude_parser", "session-end.py").parse_session_full(source)
    if platform == "codex":
        return _load_script("recall_codex_parser", "codex_session_end.py").parse_codex_rollout(source.read_text().splitlines())
    raise ValueError(f"unsupported platform: {platform}")


def create_summary(data: dict, platform: str) -> dict:
    summary = data.get("summary") or " | ".join(m.get("content", "")[:80] for m in data.get("user_messages", [])[:3])
    result = {
        "date": data["date"], "summary": summary[:200],
        "message_count": len(data.get("user_messages", [])),
        "command_count": len(data.get("commands", [])),
        "failure_count": len(data.get("failures", [])),
        "skill_count": len(data.get("skills_used", [])),
        "topics": data.get("topics", [])[:10], "has_details": True,
    }
    if platform == "codex":
        result["platform"] = "codex"
    return result


def prune_index(index: dict) -> dict:
    sessions = sorted(index.get("sessions", {}).items(), key=lambda item: item[1].get("date", ""), reverse=True)
    index["sessions"] = dict(sessions[:MAX_SESSIONS])
    return index


def _details(data: dict) -> dict:
    return {
        key: data.get(key, []) if key in {"user_messages", "commands", "failures", "skills_used"} else data.get(key)
        for key in ("session_id", "date", "summary", "topics", "user_messages", "commands", "failures", "failure_patterns", "skills_used")
    }


def _atomic_details(project_folder: str, session_id: str, data: dict):
    directory = get_session_details_dir(project_folder)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{session_id}.json"
    temp = target.with_suffix(".json.tmp")
    with temp.open("w") as handle:
        json.dump(_details(data), handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    # Full session details (messages, commands) can hold pasted secrets;
    # lock the file down before it lands at its final, discoverable name.
    os.chmod(temp, 0o600)
    os.replace(temp, target)


def _apply(index: dict, data: dict, platform: str):
    sid = data["session_id"]
    index.setdefault("sessions", {})[sid] = create_summary(data, platform)
    index.setdefault("failure_patterns", {})
    # Remove this session's previous contribution before replacing it.
    for pattern in list(index["failure_patterns"]):
        entries = [entry for entry in index["failure_patterns"][pattern] if entry.get("session_id") != sid]
        if entries:
            index["failure_patterns"][pattern] = entries
        else:
            del index["failure_patterns"][pattern]
    for pattern, failures in data.get("failure_patterns", {}).items():
        target = index["failure_patterns"].setdefault(pattern, [])
        target.extend({**failure, "session_id": sid, "date": data["date"], "count": 1} for failure in failures)
        index["failure_patterns"][pattern] = target[-15:]
    usage = index.setdefault("usage", {"skills": {}, "learnings_shown": {}})
    usage.setdefault("skills", {})
    session_usage = index.setdefault("session_skill_usage", {})
    # Exact per-session counters make replacement / retry arithmetic safe.
    old = session_usage.get(sid, {})
    for name, count in old.items():
        entry = usage["skills"].get(name)
        if entry:
            entry["count"] = max(0, entry.get("count", 0) - count)
            entry["sessions"] = [value for value in entry.get("sessions", []) if value != sid]
    fresh = {}
    for skill in data.get("skills_used", []):
        name = skill.get("skill")
        if name:
            fresh[name] = fresh.get(name, 0) + 1
    for name, count in fresh.items():
        entry = usage["skills"].setdefault(name, {"count": 0, "sessions": [], "first_used": data["date"], "last_used": data["date"]})
        entry["count"] += count
        entry["last_used"] = data["date"]
        if sid not in entry["sessions"]:
            entry["sessions"].append(sid)
            entry["sessions"] = entry["sessions"][-10:]
    session_usage[sid] = fresh


def apply_indexed_session(project_folder: str, platform: str, source: Path, job_id: str = None) -> bool:
    """Parse and atomically commit an exact transcript. Returns False if received."""
    project = get_project_dir(project_folder)
    project.mkdir(parents=True, exist_ok=True)
    lock_path = project / "recall-index.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = load_index(project_folder, create_if_missing=True)
        receipts = index.setdefault("job_receipts", {})
        if job_id and job_id in receipts:
            return False
        data = parse_source(platform, source)
        _atomic_details(project_folder, data["session_id"], data)
        _apply(index, data, platform)
        if job_id:
            receipts[job_id] = {"indexed_at": datetime.now(timezone.utc).isoformat(), "session_id": data["session_id"]}
            # Receipts outlive all retry windows (90 days) but remain bounded.
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            for key, receipt in list(receipts.items()):
                try:
                    if datetime.fromisoformat(receipt.get("indexed_at", "").replace("Z", "+00:00")) < cutoff:
                        del receipts[key]
                except (AttributeError, TypeError, ValueError):
                    del receipts[key]
            if len(receipts) > 1000:
                for key in sorted(receipts, key=lambda value: receipts[value].get("indexed_at", ""))[:-1000]:
                    del receipts[key]
        save_index(index, project_folder, prune_fn=prune_index)
        return True


def post_commit(project_folder: str, source: Path, platform: str):
    """Best effort work that must never make a committed job retry."""
    try:
        data = parse_source(platform, source)
        extraction_data = {
            "session_id": data["session_id"], "summary": data.get("summary", ""),
            "user_messages": data.get("user_messages", []), "commands": data.get("commands", []),
            "failures": data.get("failures", []),
        }
        extractor = ROOT / "bin" / "extract-knowledge.py"
        if extractor.exists():
            subprocess.run(
                [sys.executable, str(extractor), "-", project_folder],
                input=json.dumps(extraction_data), text=True, capture_output=True,
                timeout=10, check=False,
            )
    except Exception:
        pass
    try:
        from lib.sync_hooks import maybe_sync_push
        maybe_sync_push()
    except Exception:
        pass
