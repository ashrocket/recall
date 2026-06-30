# Worktree Awareness Design

**Date:** 2026-03-13
**Status:** Approved

## Problem

Recall's project identity is purely path-based (`cwd.replace('/', '-')`). Git worktrees create temporary paths (e.g., `/tmp/worktree-abc/`) that recall treats as entirely separate projects, losing all session history, failure patterns, and restart data from the canonical repo.

## Solution: Worktree Registry + Git Auto-Detection (Approach A)

### 1. Worktree Registry

**File:** `~/.claude/recall-worktrees.json` (global)

```json
{
  "projects": {
    "/Users/exampleuser/ashcode/recall-skill": {
      "project_folder": "-Users-exampleuser-ashcode-recall-skill",
      "worktrees": {
        "/tmp/worktree-abc": {
          "branch": "feat/worktree-awareness",
          "created": "2026-03-13",
          "last_seen": "2026-03-13"
        }
      }
    }
  }
}
```

- Written whenever `get_project_folder()` resolves a worktree
- Read as fast cache before falling back to `git worktree list`
- `last_seen` updates each session; stale entries (>30 days) pruned by cleanup

### 2. Resolution Logic in `get_project_folder()`

```
cwd → is .git a file (not directory)?
  YES (worktree) → git worktree list --porcelain → find main worktree
                  → register in recall-worktrees.json
                  → return main repo's project_folder
  NO  → is .git a directory?
         YES (normal repo) → use cwd as-is (current behavior)
         NO (not a git repo) → check registry cache for this path
                HIT  → return cached project_folder
                MISS → return cwd-based project_folder (new project)
```

**Performance:** `.git` file-vs-directory check is a single `stat()`. No subprocess unless it IS a worktree. Zero overhead for normal repos.

### 3. Session Picker for Unknown Directories

When recall starts in a directory with no session history AND no git repo:

```
No session history for this directory.

Today's sessions:
  1. recall-skill [3 sessions] - worktree awareness design
  2. demoapp [1 session] - CLI packaging
  3. claude-pigeon [2 sessions] - provider debugging

Resume context from which project? (number, or Enter to skip)
```

- Shown in `session-start.py`
- Scans all `recall-index.json` files, filters to today
- If user picks one, loads that context and registers directory in registry
- NOT shown if in a git repo (even with no history) — creates new project instead

### 4. Impact on Existing Commands

| Command | Change |
|---------|--------|
| `/recall` (search) | Searches canonical project, includes worktree sessions |
| `/recall restart list` | Shows restarts from canonical project |
| `/recall save` | Saves under canonical project folder |
| `/recall failures` | Aggregates across all worktrees for the project |
| `/recall cleanup` | Gains `--worktrees` flag to prune stale entries |
| SessionStart hook | Resolves worktree, loads correct context |
| SessionEnd hook | Indexes under canonical project folder |

No data migration needed. Existing sessions stay in place. New worktree sessions index correctly going forward.

### 5. Edge Cases

1. **Worktree deleted, registry entry exists** — `last_seen` goes stale, cleaned by `--worktrees` or `--all`
2. **Same repo cloned twice (not worktree)** — separate projects (correct: different git histories possible)
3. **Nested worktrees** — `git worktree list` always returns main worktree, resolves correctly
4. **No git installed** — graceful fallback, behaves like current code
