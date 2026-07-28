import json
import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _home(monkeypatch, path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))


def _codex_source(home, name="a"):
    path = home / ".codex" / "sessions" / "2026" / "07" / "28" / f"rollout-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": name, "cwd": "/tmp/project", "timestamp": "2026-07-28T12:00:00Z"}}),
        json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Build durable queue"}]}}),
    ]))
    return path


def _worker():
    worker_path = Path(__file__).resolve().parent.parent / "bin" / "recall-jobs.py"
    spec = importlib.util.spec_from_file_location("recall_jobs", worker_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enqueue_is_metadata_only_and_idempotent(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import enqueue, ensure_dirs, read_job
    source = _codex_source(tmp_path, "b")
    job = enqueue("codex", str(source), "/tmp/project", "-tmp-project")
    assert job and job["source_path"] == str(source.resolve())
    assert enqueue("codex", str(source), "/tmp/project", "-tmp-project") is None
    pending = ensure_dirs("-tmp-project") / "pending" / f"{job['id']}.json"
    assert pending.stat().st_mode & 0o777 == 0o600
    assert "Build durable queue" not in pending.read_text()
    assert read_job(pending)["id"] == job["id"]


def test_drain_commits_once_after_retryable_crash_boundary(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import enqueue, ensure_dirs, queue_status
    recall_jobs = _worker()
    monkeypatch.setattr(recall_jobs, "post_commit", lambda *_args: None)
    source = _codex_source(tmp_path, "b")
    job = enqueue("codex", str(source), "/tmp/project", "-tmp-project")
    assert recall_jobs.drain("/tmp/project", max_jobs=1, time_budget=5) == 1
    status = queue_status("-tmp-project")
    assert [entry["id"] for entry in status["completed"]] == [job["id"]]
    index = json.loads((tmp_path / ".claude" / "projects" / "-tmp-project" / "recall-index.json").read_text())
    assert job["id"] in index["job_receipts"]
    # Replaying the same completed job cannot increment the index.
    assert len(index["sessions"]) == 1


def test_only_one_concurrent_claimer_can_own_a_job(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import claim, enqueue, ensure_dirs
    job = enqueue("codex", str(_codex_source(tmp_path)), "/tmp/project", "-tmp-project")
    pending = ensure_dirs("-tmp-project") / "pending" / f"{job['id']}.json"
    assert claim(pending)
    assert claim(pending) is None
    assert not pending.exists()
    assert (ensure_dirs("-tmp-project") / "running" / f"{job['id']}.json").exists()


def test_overlapping_sessions_index_their_own_exact_sources(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import enqueue, queue_status
    worker = _worker()
    monkeypatch.setattr(worker, "post_commit", lambda *_args: None)
    first = _codex_source(tmp_path, "first")
    second = _codex_source(tmp_path, "second")
    first_job = enqueue("codex", str(first), "/tmp/project", "-tmp-project")
    second_job = enqueue("codex", str(second), "/tmp/project", "-tmp-project")
    monkeypatch.setattr(worker, "_stable_source", lambda job: (Path(job["source_path"]), True))
    assert worker.drain("/tmp/project", max_jobs=2, time_budget=5) == 2
    completed = {job["id"] for job in queue_status("-tmp-project")["completed"]}
    assert completed == {first_job["id"], second_job["id"]}
    index = json.loads((tmp_path / ".claude" / "projects" / "-tmp-project" / "recall-index.json").read_text())
    assert set(index["sessions"]) == {"codex-first", "codex-second"}


def test_stale_running_job_is_recovered_without_overwriting_pending(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import claim, enqueue, ensure_dirs, recover_stale
    job = enqueue("codex", str(_codex_source(tmp_path)), "/tmp/project", "-tmp-project")
    root = ensure_dirs("-tmp-project")
    running = claim(root / "pending" / f"{job['id']}.json")
    old = time.time() - 6 * 60
    os.utime(running, (old, old))
    assert recover_stale("-tmp-project") == 1
    assert (root / "pending" / running.name).exists()
    assert not running.exists()


def test_missing_source_is_terminal_and_transient_failure_backs_off(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import enqueue, ensure_dirs, read_job
    worker = _worker()
    source = _codex_source(tmp_path, "b")
    missing = enqueue("codex", str(source), "/tmp/project", "-tmp-project")
    source.unlink()
    assert worker.drain("/tmp/project", max_jobs=1, time_budget=5) == 1
    root = ensure_dirs("-tmp-project")
    assert (root / "failed" / f"{missing['id']}.json").exists()

    source = _codex_source(tmp_path)
    transient = enqueue("codex", str(source), "/tmp/project", "-tmp-project")
    monkeypatch.setattr(worker, "_stable_source", lambda _job: (source, True))
    monkeypatch.setattr(worker, "apply_indexed_session", lambda *_args: (_ for _ in ()).throw(RuntimeError("temporary")))
    assert worker.drain("/tmp/project", max_jobs=1, time_budget=5) == 1
    retried = read_job(root / "pending" / f"{transient['id']}.json")
    assert retried["attempts"] == 1
    assert retried["last_error"] == "temporary"


def test_macos_daemon_uses_only_stable_source_path(tmp_path, monkeypatch):
    worker = _worker()
    stable = tmp_path / ".recall"
    (stable / "bin").mkdir(parents=True)
    (stable / "bin" / "recall").write_text("#!/bin/sh\n")
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(worker, "ROOT", stable)
    monkeypatch.setattr(worker.sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(worker.subprocess, "run", lambda args, **kwargs: calls.append(args) or type("Result", (), {"returncode": 0, "stderr": ""})())
    worker.install_daemon()
    plist = tmp_path / "Library" / "LaunchAgents" / "com.ashrocket.recall-indexer.plist"
    assert plist.exists()
    assert f"{stable}/bin/recall" in plist.read_text()
    assert calls[-1][:2] == ["launchctl", "bootstrap"]


def test_retention_keeps_active_jobs_and_prunes_old_receipts_and_logs(tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    from lib.session_jobs import cleanup, enqueue, ensure_dirs
    job = enqueue("codex", str(_codex_source(tmp_path)), "/tmp/project", "-tmp-project")
    root = ensure_dirs("-tmp-project")
    completed = root / "completed" / "old.json"
    completed.write_text("{}")
    old_log = root / "logs" / "old.log"
    old_log.write_text("old")
    active_log = root / "logs" / f"{job['id']}.log"
    active_log.write_text("active")
    old = time.time() - 31 * 24 * 60 * 60
    for path in (completed, old_log, active_log):
        os.utime(path, (old, old))
    cleanup("-tmp-project")
    assert not completed.exists()
    assert not old_log.exists()
    assert active_log.exists()
    assert (root / "pending" / f"{job['id']}.json").exists()
