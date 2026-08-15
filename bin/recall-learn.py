#!/usr/bin/env python3
"""
Review and manage pending learnings for the recall system.

Usage:
  recall-learn.py                    - Show pending learnings for review
  recall-learn.py --batch            - Accept all pending learnings
  recall-learn.py --approve <index>  - Approve specific learning
  recall-learn.py --reject <index>   - Reject specific learning
"""

import json
import sys
import os
from pathlib import Path

# Add lib to path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))
sys.path.insert(0, str(LIB_DIR.parent))

from knowledge import (
    get_pending_learnings,
    get_learnings,
    approve_learning,
    reject_learning,
    approve_all_pending,
    get_project_folder,
    get_bucket_for_project,
    BUCKETS,
    DEFAULT_BUCKET,
)
from lib.platform import recall_command


def _project_cwd() -> str:
    """The project directory this invocation is acting on.

    Claude Code sets ``CLAUDE_PROJECT_DIR``; the dispatcher sets it too. Falling
    back to the process cwd matches how ``get_project_folder`` resolves, so the
    index read and the memory write always agree on which project they mean.
    """
    return os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()


def promote_to_native_memory(project_folder: str, cwd: str = None):
    """Mirror approved learnings into Claude Code's native memory directory.

    Approval is the right moment to promote: it is the one point where the user
    has explicitly blessed a learning, which keeps recall from writing anything
    unreviewed into a file that loads on every future session. Promotion is
    strictly best-effort — a failure here must never cost the user their
    approval, which is already saved to the index by this point.

    *cwd* names the project being operated on, so approving learnings for one
    project can never write into another project's memory directory.

    Off unless the project has opted in with ``/recall memory enable``, and it
    will not create a memory directory that does not already exist: writing
    into Claude Code's config tree is not a reasonable side effect of a
    command the user ran to approve a learning.
    """
    try:
        from lib import native_memory
        from knowledge import load_index
        from sops import load_sops

        if not native_memory.is_enabled():
            return None
        if not native_memory.auto_promote_enabled(load_index(project_folder)):
            return None

        learnings = [l for l in get_learnings(project_folder) if isinstance(l, dict)]
        try:
            sops = native_memory.normalize_sops(load_sops())
        except Exception:
            sops = {}
        return native_memory.sync(learnings, sops, cwd=cwd, create=False)
    except Exception:
        return None


def _report_promotion(result) -> None:
    """Print a one-line summary of what promotion changed, if anything."""
    if result is None or not getattr(result, "changed", False):
        return
    print()
    print(f"Promoted to native memory: {len(result.written)} written, "
          f"{len(result.removed)} removed.")
    print("These load automatically at the start of every session in this project.")

    # Quality-gate rejections are routine and expected; only flag the ones that
    # mean something went wrong.
    blocked = [i for i in result.skipped if i.get("reason") != "not_durable"]
    if blocked:
        print(f"{len(blocked)} not written — run "
              f"`{recall_command('memory', 'sync')}` for detail.")


def format_learning(learning: dict, index: int) -> str:
    """Format a single learning for display."""
    bucket = learning.get('bucket', DEFAULT_BUCKET)
    cat = learning.get('category', 'general')
    title = learning.get('title', 'Unknown')
    desc = learning.get('description', '')
    solution = learning.get('solution', '')
    source = learning.get('source', 'manual')

    bucket_label = bucket[0].upper()
    lines = [f"### [{index}] [{bucket_label}:{cat}] {title}"]
    if desc:
        first_desc = desc.split('\n')[0]
        lines.append(f"  {first_desc}" + ('...' if '\n' in desc else ''))
    fix = learning.get('fix', '')
    guidance = fix or solution
    if guidance:
        first_line = guidance.split('\n')[0]
        suffix = '...' if '\n' in guidance else ''
        lines.append(f"  **Fix:** {first_line}{suffix}")
    lines.append(f"  _Source: {source}_")
    return '\n'.join(lines)


def show_pending(project_folder: str):
    """Show all pending learnings."""
    pending = get_pending_learnings(project_folder)
    approved = get_learnings(project_folder)

    # Count by bucket
    bucket_counts = {}
    for l in approved:
        b = l.get('bucket', DEFAULT_BUCKET) if isinstance(l, dict) else DEFAULT_BUCKET
        bucket_counts[b] = bucket_counts.get(b, 0) + 1

    print("## Pending Learnings")
    print()
    bucket_summary = ' | '.join(f"**{b.title()}:** {c}" for b, c in sorted(bucket_counts.items())) if bucket_counts else "None"
    print(f"**Approved** ({len(approved)}): {bucket_summary}")
    print(f"**Pending:** {len(pending)}")
    print()

    if not pending:
        print("No pending learnings to review.")
        print()
        print("Learnings are proposed automatically when:")
        print("  - A command fails 3+ times with the same error category")
        print("  - A failed command is followed by a successful variant")
        print()
        print()
        if approved:
            print(f"You have {len(approved)} approved learnings. Use `{recall_command('failures')}` to view them.")
        return

    # Group pending by bucket for display
    by_bucket = {}
    for i, learning in enumerate(pending):
        bucket = learning.get('bucket', DEFAULT_BUCKET) if isinstance(learning, dict) else DEFAULT_BUCKET
        if bucket not in by_bucket:
            by_bucket[bucket] = []
        by_bucket[bucket].append((i, learning))

    # Show known buckets first (in BUCKETS order), then unknown ones
    shown = set()
    for bucket_key, bucket_desc in BUCKETS.items():
        items = by_bucket.get(bucket_key, [])
        if items:
            print(f"### {bucket_desc}")
            print()
            for i, learning in items:
                print(format_learning(learning, i))
                print()
        shown.add(bucket_key)

    for bucket_key, items in by_bucket.items():
        if bucket_key not in shown:
            label = bucket_key.title()
            print(f"### {label}")
            print()
            for i, learning in items:
                print(format_learning(learning, i))
                print()

    print("---")
    print("**Actions:**")
    print(f"  `{recall_command('learn', '--batch')}` - Accept all pending learnings")
    print(f"  `{recall_command('learn', '--approve', '0')}` - Approve learning #0")
    print(f"  `{recall_command('learn', '--reject', '0')}` - Reject learning #0")


def batch_approve(project_folder: str):
    """Approve all pending learnings."""
    count = approve_all_pending(project_folder)
    if count > 0:
        print(f"## Approved {count} learnings")
        print()
        print(f"These will now appear in `{recall_command('failures')}` and session-start context.")
        _report_promotion(promote_to_native_memory(project_folder, cwd=_project_cwd()))
    else:
        print("No pending learnings to approve.")


def approve_one(project_folder: str, index_str: str):
    """Approve a specific learning by index."""
    try:
        idx = int(index_str)
    except ValueError:
        print(f"Invalid index: {index_str}")
        return

    learning = approve_learning(idx, project_folder)
    if learning:
        print(f"Approved: [{learning.get('category')}] {learning.get('title')}")
        _report_promotion(promote_to_native_memory(project_folder, cwd=_project_cwd()))
    else:
        print(f"No pending learning at index {idx}")


def reject_one(project_folder: str, index_str: str):
    """Reject a specific learning by index."""
    try:
        idx = int(index_str)
    except ValueError:
        print(f"Invalid index: {index_str}")
        return

    learning = reject_learning(idx, project_folder)
    if learning:
        print(f"Rejected: [{learning.get('category')}] {learning.get('title')}")
    else:
        print(f"No pending learning at index {idx}")


def prune_approved(project_folder: str, confirmed: bool = False):
    """Drop already-approved learnings that cannot state a reusable rule.

    The proposal gate only guards new learnings. Indexes written before it
    existed still hold incident records — "Recurring general errors (3x)" and
    verbatim command substitutions — which clutter `/recall failures` and the
    session-start context forever. This is the cleanup path for those.
    """
    from lib.learning_quality import is_durable
    from lib.shared import save_index
    from knowledge import load_index

    index = load_index(project_folder)
    approved = [l for l in index.get('learnings', []) if isinstance(l, dict)]

    keep, drop = [], []
    for learning in approved:
        ok, reason = is_durable(learning)
        (keep if ok else drop).append(learning if ok else (learning, reason))

    print("## Prune approved learnings")
    print()
    if not drop:
        print(f"All {len(keep)} approved learnings state a usable rule. Nothing to prune.")
        return 0

    print(f"**{len(drop)} of {len(approved)}** carry no reusable rule:")
    print()
    for learning, reason in drop:
        print(f"  · {learning.get('title', '(untitled)')} — {reason}")

    if not confirmed:
        print()
        print("These are still visible in the index. Re-run with `--yes` to remove them:")
        print(f"  `{recall_command('learn', '--prune', '--yes')}`")
        return 0

    index['learnings'] = keep
    save_index(index, project_folder)
    print()
    print(f"Removed {len(drop)}. {len(keep)} approved learnings remain.")
    return 0


def main():
    project_folder = get_project_folder()

    args = sys.argv[1:]

    if not args:
        show_pending(project_folder)
    elif args[0] == '--batch':
        batch_approve(project_folder)
    elif args[0] == '--approve' and len(args) > 1:
        approve_one(project_folder, args[1])
    elif args[0] == '--reject' and len(args) > 1:
        reject_one(project_folder, args[1])
    elif args[0] == '--prune':
        prune_approved(project_folder, confirmed='--yes' in args[1:])
    else:
        show_pending(project_folder)


if __name__ == '__main__':
    main()
