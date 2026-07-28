"""Durable, metadata-only SessionEnd job queue.

The queue deliberately has no daemon dependency: hooks enqueue, and a bounded
foreground worker claims jobs using atomic renames.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from lib.shared import get_session_jobs_dir

SCHEMA_VERSION = 1
STATES = ("pending", "running", "completed", "failed", "logs")
LEASE = timedelta(minutes=5)
BACKOFF_MINUTES = (1, 5, 30, 180)


class JobError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _iso(value=None):
    return (value or _now()).isoformat()


def _parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def allowed_root(platform: str) -> Path:
    if platform == "claude":
        return Path.home() / ".claude" / "projects"
    if platform == "codex":
        return Path.home() / ".codex" / "sessions"
    raise JobError(f"unsupported platform: {platform}")


def validate_source(platform: str, source_path: str) -> Path:
    source = Path(source_path).expanduser().resolve(strict=True)
    root = allowed_root(platform).resolve()
    try:
        source.relative_to(root)
    except ValueError:
        raise JobError(f"source is outside {root}")
    if not source.is_file():
        raise JobError("source is not a regular file")
    return source


def job_id(platform: str, source: Path) -> str:
    value = f"{platform}\0{source.resolve()}".encode()
    return hashlib.sha256(value).hexdigest()[:32]


def ensure_dirs(project_folder: str) -> Path:
    root = get_session_jobs_dir(project_folder)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    for state in STATES:
        path = root / state
        path.mkdir(exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
    return root


def validate_job(job: dict) -> dict:
    required = {"schema_version", "id", "platform", "source_path", "project_dir", "project_folder", "source_size", "source_mtime_ns", "enqueued_at", "eligible_after", "attempts", "last_error"}
    if not isinstance(job, dict) or set(job) != required:
        raise JobError("malformed job schema")
    if job["schema_version"] != SCHEMA_VERSION or job["platform"] not in {"claude", "codex"}:
        raise JobError("unsupported job schema or platform")
    if not isinstance(job["attempts"], int) or job["attempts"] < 0:
        raise JobError("invalid attempts")
    if job_id(job["platform"], Path(job["source_path"])) != job["id"]:
        raise JobError("job id does not match source")
    return job


def _write_json(path: Path, payload: dict):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _write_new_json(path: Path, payload: dict) -> bool:
    """Create *path* once without replacing a competing enqueuer's job."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        try:
            # link(2) is exclusive for the destination name, unlike rename.
            os.link(tmp, path)
        except FileExistsError:
            return False
        os.chmod(path, 0o600)
        return True
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def enqueue(platform: str, source_path: str, project_dir: str, project_folder: str, eligible_after=None) -> Optional[dict]:
    """Validate an exact source and add it once.  Returns None when present."""
    source = validate_source(platform, source_path)
    root = ensure_dirs(project_folder)
    jid = job_id(platform, source)
    if any((root / state / f"{jid}.json").exists() for state in STATES if state != "logs"):
        return None
    stat = source.stat()
    job = {
        "schema_version": SCHEMA_VERSION, "id": jid, "platform": platform,
        "source_path": str(source), "project_dir": str(Path(project_dir).expanduser().resolve()),
        "project_folder": project_folder, "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns, "enqueued_at": _iso(),
        "eligible_after": _iso(eligible_after), "attempts": 0, "last_error": None,
    }
    if not _write_new_json(root / "pending" / f"{jid}.json", job):
        return None
    return job


def read_job(path: Path) -> dict:
    with path.open() as handle:
        return validate_job(json.load(handle))


def claim(path: Path) -> Optional[Path]:
    target = path.parent.parent / "running" / path.name
    try:
        # os.replace would let a second claimer overwrite the first worker's
        # running record. An exclusive hard link creates the lease atomically;
        # unlinking the pending name afterwards is safe because both names
        # refer to the same immutable job content.
        os.link(path, target)
    except (FileNotFoundError, FileExistsError):
        return None
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return target


def return_pending(path: Path, job: dict, delay_seconds=0):
    job["eligible_after"] = _iso(_now() + timedelta(seconds=delay_seconds))
    _write_json(path, job)
    os.replace(path, path.parent.parent / "pending" / path.name)


def move(path: Path, state: str, job: dict):
    _write_json(path, job)
    os.replace(path, path.parent.parent / state / path.name)


def retry_delay(attempts: int) -> timedelta:
    if attempts <= len(BACKOFF_MINUTES):
        return timedelta(minutes=BACKOFF_MINUTES[attempts - 1])
    return timedelta(days=1)


def recover_stale(project_folder: str) -> int:
    root = ensure_dirs(project_folder)
    recovered = 0
    for path in root.joinpath("running").glob("*.json"):
        try:
            if _now() - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > LEASE:
                pending = root / "pending" / path.name
                if pending.exists():
                    # A process can die after link(2) but before unlinking
                    # pending. Keep that original queue entry and discard the
                    # stale lease rather than overwriting either record.
                    path.unlink()
                else:
                    os.replace(path, pending)
                recovered += 1
        except FileNotFoundError:
            pass
    return recovered


def queue_status(project_folder: Optional[str] = None) -> dict:
    roots = [ensure_dirs(project_folder)] if project_folder else list((Path.home() / ".claude" / "projects").glob("*/recall-jobs"))
    result = {state: [] for state in ("pending", "running", "completed", "failed")}
    for root in roots:
        for state in result:
            for path in (root / state).glob("*.json"):
                try:
                    result[state].append(read_job(path))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    result["failed"].append({"id": path.stem, "last_error": f"malformed job: {exc}", "project_folder": root.parent.name})
    return result


def cleanup(project_folder: str, completed_days=7, failed_days=30):
    root = ensure_dirs(project_folder)
    now = _now()
    for state, days in (("completed", completed_days), ("failed", failed_days)):
        for path in (root / state).glob("*.json"):
            if now - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > timedelta(days=days):
                path.unlink(missing_ok=True)
    # Logs are metadata too. Keep diagnostics for active jobs regardless of
    # age, while bounding orphaned/completed job logs to the failed-job window.
    active_ids = {path.stem for state in ("pending", "running") for path in (root / state).glob("*.json")}
    for path in (root / "logs").glob("*.log"):
        if path.stem in active_ids:
            continue
        if now - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > timedelta(days=failed_days):
            path.unlink(missing_ok=True)
