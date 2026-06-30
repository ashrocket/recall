"""
Git sync provider.

Implements SyncProvider for GitHub, GitLab, and Bitbucket
using shell git commands.
"""

import subprocess
from pathlib import Path
from typing import List, Optional

from lib.sync import SyncProvider, register_provider
from lib.sync_config import SyncConfig


class GitProvider(SyncProvider):
    def __init__(self, local_dir: Path = None):
        if local_dir is None:
            local_dir = Path.home() / ".local" / "share" / "recall" / "sync"
        self.local_dir = local_dir

    def init(self, config: SyncConfig):
        """Clone the remote repo locally, or no-op if already initialised."""
        if (self.local_dir / ".git").exists():
            return
        self.local_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", config.repo, str(self.local_dir)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # Clone failed — repo likely empty (no commits).  Init locally and
            # wire up the remote so that the first push can succeed.
            subprocess.run(
                ["git", "init", str(self.local_dir)],
                capture_output=True, text=True, check=True, timeout=30,
            )
            subprocess.run(
                ["git", "remote", "add", "origin", config.repo],
                capture_output=True, text=True, check=True, timeout=30,
                cwd=str(self.local_dir),
            )

    def push(self, files: List[dict], config: SyncConfig) -> dict:
        pushed = 0
        errors = []

        for f in files:
            try:
                dest = self.local_dir / f["relative_path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f["content"])
                self._git_in_repo("add", f["relative_path"])
                pushed += 1
            except Exception as e:
                errors.append({"file": f["relative_path"], "error": str(e)})

        if pushed > 0:
            self._git_in_repo("commit", "-m", f"sync: push {pushed} files")
            self._push_to_remote(errors)

        return {"pushed": pushed, "errors": errors}

    def pull(self, since: Optional[str], config: SyncConfig) -> List[dict]:
        self._git_in_repo("pull", "--ff-only")

        files = []
        for yaml_file in self.local_dir.rglob("*.yaml"):
            relative = str(yaml_file.relative_to(self.local_dir))
            if relative.startswith("."):
                continue
            files.append({
                "path": relative,
                "content": yaml_file.read_bytes(),
            })
        return files

    def status(self, config: SyncConfig) -> dict:
        return {
            "provider": "git",
            "local_dir": str(self.local_dir),
            "initialized": (self.local_dir / ".git").exists(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _push_to_remote(self, errors: list):
        """Push the current branch, trying main then master, then current HEAD."""
        # Determine the actual branch name in the local clone.
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(self.local_dir),
        )
        current_branch = result.stdout.strip() if result.returncode == 0 else "main"

        # Try: push with upstream tracking set (handles empty remote).
        push_result = subprocess.run(
            ["git", "push", "-u", "origin", current_branch],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.local_dir),
        )
        if push_result.returncode == 0:
            return

        # Fallback: try the other common default branch name.
        fallback = "master" if current_branch == "main" else "main"
        push_result2 = subprocess.run(
            ["git", "push", "-u", "origin", f"HEAD:{fallback}"],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.local_dir),
        )
        if push_result2.returncode != 0:
            errors.append({"file": "push", "error": push_result2.stderr.strip()})

    def _git(self, *args):
        subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True, timeout=30,
        )

    def _git_in_repo(self, *args):
        subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True, timeout=30,
            cwd=str(self.local_dir),
        )


register_provider("github", GitProvider)
register_provider("gitlab", GitProvider)
register_provider("bitbucket", GitProvider)
