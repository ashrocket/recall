"""
Sync hook integration.
Called from session-start and session-end hooks to auto-push/pull.
Fails silently — never blocks the user's session.
"""

import sys
from pathlib import Path
from typing import Optional

from lib.sync_config import load_sync_config, SyncConfig
from lib.sync import gather_sync_files, get_provider, is_safe_pull_relative_path


def maybe_sync_push(data_dir: Path = None) -> Optional[dict]:
    config = load_sync_config()
    if config is None:
        return None
    if config.mode == "manual":
        return None
    if not config.auto_sync:
        return None

    try:
        provider_cls = get_provider(config.provider)
        provider = provider_cls()
        files = gather_sync_files(data_dir or Path.home() / ".claude", config)

        if not files:
            return {"pushed": 0, "errors": []}

        if config.secret_scan == "strict":
            clean_files = [f for f in files if not f["secret_findings"]]
            if len(clean_files) < len(files):
                print(f"  sync: {len(files) - len(clean_files)} files blocked by secret scan", file=sys.stderr)
            files = clean_files

        result = provider.push(files, config)
        if result["pushed"] > 0:
            print(f"  sync: pushed {result['pushed']} files to {config.provider}")
        if result["errors"]:
            print(f"  sync: {len(result['errors'])} errors", file=sys.stderr)
        return result

    except Exception as e:
        print(f"  sync: push failed ({e})", file=sys.stderr)
        return {"pushed": 0, "errors": [str(e)]}


def maybe_sync_pull(data_dir: Path = None) -> Optional[dict]:
    config = load_sync_config()
    if config is None:
        return None
    if config.mode == "manual":
        return None

    try:
        provider_cls = get_provider(config.provider)
        provider = provider_cls()

        ts_file = (data_dir or Path.home() / ".claude") / ".last_sync_pull"
        since = ts_file.read_text().strip() if ts_file.exists() else None

        pulled = provider.pull(since=since, config=config)

        base_dir = (data_dir or Path.home() / ".claude").resolve()
        written = 0
        blocked = 0
        for f in pulled:
            path = f["path"]
            if not is_safe_pull_relative_path(path):
                blocked += 1
                print(f"  sync: blocked unsafe pull path {path!r}", file=sys.stderr)
                continue

            dest = (base_dir / path).resolve()
            if dest != base_dir and base_dir not in dest.parents:
                blocked += 1
                print(f"  sync: blocked pull path outside sync dir {path!r}", file=sys.stderr)
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(f["content"], bytes):
                dest.write_bytes(f["content"])
            else:
                dest.write_text(f["content"])
            written += 1

        from datetime import datetime, timezone
        ts_file.parent.mkdir(parents=True, exist_ok=True)
        ts_file.write_text(datetime.now(timezone.utc).isoformat())

        if written:
            print(f"  sync: pulled {written} files from {config.provider}")
        result = {"pulled": written}
        if blocked:
            result["blocked"] = blocked
        return result

    except Exception as e:
        print(f"  sync: pull failed ({e})", file=sys.stderr)
        return {"pulled": 0, "error": str(e)}
