#!/usr/bin/env python3
"""Foreground durable SessionEnd queue worker and diagnostics."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lib.session_jobs import (JobError, claim, cleanup, ensure_dirs, move, queue_status,
                              read_job, recover_stale, retry_delay, return_pending,
                              validate_source)
from lib.session_indexing import apply_indexed_session, post_commit
from lib.shared import get_project_folder, get_session_jobs_dir


def _folder(project):
    return get_project_folder(project) if project else None


def _log(root, jid, text):
    path = root / "logs" / f"{jid}.log"
    with path.open("a") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {text}\n")
    os.chmod(path, 0o600)


def _stable_source(job):
    source = validate_source(job["platform"], job["source_path"])
    first = source.stat()
    time.sleep(1)
    second = source.stat()
    return source, first.st_size == second.st_size and first.st_mtime_ns == second.st_mtime_ns


def drain(project=None, max_jobs=2, time_budget=60):
    folder = _folder(project)
    roots = [ensure_dirs(folder)] if folder else list((Path.home() / ".claude" / "projects").glob("*/recall-jobs"))
    deadline = time.monotonic() + time_budget
    processed = 0
    for root in roots:
        if processed >= max_jobs or time.monotonic() >= deadline:
            break
        folder_name = root.parent.name
        recover_stale(folder_name)
        for pending in sorted((root / "pending").glob("*.json")):
            if processed >= max_jobs or time.monotonic() >= deadline:
                break
            try:
                job = read_job(pending)
                if datetime.fromisoformat(job["eligible_after"].replace("Z", "+00:00")) > datetime.now(timezone.utc):
                    continue
            except Exception as exc:
                # A corrupt job never blocks the rest of the queue.
                bad = claim(pending)
                if bad:
                    _log(root, pending.stem, f"terminal malformed job: {exc}")
                    os.replace(bad, root / "failed" / bad.name)
                continue
            running = claim(pending)
            if not running:
                continue
            processed += 1
            try:
                source, stable = _stable_source(job)
                if not stable:
                    _log(root, job["id"], "source still changing; delayed")
                    return_pending(running, job, delay_seconds=5)
                    continue
                committed = apply_indexed_session(folder_name, job["platform"], source, job["id"])
                move(running, "completed", job)
                _log(root, job["id"], "indexed" if committed else "receipt already committed")
                post_commit(folder_name, source, job["platform"])
                cleanup(folder_name)
            except (JobError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
                job["last_error"] = str(exc)
                _log(root, job["id"], f"terminal: {exc}")
                move(running, "failed", job)
            except Exception as exc:
                job["attempts"] += 1
                job["last_error"] = str(exc)
                _log(root, job["id"], f"transient attempt {job['attempts']}: {exc}")
                if job["attempts"] >= 10:
                    move(running, "failed", job)
                else:
                    return_pending(running, job, delay_seconds=retry_delay(job["attempts"]).total_seconds())
    return processed


def install_daemon():
    if sys.platform != "darwin":
        raise SystemExit("LaunchAgent installation is available on macOS only; use `recall jobs drain` on this platform.")
    stable = Path.home() / ".recall"
    if ROOT.resolve() != stable.resolve() or not (stable / "bin" / "recall").exists():
        raise SystemExit("LaunchAgent requires a stable ~/.recall source install; use `recall jobs drain` until it is installed.")
    plist = Path.home() / "Library" / "LaunchAgents" / "com.ashrocket.recall-indexer.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    text = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>com.ashrocket.recall-indexer</string><key>ProgramArguments</key><array><string>{stable}/bin/recall</string><string>jobs</string><string>drain</string><string>--max-jobs</string><string>2</string><string>--time-budget</string><string>60</string></array><key>RunAtLoad</key><true/><key>StartInterval</key><integer>30</integer></dict></plist>\n'''
    plist.write_text(text)
    os.chmod(plist, 0o600)
    domain = f"gui/{os.getuid()}"
    # Reinstalling is intentional and idempotent: remove a prior registration
    # before bootstrapping the new stable-source definition.
    subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True)
    result = subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "launchctl could not load Recall indexer")
    print(plist)


def main():
    # argparse normally requires global options before a subcommand. Keep the
    # public `recall jobs status --project <dir>` spelling ergonomic too.
    raw = sys.argv[1:]
    project_override = None
    if "--project" in raw:
        pos = raw.index("--project")
        if pos + 1 >= len(raw):
            raise SystemExit("--project requires a directory")
        project_override = raw[pos + 1]
        del raw[pos:pos + 2]
    parser = argparse.ArgumentParser(prog="recall jobs")
    parser.add_argument("--project")
    sub = parser.add_subparsers(dest="command", required=True)
    drain_p = sub.add_parser("drain")
    drain_p.add_argument("--max-jobs", type=int, default=2)
    drain_p.add_argument("--time-budget", type=float, default=60)
    sub.add_parser("status")
    show = sub.add_parser("show"); show.add_argument("job_id")
    retry = sub.add_parser("retry"); retry.add_argument("job_id")
    sub.add_parser("install-daemon"); sub.add_parser("uninstall-daemon")
    args = parser.parse_args(raw)
    if project_override:
        args.project = project_override
    folder = _folder(args.project)
    if args.command == "drain":
        print(f"Processed {drain(args.project, args.max_jobs, args.time_budget)} job(s)")
    elif args.command == "status":
        print(json.dumps(queue_status(folder), indent=2))
    elif args.command in {"show", "retry"}:
        roots = [ensure_dirs(folder)] if folder else list((Path.home() / ".claude" / "projects").glob("*/recall-jobs"))
        found = next((root / state / f"{args.job_id}.json" for root in roots for state in ("pending", "running", "completed", "failed") if (root / state / f"{args.job_id}.json").exists()), None)
        if not found: raise SystemExit(f"job not found: {args.job_id}")
        if args.command == "show": print(json.dumps(read_job(found), indent=2))
        else:
            job = read_job(found); job["attempts"] += 1; job["last_error"] = None; job["eligible_after"] = datetime.now(timezone.utc).isoformat()
            move(found, "pending", job); print(f"retried {args.job_id}")
    elif args.command == "install-daemon": install_daemon()
    else:
        plist = Path.home() / "Library" / "LaunchAgents" / "com.ashrocket.recall-indexer.plist"
        if sys.platform == "darwin":
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
        plist.unlink(missing_ok=True); print("uninstalled")


if __name__ == "__main__": main()
