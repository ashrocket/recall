"""
Where promoted knowledge goes, per agent.

Claude Code gives recall a *directory* to own: one file per memory, plus an
index. Ownership there is per-file — a filename prefix and a frontmatter marker
agree, and recall touches nothing else.

Codex has no such directory. What it has is `AGENTS.md`, a single file injected
as the first user turn of every session, which the user also writes by hand. So
ownership cannot be per-file; it has to be a *region* inside a file recall does
not own. That is the whole abstraction: a marker-fenced block that recall
rewrites wholesale, with every byte outside the fence preserved exactly.

The two targets share the documents (:class:`lib.native_memory.MemoryDoc`) and
the promotion gate (:mod:`lib.learning_quality`). Only the write strategy
differs.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from lib.native_memory import MemoryDoc, build_docs
except ImportError:
    from native_memory import MemoryDoc, build_docs


#: Fence markers. Chosen to be invisible in rendered markdown, so a user
#: reading AGENTS.md sees the content rather than the bookkeeping.
REGION_START = "<!-- recall:start -->"
REGION_END = "<!-- recall:end -->"

#: Codex caps the combined instruction files at 32 KiB. recall takes a small
#: slice of that and no more — the file belongs to the user, not to us.
DEFAULT_REGION_BUDGET = 4096

_REGION_RE = re.compile(
    re.escape(REGION_START) + r".*?" + re.escape(REGION_END),
    re.DOTALL,
)


@dataclass
class RegionResult:
    path: Optional[Path] = None
    written: bool = False
    removed: bool = False
    doc_count: int = 0
    truncated: int = 0
    bytes_used: int = 0
    skipped: List[dict] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.written or self.removed)


def agents_md_path(project_root: str) -> Path:
    """The Codex instruction file for *project_root*."""
    return Path(project_root) / "AGENTS.md"


def render_region(docs: List[MemoryDoc], budget: int = DEFAULT_REGION_BUDGET):
    """Render the fenced block for *docs*, and how many did not fit.

    Returns ``(text, truncated_count)``. Docs are emitted whole or not at all —
    a half-written rule is worse than an absent one — and the caller reports
    what was dropped rather than letting it vanish.
    """
    header = [
        REGION_START,
        "<!-- Managed by recall. Edits inside this block are overwritten;",
        "     everything outside it is left alone. `recall memory clear` removes it. -->",
        "",
        "## Project knowledge (recall)",
        "",
    ]
    footer = [REGION_END]

    fixed = len("\n".join(header + footer)) + 2
    body: List[str] = []
    used = fixed
    truncated = 0

    for doc in docs:
        entry = f"- **{doc.title}** — {doc.description}\n  {_one_line_body(doc)}"
        cost = len(entry) + 1
        if used + cost > budget:
            truncated += 1
            continue
        body.append(entry)
        used += cost

    if not body:
        return "", len(docs)

    return "\n".join(header + body + [""] + footer) + "\n", truncated


def _one_line_body(doc: MemoryDoc) -> str:
    """Collapse a document to the single actionable line Codex should see."""
    for line in doc.body.splitlines():
        stripped = line.strip()
        if stripped.startswith("**How to apply:**"):
            return stripped[len("**How to apply:**"):].strip()
        if stripped.startswith("**Fix:**"):
            return stripped[len("**Fix:**"):].strip()
    return " ".join(doc.body.split())[:200]


def apply_region(existing: str, region: str) -> str:
    """Return *existing* with recall's region replaced by *region*.

    Everything outside the fence is preserved byte for byte, including a
    trailing region the user may have moved. An empty *region* removes the
    block entirely.
    """
    existing = existing or ""

    if _REGION_RE.search(existing):
        if not region:
            cleaned = _REGION_RE.sub("", existing, count=1)
            return re.sub(r"\n{3,}", "\n\n", cleaned).rstrip("\n") + "\n" if cleaned.strip() else ""
        return _REGION_RE.sub(lambda _m: region.rstrip("\n"), existing, count=1)

    if not region:
        return existing

    if not existing.strip():
        return region

    return existing.rstrip("\n") + "\n\n" + region


def sync_region(
    learnings: List[dict],
    sops: dict = None,
    project_root: str = ".",
    budget: int = DEFAULT_REGION_BUDGET,
    create: bool = False,
) -> RegionResult:
    """Write recall's fenced block into the project's ``AGENTS.md``.

    Like the Claude Code path, this refuses to create the file it writes into:
    a project with no ``AGENTS.md`` is a project not using Codex, and planting
    one is not recall's call to make.
    """
    path = agents_md_path(project_root)
    result = RegionResult(path=path)

    docs = build_docs(learnings, sops)
    region, truncated = render_region(docs, budget)
    result.doc_count = len(docs) - truncated
    result.truncated = truncated
    result.bytes_used = len(region)

    if truncated:
        result.skipped.append({
            "name": f"{truncated} more item(s)",
            "reason": "over_budget",
            "detail": f"the AGENTS.md block is capped at {budget} bytes",
        })

    if not path.exists() and not create:
        result.skipped.append({
            "name": path.name,
            "reason": "absent",
            "detail": "no AGENTS.md in this project; recall will not create one",
        })
        return result

    existing = path.read_text(errors="replace") if path.exists() else ""
    updated = apply_region(existing, region)

    if updated == existing:
        return result

    if not updated.strip():
        # recall's block was the only thing in a file recall created.
        path.write_text("")
    else:
        path.write_text(updated)

    result.written = bool(region)
    result.removed = not region and _REGION_RE.search(existing) is not None
    return result


def clear_region(project_root: str = ".") -> RegionResult:
    """Remove recall's block from ``AGENTS.md``, leaving the rest untouched."""
    return sync_region([], {}, project_root=project_root, create=False)
