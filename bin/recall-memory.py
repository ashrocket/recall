#!/usr/bin/env python3
"""
Bridge recall's distilled knowledge into Claude Code's native memory directory.

Usage:
  recall-memory.py                  - Show bridge status
  recall-memory.py status           - Show bridge status
  recall-memory.py sync             - Promote approved learnings and SOPs
  recall-memory.py sync --dry-run   - Show what sync would change
  recall-memory.py clear            - Remove everything recall promoted
  recall-memory.py store-env        - Print the CLAUDE_MEMORY_STORES declaration
"""

import os
import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))
sys.path.insert(0, str(LIB_DIR.parent))

from lib import native_memory
from lib.native_memory import INDEX_NAME
from lib.platform import recall_command
from knowledge import get_learnings, get_project_folder
from sops import load_sops


def _collect(project_folder: str):
    """Return the (learnings, sops) recall would promote."""
    learnings = [l for l in get_learnings(project_folder) if isinstance(l, dict)]
    try:
        sops = native_memory.normalize_sops(load_sops())
    except Exception:
        sops = {}
    return learnings, sops


def _print_skipped(skipped):
    """Explain everything that did not get promoted, and why."""
    if not skipped:
        return
    print()
    print("**Not promoted:**")
    for item in skipped:
        reason = item.get("reason")
        if reason == "secret_scan":
            hits = ", ".join(sorted({f["type"] for f in item["findings"]}))
            print(f"  ! {item['name']} — possible secret ({hits})")
        elif reason == "not_recall_owned":
            print(f"  ! {item['name']} — a non-recall file already owns that name")
        elif item.get("detail"):
            marker = "!" if reason in ("hand_edited", "foreign_origin") else "·"
            print(f"  {marker} {item['name']} — {item['detail']}")
        else:
            print(f"  · {item['name']} — {reason}")
    if any(i.get("reason") == "not_durable" for i in skipped):
        print()
        print(f"  Held-back learnings stay in `{recall_command('failures')}`; only durable")
        print(f"  guidance is promoted, because {INDEX_NAME} is loaded into every session.")


def _warn_if_suppressed():
    if not native_memory.index_injection_suppressed():
        return
    print()
    print("!! CLAUDE_MEMORY_STORES is set in this environment.")
    print(f"   Claude Code stops inlining {INDEX_NAME} whenever that variable is")
    print("   present, so promoted memories will sit on disk unread. Unset it to")
    print("   restore automatic loading.")


def cmd_status(project_folder: str, cwd: str = None):
    info = native_memory.status(cwd=cwd)
    learnings, sops = _collect(project_folder)

    from knowledge import load_index
    auto = native_memory.auto_promote_enabled(load_index(project_folder))

    print("## Native Memory Bridge")
    print()
    print("Promotes approved learnings and SOPs into Claude Code's memory directory")
    print(f"for this project, where they are loaded at the start of every session. "
          f"`{recall_command('memory', 'clear')}` undoes it.")
    print()
    print(f"**Status:** {'enabled' if info['enabled'] else 'disabled'} "
          f"(platform: {info['platform']})")
    print(f"**Auto-promote on approval:** {'on' if auto else 'off'}"
          + ("" if auto else f"  —  `{recall_command('memory', 'enable')}` to turn on"))
    print(f"**Memory dir:** `{info['memory_dir']}`"
          + ("" if info["memory_dir_exists"] else "  _(not created yet)_"))
    print(f"**Index:** {INDEX_NAME} "
          + ("present" if info["index_exists"] else "not created yet"))
    print()
    print(f"**Promoted files:** {len(info['promoted_files'])}")
    print(f"**Promoted index pointers:** {info['promoted_pointers']}")
    if info["other_files"]:
        print(f"**Other memory files (untouched by recall):** {info['other_files']}")
    print()
    print(f"**Available to promote:** {len(learnings)} approved learnings, {len(sops)} SOPs")

    if info["promoted_files"]:
        print()
        for name in info["promoted_files"]:
            print(f"  - {name}")

    _warn_if_suppressed()

    print()
    print("---")
    print("**Actions:**")
    print(f"  `{recall_command('memory', 'sync')}` - Promote approved learnings and SOPs")
    print(f"  `{recall_command('memory', 'clear')}` - Remove everything recall promoted")


def _sync_codex(learnings, sops, cwd):
    """Write the fenced block into the project's AGENTS.md."""
    from lib import memory_targets

    root = cwd or os.getcwd()
    result = memory_targets.sync_region(learnings, sops, project_root=root)

    print("## Codex Memory Sync")
    print()
    print(f"**File:** `{result.path}`")
    print(f"**Entries in the recall block:** {result.doc_count}"
          f"  ({result.bytes_used} bytes)")
    if result.written:
        print("**Block:** rewritten — everything outside it left untouched")
    elif result.removed:
        print("**Block:** removed")
    elif not result.skipped:
        print("Already up to date.")
    _print_skipped(result.skipped)
    return 0


def cmd_sync(project_folder: str, dry_run: bool = False, cwd: str = None,
             target: str = "claude"):
    if target == "claude" and not native_memory.is_enabled():
        print("Native memory bridge is off: this platform, RECALL_NATIVE_MEMORY=0, "
              "CLAUDE_CODE_DISABLE_AUTO_MEMORY, or autoMemoryEnabled:false in your "
              "Claude Code settings. `/memory` in Claude Code toggles the last one.")
        return 1

    learnings, sops = _collect(project_folder)

    if dry_run:
        if target == "codex":
            from lib import memory_targets
            docs = native_memory.build_docs(learnings, sops)
            region, truncated = memory_targets.render_region(docs)
            print("## Codex Memory Sync (dry run)")
            print()
            print(f"Would write a {len(region)}-byte block with "
                  f"{len(docs) - truncated} entr(ies) to "
                  f"`{memory_targets.agents_md_path(cwd or os.getcwd())}`.")
            return 0

        # Same code path as the real thing, so a dry run cannot predict an
        # outcome sync would not produce.
        docs, skipped, memdir = native_memory.plan(learnings, sops, cwd=cwd)
        print("## Native Memory Sync (dry run)")
        print()
        print(f"Would write {len(docs)} file(s) to `{memdir}`:")
        print()
        for doc in docs:
            print(f"  - {doc.filename}  [{doc.type}]")
        _print_skipped(skipped)
        _warn_if_suppressed()
        return 0

    if target == "codex":
        return _sync_codex(learnings, sops, cwd)

    result = native_memory.sync(learnings, sops, cwd=cwd)

    print("## Native Memory Sync")
    print()
    print(f"**Directory:** `{result.memory_dir}`")
    print(f"**Written:** {len(result.written)}  "
          f"**Unchanged:** {len(result.unchanged)}  "
          f"**Removed:** {len(result.removed)}")
    if result.index_updated:
        print(f"**{INDEX_NAME}:** pointers refreshed")

    for name in result.written:
        print(f"  + {name}")
    for name in result.removed:
        print(f"  - {name}")

    _print_skipped(result.skipped)

    if not result.changed:
        print()
        print("Already up to date.")

    _warn_if_suppressed()

    if result.written or result.unchanged:
        print()
        print("These load automatically at the start of every session in this project.")
    return 0


def cmd_set_auto(project_folder: str, on: bool):
    """Turn automatic promotion on approval on or off for this project."""
    from knowledge import load_index
    from lib.shared import save_index

    index = load_index(project_folder)
    index.setdefault("settings", {})[native_memory.AUTO_PROMOTE_SETTING] = on
    save_index(index, project_folder)

    if on:
        print("## Native memory auto-promotion enabled")
        print()
        print(f"Approving a learning with `{recall_command('learn')}` will now also write it")
        print("to this project's native memory directory. recall still refuses to create")
        print("that directory — if it does not exist, run "
              f"`{recall_command('memory', 'sync')}` once.")
    else:
        print("## Native memory auto-promotion disabled")
        print()
        print(f"`{recall_command('memory', 'sync')}` still works on demand. Already-promoted")
        print(f"files stay where they are — use `{recall_command('memory', 'clear')}` to remove them.")
    return 0


def cmd_clear(cwd: str = None):
    result = native_memory.clear(cwd=cwd)
    print("## Native Memory Cleared")
    print()
    print(f"**Directory:** `{result.memory_dir}`")
    print(f"**Removed:** {len(result.removed)} file(s)")
    for name in result.removed:
        print(f"  - {name}")
    if result.index_updated:
        print(f"**{INDEX_NAME}:** recall pointers removed (other entries untouched)")
    if not result.changed:
        print("Nothing to remove.")
    return 0


def cmd_store_env():
    print("## CLAUDE_MEMORY_STORES — do not set this on a local session")
    print()
    print("Measured against Claude Code 2.1.229, by capturing the request Claude Code")
    print("actually sends:")
    print()
    print(f"  - Any non-empty value stops {INDEX_NAME} being loaded into your session.")
    print("    Even a garbage value does it — the check is only whether the variable")
    print("    is set. That is the mechanism this bridge relies on.")
    print("  - The replacement (loading the store's own promptIndex) did not fire in")
    print("    a local session under API-key auth; the declared mount materialised as")
    print("    an empty directory. Managed/org sessions may differ.")
    print("  - You cannot point it at your own server: CLAUDE_CODE_MEMORY_API_BASE_URL")
    print("    is never read in 2.1.229 — its only occurrences are in an env-var")
    print("    allowlist. Store paths are API routes, not filesystem paths.")
    print()
    print("The declaration recall would use, recorded for when org memory stores")
    print("become reachable from local sessions:")
    print()
    print(f"    {native_memory.store_env_declaration()}")
    return 0


def main():
    args = [a for a in sys.argv[1:] if a]

    # The dispatcher passes the project path through as the first argument.
    # Honour it, so `recall <path> memory sync` targets that project's memory
    # directory rather than whatever directory the shell happens to be in.
    cwd = None
    if args and args[0].startswith("/") and os.path.isdir(args[0]):
        cwd = args[0]
        args = args[1:]

    project_folder = get_project_folder(cwd)

    cmd = args[0] if args else "status"
    flags = set(args[1:])
    target = "codex" if "--codex" in flags or "--target=codex" in flags else "claude"

    if cmd in ("status", ""):
        cmd_status(project_folder, cwd=cwd)
        return 0
    if cmd == "sync":
        return cmd_sync(project_folder,
                        dry_run="--dry-run" in flags or "-n" in flags,
                        cwd=cwd, target=target)
    if cmd in ("clear", "remove"):
        if target == "codex":
            from lib import memory_targets
            result = memory_targets.clear_region(project_root=cwd or os.getcwd())
            print("## Codex Memory Cleared")
            print()
            print(f"**File:** `{result.path}`")
            print("**Block:** removed" if result.removed
                  else "No recall block found; nothing to remove.")
            return 0
        return cmd_clear(cwd=cwd)
    if cmd == "enable":
        return cmd_set_auto(project_folder, True)
    if cmd in ("disable", "off"):
        return cmd_set_auto(project_folder, False)
    if cmd in ("store-env", "store_env"):
        return cmd_store_env()

    print(f"Unknown memory subcommand: {cmd}")
    print()
    print(f"  `{recall_command('memory')}`            Show bridge status")
    print(f"  `{recall_command('memory', 'sync')}`       Promote approved learnings and SOPs")
    print(f"  `{recall_command('memory', 'enable')}`     Also promote automatically on approval")
    print(f"  `{recall_command('memory', 'disable')}`    Stop promoting automatically")
    print(f"  `{recall_command('memory', 'clear')}`      Remove everything recall promoted")
    print(f"  `{recall_command('memory', 'store-env')}`  Print the CLAUDE_MEMORY_STORES declaration")
    print()
    print("  Add `--codex` to sync/clear the recall block in this project's AGENTS.md")
    print("  instead of Claude Code's memory directory.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
