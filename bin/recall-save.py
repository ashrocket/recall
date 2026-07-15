#!/usr/bin/env python3
"""Create a recall restart prompt without LLM distillation.

The script indexes the current session when possible, ranks session signals
locally, writes a restart prompt under the project recall directory, and
registers it with recall-restart.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.shared import (  # noqa: E402
    get_project_dir,
    get_project_folders,
    get_restarts_dir,
    load_index,
    load_session_details,
    read_session_title,
    resolve_project_root,
)
from lib.text_rank import rank_texts, slug_from_text, top_terms  # noqa: E402


PATH_RE = re.compile(
    r"(?:[\w.~/-]+/)?[\w.-]+\.(?:py|js|ts|tsx|jsx|json|md|sh|yml|yaml|toml|css|html|swift|kt|java|go|rs)"
)


def run_command(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 10,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run a local command and return ``(returncode, combined_output)``."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def _read_rollout_cwd(path: Path) -> str:
    try:
        with open(path, "r") as handle:
            for _ in range(80):
                raw = handle.readline()
                if not raw:
                    break
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "session_meta":
                    payload = obj.get("payload") or {}
                    return payload.get("cwd", "") or ""
    except OSError:
        return ""
    return ""


def find_latest_codex_rollout_for(working_dir: str) -> Optional[Path]:
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        return None

    try:
        target = Path(working_dir).resolve()
    except OSError:
        target = Path(working_dir)

    candidates = sorted(
        sessions_dir.rglob("rollout-*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        cwd = _read_rollout_cwd(candidate)
        if not cwd:
            continue
        try:
            if Path(cwd).resolve() == target:
                return candidate
        except OSError:
            if cwd == working_dir:
                return candidate
    return None


def _candidate_claude_project_dirs(working_dir: str) -> list[Path]:
    """Return project dirs that may contain Claude transcripts for *working_dir*."""
    try:
        folders = list(dict.fromkeys(get_project_folders(working_dir)))
    except (OSError, ValueError):
        return []
    return [Path.home() / ".claude" / "projects" / folder for folder in folders if folder]


def _transcript_matches_session_id(path: Path, session_id: str) -> bool:
    """Return whether *path* appears to be the Claude transcript for *session_id*."""
    if path.stem == session_id:
        return True
    try:
        with open(path, "r") as handle:
            for _ in range(80):
                raw = handle.readline()
                if not raw:
                    break
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("sessionId") == session_id:
                    return True
                payload = obj.get("payload")
                if isinstance(payload, dict) and payload.get("sessionId") == session_id:
                    return True
    except OSError:
        return False
    return False


def find_claude_transcript_by_session_id(working_dir: str, session_id: str) -> Optional[Path]:
    """Return the Claude transcript matching *session_id* for this project."""
    if not session_id:
        return None
    for claude_dir in _candidate_claude_project_dirs(working_dir):
        if not claude_dir.exists():
            continue
        exact = claude_dir / f"{session_id}.jsonl"
        if exact.exists() and not exact.name.startswith("agent-"):
            return exact
        for session_file in claude_dir.glob("*.jsonl"):
            if session_file.name.startswith("agent-"):
                continue
            if _transcript_matches_session_id(session_file, session_id):
                return session_file
    return None


def _claude_transcripts_by_mtime(working_dir: str) -> list[tuple[Path, float]]:
    """Return non-agent Claude transcripts for this project, newest first."""
    transcripts = []
    for claude_dir in _candidate_claude_project_dirs(working_dir):
        if not claude_dir.exists():
            continue
        for session_file in claude_dir.glob("*.jsonl"):
            if session_file.name.startswith("agent-"):
                continue
            try:
                transcripts.append((session_file, session_file.stat().st_mtime))
            except OSError:
                continue
    transcripts.sort(key=lambda item: item[1], reverse=True)
    return transcripts


def has_ambiguous_active_claude_transcripts(
    working_dir: str,
    within_seconds: int = 300,
) -> bool:
    """Return whether mtime fallback would be unsafe for this project."""
    transcripts = _claude_transcripts_by_mtime(working_dir)
    if len(transcripts) < 2:
        return False
    newest = transcripts[0][1]
    return any(newest - mtime <= within_seconds for _path, mtime in transcripts[1:])


def find_current_claude_transcript(
    working_dir: str,
    session_id: str = "",
) -> Optional[Path]:
    """Return the current non-agent Claude transcript JSONL for *working_dir*.

    When a session id is known, exact transcript identity wins over mtime so a
    concurrent session in the same project cannot steal `/recall save`.
    """
    by_session = find_claude_transcript_by_session_id(working_dir, session_id)
    if by_session is not None:
        return by_session

    newest_path = None
    newest_mtime = None
    for session_file, mtime in _claude_transcripts_by_mtime(working_dir):
        if newest_mtime is None or mtime > newest_mtime:
            newest_mtime = mtime
            newest_path = session_file
    return newest_path


def _latest_claude_session_mtime(working_dir: str, session_id: str = "") -> Optional[float]:
    """mtime of the newest Claude session JSONL for this project, if any."""
    path = find_current_claude_transcript(working_dir, session_id=session_id)
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def detect_auto_platform(working_dir: str, session_id: str = "") -> tuple[str, Optional[Path]]:
    """Pick the platform with the freshest session evidence.

    A Codex rollout existing for this directory is not enough — a live
    Claude session writes its JSONL continuously, so whichever artifact is
    newer is the session the user is actually saving from.
    """
    rollout = find_latest_codex_rollout_for(working_dir)
    if rollout is None:
        return "claude", None
    claude_mtime = _latest_claude_session_mtime(working_dir, session_id=session_id)
    try:
        rollout_mtime = rollout.stat().st_mtime
    except OSError:
        return "claude", None
    if claude_mtime is not None and claude_mtime >= rollout_mtime:
        return "claude", None
    return "codex", rollout


def index_current_session(
    working_dir: str,
    platform: str = "auto",
    claude_session_id: str = "",
) -> str:
    """Index the current session with the cheapest available local parser."""
    if platform == "none":
        return "Indexing skipped (--platform none)."

    if platform == "auto":
        platform, codex_rollout = detect_auto_platform(working_dir, session_id=claude_session_id)
    elif platform == "codex":
        codex_rollout = find_latest_codex_rollout_for(working_dir)
    else:
        codex_rollout = None
    if platform == "codex":
        if codex_rollout is None:
            return "No matching Codex rollout found; indexing skipped."
        script = ROOT / "hooks" / "scripts" / "codex_session_end.py"
        args = ["python3", str(script), "--file", str(codex_rollout), working_dir]
        code, output = run_command(args, cwd=working_dir, timeout=20)
        return output if code == 0 else f"Codex indexing failed: {output}"

    script = ROOT / "hooks" / "scripts" / "session-end.py"
    args = ["python3", str(script), working_dir]
    transcript = find_current_claude_transcript(working_dir, session_id=claude_session_id)
    if claude_session_id == "" and has_ambiguous_active_claude_transcripts(working_dir):
        return "Multiple active Claude transcripts found; indexing skipped because current session id is unavailable."
    if transcript is not None:
        args.extend(["--session-file", str(transcript)])
    code, output = run_command(args, cwd=working_dir, timeout=20)
    return output if code == 0 else f"Claude indexing failed: {output}"


def registration_platform(working_dir: str, requested: str, claude_session_id: str = "") -> str:
    """Choose the platform label to store with the restart entry."""
    if requested == "claude":
        return "claude"
    if requested == "codex":
        return "codex"
    if requested == "auto":
        return detect_auto_platform(working_dir, session_id=claude_session_id)[0]
    return "codex"


def index_output_has_current_session(output: str, skipped: bool) -> bool:
    """Whether it is safe to use newest indexed details for this save."""
    if skipped:
        return True
    return (output or "").startswith("Indexed")


def latest_session(project_folder: str) -> tuple[str, dict, dict]:
    """Return ``(session_id, summary_entry, details)`` for the newest session."""
    index = load_index(project_folder) or {}
    sessions = index.get("sessions") or {}
    if not sessions:
        return "", {}, {}

    ordered = sorted(sessions.items(), key=lambda item: item[1].get("date", ""), reverse=True)
    for session_id, summary_entry in ordered:
        details = load_session_details(project_folder, session_id) or {}
        if details:
            return session_id, summary_entry, details
    session_id, summary_entry = ordered[0]
    return session_id, summary_entry, {}


def git_snapshot(working_dir: str) -> dict:
    branch_code, branch = run_command(["git", "branch", "--show-current"], cwd=working_dir)
    status_code, status = run_command(["git", "status", "--short"], cwd=working_dir)
    log_code, log = run_command(["git", "log", "--oneline", "-5"], cwd=working_dir)

    return {
        "branch": branch if branch_code == 0 and branch else "unknown",
        "status": status if status_code == 0 else "",
        "status_available": status_code == 0,
        "log": log if log_code == 0 else "",
    }


def extract_paths(texts: Iterable[str], limit: int = 12) -> list[str]:
    seen = set()
    paths = []
    for text in texts:
        for match in PATH_RE.findall(text or ""):
            normalized = match.strip("`'\".,)")
            if normalized and normalized not in seen:
                seen.add(normalized)
                paths.append(normalized)
                if len(paths) >= limit:
                    return paths
    return paths


def _truncate(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _bullet_lines(items: Iterable[str], limit: int = 6, code: bool = False) -> str:
    lines = []
    for item in list(items)[:limit]:
        if not item:
            continue
        value = _truncate(item, 200)
        if code:
            value = f"`{value}`"
        lines.append(f"- {value}")
    return "\n".join(lines) if lines else "- None captured."


def _numbered_lines(items: Iterable[str]) -> str:
    lines = []
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. {item}")
    return "\n".join(lines)


def build_restart_prompt(
    *,
    working_dir: str,
    session_id: str,
    summary_entry: dict,
    details: dict,
    git_info: dict,
) -> str:
    summary = details.get("summary") or summary_entry.get("summary") or "Session checkpoint"
    messages = [m.get("content", "") for m in details.get("user_messages", [])]
    commands = [c.get("command", "") for c in details.get("commands", [])]
    failures = details.get("failures", [])
    terms = top_terms([summary, *messages, *commands], limit=8)
    ranked_messages = rank_texts(messages, limit=5, query_terms=terms)
    paths = extract_paths([git_info.get("status", ""), *messages, *commands])

    branch = git_info.get("branch") or "unknown"
    status = git_info.get("status") or ""
    status_available = git_info.get("status_available", True)
    status_summary = (
        "git status unavailable"
        if not status_available
        else ("clean" if not status else f"{len(status.splitlines())} changed path(s)")
    )
    title = " ".join((summary or "Session checkpoint").split()[:8])

    failure_lines = []
    for failure in failures[:5]:
        command = failure.get("command", "")
        error = failure.get("error", "")
        failure_lines.append(f"`{_truncate(command, 90)}` -> {_truncate(error, 140)}")

    restart_items = [
        f"`cd {working_dir}`",
        "Inspect `git status --short` and the files listed below.",
        "Continue from the session focus and key signals; verify behavior before reporting completion.",
    ]
    if commands:
        restart_items.append("Use the recent commands as evidence, not as a script to replay blindly.")

    return f"""# {title} — Session Context

## Generated By
`recall-save.py` using local parsing and extractive TF-IDF ranking. No LLM distillation was used.

## Working Directory
`{working_dir}`

## Branch
`{branch}` ({status_summary})

## Session Focus
{_truncate(summary, 260)}

## Key Signals
{_bullet_lines(ranked_messages, limit=5)}

## Local Keywords
{", ".join(terms) if terms else "None captured."}

## Files And Paths
{_bullet_lines(paths, limit=12, code=True)}

## Git Status
{_bullet_lines(status.splitlines(), limit=20, code=True)}

## Recent Commits
{_bullet_lines((git_info.get("log") or "").splitlines(), limit=5, code=True)}

## Recent Commands
{_bullet_lines(commands[-10:], limit=10, code=True)}

## Failures Or Risks
{_bullet_lines(failure_lines, limit=5)}

## Restart Instructions
{_numbered_lines(restart_items)}

## Source
- Session ID: `{session_id or "not indexed"}`
- Prompt generated from structured recall data and current git state.
"""


def unique_prompt_path(project_folder: str, slug: str) -> Path:
    restarts_dir = get_restarts_dir(project_folder)
    restarts_dir.mkdir(parents=True, exist_ok=True)
    candidate = restarts_dir / f"{slug}.prompt"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 100):
        candidate = restarts_dir / f"{slug}-{suffix}.prompt"
        if not candidate.exists():
            return candidate
    return restarts_dir / f"{slug}-{os.getpid()}.prompt"


def resolve_restart_name(explicit_name: str, platform: str, transcript_path: Optional[Path]) -> str:
    """Resolve the restart display name.

    Order: explicit arg -> the current Claude session's ``customTitle`` -> ""
    (the caller then falls back to the summary slug). Codex sessions have no
    custom title, so only an explicit name applies there.
    """
    if explicit_name:
        return explicit_name
    if platform == "claude" and transcript_path is not None:
        return read_session_title(transcript_path) or ""
    return ""


def register_restart(
    working_dir: str,
    summary: str,
    prompt_path: Path,
    project_folder: str,
    session_id: str,
    platform: str = "codex",
    resume_checkpoint: str = "",
    name: str = "",
) -> str:
    project_dir = get_project_dir(project_folder)
    try:
        relative_prompt = str(prompt_path.relative_to(project_dir))
    except ValueError:
        relative_prompt = str(prompt_path)

    args = [
        "python3",
        str(ROOT / "bin" / "recall-restart.py"),
        "save",
        working_dir,
        _truncate(summary, 90),
        "--prompt-file",
        relative_prompt,
        "--platform",
        "claude-code" if platform == "claude" else "codex",
    ]
    if session_id:
        args.extend(["--session-id", session_id])
    if resume_checkpoint:
        args.extend(["--resume-checkpoint", resume_checkpoint])
    if name:
        args.extend(["--name", name])

    code, output = run_command(args, cwd=working_dir, timeout=10)
    if code != 0:
        return f"Restart registration failed: {output}"
    return output


def cmux_get_resume_checkpoint() -> str:
    """Return the current cmux surface checkpoint_id (Claude session UUID).

    Must be called BEFORE cmux_register_recall overwrites the binding.
    Returns empty string when not in cmux or on error.
    """
    if not os.environ.get("CMUX_SURFACE_ID") or not shutil.which("cmux"):
        return ""
    code, output = run_command(["cmux", "surface", "resume", "show", "--json"], timeout=5)
    if code != 0:
        return ""
    try:
        data = json.loads(output)
        return (data.get("resume_binding") or {}).get("checkpoint_id", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        return ""


def current_claude_session_id() -> str:
    """Return the best known Claude session id for this invocation."""
    for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE_SESSION_ID"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return cmux_get_resume_checkpoint()


def cmux_register_recall(
    working_dir: str,
    prompt_path: Path,
    summary: str,
    session_id: str,
) -> str:
    """Override the cmux surface resume binding to use the recall restart prompt.

    When running inside cmux ($CMUX_SURFACE_ID is set), replaces the default
    `claude --resume <id>` binding with a recall-prompt-fed fresh session so
    that cmux restores via recall rather than native resume.

    Returns a human-readable status line, or an empty string when not in cmux.
    """
    if not os.environ.get("CMUX_SURFACE_ID"):
        return ""

    if not shutil.which("cmux"):
        return ""

    shell_cmd = f"cd '{working_dir}' && cat '{prompt_path}' | claude"
    args = [
        "cmux", "surface", "resume", "set",
        "--kind", "claude",
        "--name", f"Recall: {_truncate(summary, 60)}",
        "--source", "recall",
        "--cwd", working_dir,
        "--shell", shell_cmd,
    ]
    if session_id:
        args.extend(["--checkpoint", session_id])

    code, output = run_command(args, cwd=working_dir, timeout=5)
    if code != 0:
        return f"cmux registration failed: {output}"
    return "Registered with cmux for recall restore."


def save_restart(working_dir: str, platform: str = "auto", skip_index: bool = False, name: str = "") -> int:
    working_dir = os.path.abspath(resolve_project_root(working_dir))
    resume_checkpoint = current_claude_session_id()
    index_output = "Indexing skipped."
    if not skip_index:
        index_output = index_current_session(
            working_dir,
            platform=platform,
            claude_session_id=resume_checkpoint,
        )

    project_folder, _raw_folder = get_project_folders(working_dir)
    if index_output_has_current_session(index_output, skip_index or platform == "none"):
        session_id, summary_entry, details = latest_session(project_folder)
    else:
        session_id, summary_entry, details = "", {}, {}
    summary = details.get("summary") or summary_entry.get("summary") or Path(working_dir).name
    slug = slug_from_text(summary, fallback=Path(working_dir).name)
    git_info = git_snapshot(working_dir)
    prompt = build_restart_prompt(
        working_dir=working_dir,
        session_id=session_id,
        summary_entry=summary_entry,
        details=details,
        git_info=git_info,
    )
    prompt_path = unique_prompt_path(project_folder, slug)
    prompt_path.write_text(prompt)
    entry_platform = registration_platform(working_dir, platform, claude_session_id=resume_checkpoint)
    transcript_path = (
        find_current_claude_transcript(working_dir, session_id=resume_checkpoint)
        if entry_platform == "claude"
        else None
    )
    resolved_name = resolve_restart_name(name, entry_platform, transcript_path)
    registration_output = register_restart(
        working_dir,
        summary,
        prompt_path,
        project_folder,
        session_id,
        entry_platform,
        resume_checkpoint=resume_checkpoint,
        name=resolved_name,
    )

    cmux_output = cmux_register_recall(working_dir, prompt_path, summary, session_id)

    print(index_output)
    print(f"Saved restart prompt: {prompt_path}")
    print(registration_output)
    if cmux_output:
        print(cmux_output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a recall restart prompt without LLM distillation.")
    parser.add_argument("working_dir", nargs="?", default=os.getcwd())
    parser.add_argument("--platform", choices=["auto", "codex", "claude", "none"], default="auto")
    parser.add_argument("--no-index", action="store_true", help="Do not run a session indexer first")
    parser.add_argument("--name", default="", help="Display name for the restart (auto-filled from session title when omitted)")
    args = parser.parse_args()
    return save_restart(args.working_dir, platform=args.platform, skip_index=args.no_index, name=args.name)


if __name__ == "__main__":
    raise SystemExit(main())
