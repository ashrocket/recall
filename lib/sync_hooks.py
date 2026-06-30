"""
Sync hook integration.
Called from session-start and session-end hooks to auto-push/pull.
Fails silently — never blocks the user's session.
"""

import sys
from pathlib import Path
from typing import Optional

from lib.sync_config import load_sync_config, SyncConfig
from lib.sync import gather_sync_files, get_provider


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

        for f in pulled:
            dest = (data_dir or Path.home() / ".claude") / f["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(f["content"], bytes):
                dest.write_bytes(f["content"])
            else:
                dest.write_text(f["content"])

        from datetime import datetime, timezone
        ts_file.parent.mkdir(parents=True, exist_ok=True)
        ts_file.write_text(datetime.now(timezone.utc).isoformat())

        if pulled:
            print(f"  sync: pulled {len(pulled)} files from {config.provider}")
        return {"pulled": len(pulled)}

    except Exception as e:
        print(f"  sync: pull failed ({e})", file=sys.stderr)
        return {"pulled": 0, "error": str(e)}
