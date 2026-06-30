# Worktree Awareness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make recall resolve git worktrees to their parent repo so all sessions index under the canonical project, and maintain a global worktree registry.

**Architecture:** Add a git worktree resolution layer to `get_project_folder()` in `lib/shared.py`. Introduce `~/.claude/recall-worktrees.json` as a global registry mapping worktree paths to canonical projects. Add a session picker to `session-start.py` for unknown non-git directories. Add `--worktrees` cleanup flag.

**Tech Stack:** Python 3, `git worktree list --porcelain`, pathlib, JSON

---

### Task 1: Add worktree resolution to `lib/shared.py`

**Files:**
- Modify: `lib/shared.py:19-26` (replace `get_project_folder`)
- Create: `tests/test_worktree_resolution.py`

**Step 1: Write the failing test**

```python
# tests/test_worktree_resolution.py
"""Tests for worktree resolution in get_project_folder."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import resolve_worktree_root, get_project_folder


class TestResolveWorktreeRoot:
    """Test git worktree detection and resolution."""

    def test_regular_git_dir_returns_none(self, tmp_path):
        """A normal .git directory (not worktree) returns None."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        result = resolve_worktree_root(str(tmp_path))
        assert result is None

    def test_no_git_at_all_returns_none(self, tmp_path):
        """A directory with no .git returns None."""
        result = resolve_worktree_root(str(tmp_path))
        assert result is None

    def test_worktree_git_file_triggers_resolution(self, tmp_path):
        """A .git file (worktree indicator) triggers git worktree list."""
        # Create a .git file like worktrees have
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /Users/ash/repo/.git/worktrees/feat-x\n")

        # Mock subprocess to return porcelain output
        porcelain = (
            "worktree /Users/ash/repo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            f"worktree {tmp_path}\n"
            "HEAD def456\n"
            "branch refs/heads/feat-x\n"
            "\n"
        )
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=porcelain, stderr=""
            )
            result = resolve_worktree_root(str(tmp_path))
            assert result == "/Users/ash/repo"

    def test_git_not_installed_returns_none(self, tmp_path):
        """If git is not available, gracefully return None."""
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /some/path\n")

        with patch('subprocess.run', side_effect=FileNotFoundError):
            result = resolve_worktree_root(str(tmp_path))
            assert result is None


class TestGetProjectFolderWithWorktree:
    """Test that get_project_folder resolves worktrees to canonical path."""

    def test_worktree_resolves_to_main_repo(self, tmp_path):
        """When in a worktree, project folder should use the main repo path."""
        with patch('lib.shared.resolve_worktree_root', return_value="/Users/ash/repo"):
            with patch('lib.shared.update_worktree_registry'):
                result = get_project_folder(str(tmp_path))
                assert result == "-Users-ash-repo"

    def test_normal_repo_unchanged(self, tmp_path):
        """When in a normal repo, behavior is unchanged."""
        with patch('lib.shared.resolve_worktree_root', return_value=None):
            result = get_project_folder(str(tmp_path))
            assert result == str(tmp_path).replace('/', '-')
```

**Step 2: Run test to verify it fails**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_worktree_resolution.py -v`
Expected: FAIL — `resolve_worktree_root` doesn't exist yet

**Step 3: Write minimal implementation**

In `lib/shared.py`, add before `get_project_folder`:

```python
import subprocess

# ---------------------------------------------------------------------------
# Worktree registry
# ---------------------------------------------------------------------------

WORKTREE_REGISTRY_PATH = Path.home() / '.claude' / 'recall-worktrees.json'


def _load_worktree_registry() -> dict:
    """Load the global worktree registry."""
    if WORKTREE_REGISTRY_PATH.exists():
        try:
            with open(WORKTREE_REGISTRY_PATH, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"projects": {}}


def _save_worktree_registry(registry: dict):
    """Save the global worktree registry."""
    WORKTREE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WORKTREE_REGISTRY_PATH, 'w') as f:
        json.dump(registry, f, indent=2, default=str)


def resolve_worktree_root(cwd: str) -> Optional[str]:
    """If cwd is a git worktree, return the main worktree path. Else None.

    Detection: .git as a file (not directory) indicates a worktree.
    Resolution: parse `git worktree list --porcelain` for the main worktree.
    """
    git_path = Path(cwd) / '.git'

    # Fast path: no .git at all, or .git is a directory (normal repo)
    if not git_path.exists() or git_path.is_dir():
        return None

    # .git is a file — this is a worktree
    try:
        result = subprocess.run(
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        # Parse porcelain output — first "worktree <path>" is the main worktree
        for line in result.stdout.splitlines():
            if line.startswith('worktree '):
                return line[len('worktree '):]

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    return None


def update_worktree_registry(main_repo: str, worktree_path: str, branch: str = None):
    """Register a worktree mapping in the global registry."""
    from datetime import date as _date
    registry = _load_worktree_registry()
    today = str(_date.today())

    if main_repo not in registry['projects']:
        registry['projects'][main_repo] = {
            'project_folder': main_repo.replace('/', '-'),
            'worktrees': {},
        }

    wt_entry = registry['projects'][main_repo]['worktrees'].get(worktree_path, {})
    wt_entry['last_seen'] = today
    if not wt_entry.get('created'):
        wt_entry['created'] = today
    if branch:
        wt_entry['branch'] = branch

    registry['projects'][main_repo]['worktrees'][worktree_path] = wt_entry
    _save_worktree_registry(registry)
```

Then modify `get_project_folder` to use resolution:

```python
def get_project_folder(cwd: str = None) -> str:
    """Convert a working directory to Claude's project-folder naming convention.

    Resolution order:
    1. Explicit cwd argument
    2. CLAUDE_PROJECT_DIR env var
    3. os.getcwd()

    If the resolved path is a git worktree, maps to the main repo path.
    """
    if cwd is None:
        cwd = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()

    # Resolve worktree to canonical repo path
    main_repo = resolve_worktree_root(cwd)
    if main_repo:
        # Extract branch name from .git file for registry
        branch = None
        git_file = Path(cwd) / '.git'
        if git_file.is_file():
            content = git_file.read_text().strip()
            # gitdir: /path/.git/worktrees/<branch-name>
            parts = content.split('/worktrees/')
            if len(parts) == 2:
                branch = parts[1]

        update_worktree_registry(main_repo, cwd, branch)
        cwd = main_repo

    return cwd.replace('/', '-')
```

**Step 4: Run test to verify it passes**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_worktree_resolution.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add lib/shared.py tests/test_worktree_resolution.py
git commit -m "feat: add worktree resolution to get_project_folder

Detects git worktrees via .git file check, resolves to main repo
path via git worktree list --porcelain, and registers the mapping
in ~/.claude/recall-worktrees.json."
```

---

### Task 2: Add worktree registry I/O helpers

**Files:**
- Modify: `lib/shared.py` (add public API functions)
- Create: `tests/test_worktree_registry.py`

**Step 1: Write the failing test**

```python
# tests/test_worktree_registry.py
"""Tests for worktree registry I/O."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import (
    _load_worktree_registry,
    _save_worktree_registry,
    update_worktree_registry,
    lookup_worktree_project,
    list_project_worktrees,
    prune_stale_worktrees,
)


class TestWorktreeRegistry:

    def test_load_empty_registry(self, tmp_path):
        """Loading from nonexistent file returns empty structure."""
        with patch('lib.shared.WORKTREE_REGISTRY_PATH', tmp_path / 'missing.json'):
            reg = _load_worktree_registry()
            assert reg == {"projects": {}}

    def test_save_and_load_roundtrip(self, tmp_path):
        """Registry survives save/load roundtrip."""
        reg_path = tmp_path / 'worktrees.json'
        data = {"projects": {"/home/user/repo": {
            "project_folder": "-home-user-repo",
            "worktrees": {"/tmp/wt1": {"branch": "feat-x", "created": "2026-03-13", "last_seen": "2026-03-13"}}
        }}}
        with patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            _save_worktree_registry(data)
            loaded = _load_worktree_registry()
            assert loaded == data

    def test_lookup_worktree_project_found(self, tmp_path):
        """Lookup returns project folder for a known worktree path."""
        reg_path = tmp_path / 'worktrees.json'
        data = {"projects": {"/home/user/repo": {
            "project_folder": "-home-user-repo",
            "worktrees": {"/tmp/wt1": {"branch": "feat-x", "created": "2026-03-13", "last_seen": "2026-03-13"}}
        }}}
        with patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            _save_worktree_registry(data)
            result = lookup_worktree_project("/tmp/wt1")
            assert result == "-home-user-repo"

    def test_lookup_worktree_project_not_found(self, tmp_path):
        """Lookup returns None for unknown path."""
        reg_path = tmp_path / 'worktrees.json'
        with patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            result = lookup_worktree_project("/tmp/unknown")
            assert result is None

    def test_list_project_worktrees(self, tmp_path):
        """List returns all worktree paths for a project."""
        reg_path = tmp_path / 'worktrees.json'
        data = {"projects": {"/home/user/repo": {
            "project_folder": "-home-user-repo",
            "worktrees": {
                "/tmp/wt1": {"branch": "feat-x", "created": "2026-03-13", "last_seen": "2026-03-13"},
                "/tmp/wt2": {"branch": "fix-y", "created": "2026-03-13", "last_seen": "2026-03-13"},
            }
        }}}
        with patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            _save_worktree_registry(data)
            result = list_project_worktrees("/home/user/repo")
            assert set(result.keys()) == {"/tmp/wt1", "/tmp/wt2"}

    def test_prune_stale_worktrees(self, tmp_path):
        """Stale worktrees (>30 days) are pruned."""
        reg_path = tmp_path / 'worktrees.json'
        data = {"projects": {"/home/user/repo": {
            "project_folder": "-home-user-repo",
            "worktrees": {
                "/tmp/fresh": {"branch": "feat-x", "created": "2026-03-13", "last_seen": "2026-03-13"},
                "/tmp/stale": {"branch": "old", "created": "2026-01-01", "last_seen": "2026-01-01"},
            }
        }}}
        with patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            _save_worktree_registry(data)
            removed = prune_stale_worktrees(max_age_days=30)
            assert removed == 1
            reg = _load_worktree_registry()
            assert "/tmp/stale" not in reg['projects']['/home/user/repo']['worktrees']
            assert "/tmp/fresh" in reg['projects']['/home/user/repo']['worktrees']
```

**Step 2: Run test to verify it fails**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_worktree_registry.py -v`
Expected: FAIL — `lookup_worktree_project`, `list_project_worktrees`, `prune_stale_worktrees` don't exist

**Step 3: Write minimal implementation**

Add to `lib/shared.py` after the existing registry functions:

```python
def lookup_worktree_project(worktree_path: str) -> Optional[str]:
    """Look up a worktree path in the registry. Returns project_folder or None."""
    registry = _load_worktree_registry()
    for repo_path, project_data in registry.get('projects', {}).items():
        if worktree_path in project_data.get('worktrees', {}):
            return project_data['project_folder']
    return None


def list_project_worktrees(repo_path: str) -> dict:
    """Return all worktree entries for a given repo path."""
    registry = _load_worktree_registry()
    project_data = registry.get('projects', {}).get(repo_path, {})
    return project_data.get('worktrees', {})


def prune_stale_worktrees(max_age_days: int = 30) -> int:
    """Remove worktree entries older than max_age_days. Returns count removed."""
    from datetime import date as _date, timedelta
    registry = _load_worktree_registry()
    cutoff = str(_date.today() - timedelta(days=max_age_days))
    removed = 0

    for repo_path in list(registry.get('projects', {})):
        project = registry['projects'][repo_path]
        worktrees = project.get('worktrees', {})
        stale = [p for p, wt in worktrees.items() if wt.get('last_seen', '') < cutoff]
        for p in stale:
            del worktrees[p]
            removed += 1
        # Remove project entry if no worktrees left
        if not worktrees:
            del registry['projects'][repo_path]

    if removed > 0:
        _save_worktree_registry(registry)
    return removed
```

**Step 4: Run test to verify it passes**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_worktree_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add lib/shared.py tests/test_worktree_registry.py
git commit -m "feat: add worktree registry lookup, list, and prune helpers"
```

---

### Task 3: Add session picker to `session-start.py`

**Files:**
- Modify: `hooks/scripts/session-start.py:38-49` (add picker logic after no-index check)
- Create: `tests/test_session_picker.py`

**Step 1: Write the failing test**

```python
# tests/test_session_picker.py
"""Tests for the session picker in session-start."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hooks', 'scripts'))


class TestBuildSessionPicker:
    """Test the picker that shows today's sessions from all projects."""

    def test_finds_todays_sessions(self, tmp_path):
        """Picker finds sessions from today across projects."""
        from session_start_helpers import collect_todays_sessions

        today = datetime.now().strftime('%Y-%m-%d')
        # Create two fake project indices
        proj_a = tmp_path / '-Users-ash-repo-a'
        proj_a.mkdir()
        (proj_a / 'recall-index.json').write_text(json.dumps({
            'sessions': {
                'sess1': {'date': f'{today}T10:00:00', 'summary': 'working on auth', 'message_count': 5}
            }
        }))

        proj_b = tmp_path / '-Users-ash-repo-b'
        proj_b.mkdir()
        (proj_b / 'recall-index.json').write_text(json.dumps({
            'sessions': {
                'sess2': {'date': '2026-01-01T10:00:00', 'summary': 'old session', 'message_count': 3}
            }
        }))

        results = collect_todays_sessions(projects_dir=tmp_path)
        assert len(results) == 1
        assert results[0]['project_folder'] == '-Users-ash-repo-a'

    def test_formats_picker_output(self, tmp_path):
        """Picker output is compact 1-liners."""
        from session_start_helpers import format_session_picker

        sessions = [
            {'project_folder': '-Users-ash-repo-a', 'session_count': 3, 'summary': 'worktree awareness design'},
            {'project_folder': '-Users-ash-repo-b', 'session_count': 1, 'summary': 'CLI packaging'},
        ]
        output = format_session_picker(sessions)
        assert 'repo-a' in output
        assert '[3 sessions]' in output
        assert 'repo-b' in output

    def test_empty_when_no_sessions_today(self, tmp_path):
        """Returns empty list when no sessions are from today."""
        from session_start_helpers import collect_todays_sessions
        results = collect_todays_sessions(projects_dir=tmp_path)
        assert results == []
```

**Step 2: Run test to verify it fails**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_session_picker.py -v`
Expected: FAIL — `session_start_helpers` module doesn't exist

**Step 3: Write minimal implementation**

Create `lib/session_start_helpers.py`:

```python
"""Helpers for SessionStart hook — session picker for unknown directories."""
import json
from datetime import datetime
from pathlib import Path


def collect_todays_sessions(projects_dir: Path = None) -> list:
    """Scan all project indices and collect projects with sessions from today.

    Returns list of dicts: {project_folder, session_count, summary, worktrees}
    sorted by session count descending.
    """
    if projects_dir is None:
        projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return []

    today = datetime.now().strftime('%Y-%m-%d')
    results = []

    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        index_file = proj_dir / 'recall-index.json'
        if not index_file.exists():
            continue

        try:
            with open(index_file, 'r') as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        sessions = index.get('sessions', {})
        today_sessions = [
            s for s in sessions.values()
            if s.get('date', '')[:10] == today
        ]

        if today_sessions:
            # Use most recent session's summary
            latest = max(today_sessions, key=lambda s: s.get('date', ''))
            results.append({
                'project_folder': proj_dir.name,
                'session_count': len(today_sessions),
                'summary': latest.get('summary', 'No summary')[:80],
            })

    return sorted(results, key=lambda x: -x['session_count'])


def format_session_picker(sessions: list) -> str:
    """Format session list as compact picker output."""
    if not sessions:
        return ""

    lines = ["No session history for this directory.", "",
             "Today's sessions:"]

    for i, s in enumerate(sessions, 1):
        # Extract short project name from folder (last component)
        name = s['project_folder'].rsplit('-', 1)[-1] if '-' in s['project_folder'] else s['project_folder']
        # Try to get a better name: last two path components
        parts = s['project_folder'].strip('-').split('-')
        if len(parts) >= 2:
            name = parts[-1]

        count = s['session_count']
        summary = s['summary'][:60]
        lines.append(f"  {i}. {name} [{count} session{'s' if count != 1 else ''}] — {summary}")

    lines.append("")
    lines.append("Resume context from which project? (number, or Enter to skip)")
    return '\n'.join(lines)
```

Then modify `hooks/scripts/session-start.py` to use it. Replace lines 47-49 (`if not index...` block):

```python
    if not index or not index.get('sessions'):
        # No history — check if this is a non-git dir and show picker
        git_path = Path(cwd) / '.git'
        if not git_path.exists():
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
                from session_start_helpers import collect_todays_sessions, format_session_picker
                today_sessions = collect_todays_sessions()
                if today_sessions:
                    print(format_session_picker(today_sessions))
            except Exception:
                pass
        sys.exit(0)
```

**Step 4: Run test to verify it passes**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_session_picker.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add lib/session_start_helpers.py hooks/scripts/session-start.py tests/test_session_picker.py
git commit -m "feat: add session picker for unknown non-git directories

When SessionStart fires in a directory with no history and no .git,
shows today's sessions across all projects as a numbered picker."
```

---

### Task 4: Add `--worktrees` cleanup flag

**Files:**
- Modify: `bin/recall-sessions.py` (add `--worktrees` to cleanup dispatch)
- Create: `tests/test_worktree_cleanup.py`

**Step 1: Write the failing test**

```python
# tests/test_worktree_cleanup.py
"""Tests for worktree cleanup via /recall cleanup --worktrees."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import prune_stale_worktrees


class TestWorktreeCleanup:

    def test_prune_removes_old_entries(self, tmp_path):
        """Pruning removes entries with last_seen older than threshold."""
        import json
        reg_path = tmp_path / 'worktrees.json'
        data = {"projects": {"/home/user/repo": {
            "project_folder": "-home-user-repo",
            "worktrees": {
                "/tmp/recent": {"branch": "a", "created": "2026-03-13", "last_seen": "2026-03-13"},
                "/tmp/old": {"branch": "b", "created": "2025-01-01", "last_seen": "2025-01-01"},
            }
        }}}
        with open(reg_path, 'w') as f:
            json.dump(data, f)

        with patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            removed = prune_stale_worktrees(max_age_days=30)
            assert removed == 1
```

**Step 2: Run test to verify it fails (or passes if Task 2 is done)**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_worktree_cleanup.py -v`
Expected: PASS (prune_stale_worktrees already implemented in Task 2)

**Step 3: Wire into recall-sessions.py cleanup command**

Find the cleanup dispatch section in `bin/recall-sessions.py` and add `--worktrees` handling. The cleanup function should call `prune_stale_worktrees()` and print results:

```python
# In the cleanup flags dispatch section:
if '--worktrees' in flags or '--all' in flags:
    from lib.shared import prune_stale_worktrees
    removed = prune_stale_worktrees()
    if removed:
        print(f"  Pruned {removed} stale worktree entries")
    else:
        print("  No stale worktree entries found")
```

**Step 4: Test manually**

Run: `cd ~/ashcode/recall-skill && python3 bin/recall-sessions.py "$PWD" cleanup --worktrees`
Expected: "No stale worktree entries found" (or pruned count)

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add bin/recall-sessions.py tests/test_worktree_cleanup.py
git commit -m "feat: add --worktrees flag to /recall cleanup

Prunes stale worktree registry entries (>30 days since last seen)."
```

---

### Task 5: Update `/recall` command docs

**Files:**
- Modify: `commands/recall.md` (add worktree info to docs)

**Step 1: Add worktree documentation**

Add to the usage section of `commands/recall.md`:

```markdown
- `/recall cleanup --worktrees` - Prune stale worktree registry entries (>30 days)
```

Add a new section:

```markdown
## Worktree Awareness

Recall automatically detects git worktrees and maps them to the parent repository.
Sessions in worktrees are indexed under the canonical project, not the temporary path.

A global registry at `~/.claude/recall-worktrees.json` tracks which worktrees
belong to which projects.

If you start a session in an unknown non-git directory, recall shows today's
sessions as a picker so you can resume the right project context.
```

**Step 2: Commit**

```bash
cd ~/ashcode/recall-skill
git add commands/recall.md
git commit -m "docs: add worktree awareness documentation to /recall"
```

---

### Task 6: Integration test — end-to-end worktree flow

**Files:**
- Create: `tests/test_integration_worktree.py`

**Step 1: Write the integration test**

```python
# tests/test_integration_worktree.py
"""Integration test: full worktree detection → registration → project resolution."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestWorktreeIntegration:

    def test_full_flow_worktree_to_canonical_project(self, tmp_path):
        """End-to-end: worktree detected → registry updated → correct project folder returned."""
        from lib.shared import get_project_folder, _load_worktree_registry, WORKTREE_REGISTRY_PATH

        # Set up: fake worktree directory
        wt_dir = tmp_path / 'worktree-feat-x'
        wt_dir.mkdir()
        (wt_dir / '.git').write_text('gitdir: /Users/ash/myrepo/.git/worktrees/feat-x\n')

        # Mock git worktree list output
        porcelain = (
            "worktree /Users/ash/myrepo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            f"worktree {wt_dir}\n"
            "HEAD def456\n"
            "branch refs/heads/feat-x\n"
            "\n"
        )
        reg_path = tmp_path / 'registry.json'

        with patch('subprocess.run') as mock_run, \
             patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            mock_run.return_value = MagicMock(returncode=0, stdout=porcelain, stderr="")

            # Call get_project_folder from the worktree path
            result = get_project_folder(str(wt_dir))

            # Should resolve to main repo's project folder
            assert result == '-Users-ash-myrepo'

            # Registry should be updated
            reg = json.loads(reg_path.read_text())
            assert '/Users/ash/myrepo' in reg['projects']
            assert str(wt_dir) in reg['projects']['/Users/ash/myrepo']['worktrees']
            assert reg['projects']['/Users/ash/myrepo']['worktrees'][str(wt_dir)]['branch'] == 'feat-x'

    def test_second_call_uses_same_project(self, tmp_path):
        """Calling get_project_folder twice from same worktree returns same result."""
        from lib.shared import get_project_folder

        wt_dir = tmp_path / 'worktree-feat-x'
        wt_dir.mkdir()
        (wt_dir / '.git').write_text('gitdir: /Users/ash/myrepo/.git/worktrees/feat-x\n')

        porcelain = "worktree /Users/ash/myrepo\nHEAD abc\nbranch refs/heads/main\n\n"
        reg_path = tmp_path / 'registry.json'

        with patch('subprocess.run') as mock_run, \
             patch('lib.shared.WORKTREE_REGISTRY_PATH', reg_path):
            mock_run.return_value = MagicMock(returncode=0, stdout=porcelain, stderr="")

            result1 = get_project_folder(str(wt_dir))
            result2 = get_project_folder(str(wt_dir))
            assert result1 == result2 == '-Users-ash-myrepo'
```

**Step 2: Run all tests**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
cd ~/ashcode/recall-skill
git add tests/test_integration_worktree.py
git commit -m "test: add end-to-end integration test for worktree flow"
```
