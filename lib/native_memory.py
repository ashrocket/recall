"""
Native memory bridge.

Claude Code keeps a per-project auto-memory directory at
``~/.claude/projects/<slug>/memory/``. Its ``MEMORY.md`` index is injected into
every session in that project — as a ``<system-reminder>`` attached to the first
user message, not in the system prompt proper — and the topic files it points at
are read on demand. That makes it the one memory surface reachable without an
API, auth, or org enrollment.

It is not, however, unconditional. Injection is subject to server-side feature
gating, a model-dependent check, the ``autoMemoryEnabled`` setting, and the
``CLAUDE_CODE_SIMPLE`` / ``CLAUDE_CODE_REMOTE`` modes. Anthropic can turn this
surface off without shipping a release, and recall cannot detect that from the
outside. The bridge degrades quietly if that happens: files stay on disk and
nothing breaks, they just stop being read.

recall already distills durable signal out of sessions — approved learnings and
SOPs. This module promotes that distilled signal into the native directory so it
is loaded automatically at session start, instead of only when the user runs a
``/recall`` subcommand.

Two rules govern every write:

* **Only distilled artifacts get promoted.** ``MEMORY.md`` is loaded into every
  session; the raw session index would drown it. Approved learnings and matched
  SOPs only.
* **recall only ever edits what recall wrote.** Every promoted file carries
  ``metadata.source: recall`` in its frontmatter, and every index pointer links a
  ``recall-*.md`` target. Files and index lines without those markers — whether
  the user wrote them or Claude did — are never rewritten or removed.

On ``CLAUDE_MEMORY_STORES``
--------------------------
Claude Code 2.1.229 also accepts a ``CLAUDE_MEMORY_STORES`` env var that declares
named memory stores. Declaring one is a net context *loss* for a local CLI
session, measured by capturing the request Claude Code actually sends: any
non-empty value — including a garbage value that declares no store at all —
stops ``MEMORY.md`` being injected, because the check is only whether the
variable is set. The replacement, loading the store's own ``promptIndex``, did
not fire in a local session under API-key auth; the declared mount materialised
as an empty directory. Managed and org sessions may well behave differently.

So recall never sets that variable. ``recall memory store-env`` prints the
declaration with the tradeoff spelled out, for when org stores become reachable.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Support being imported as both 'native_memory' (lib/ on sys.path) and
# 'lib.native_memory', matching the rest of lib/.
try:
    from lib.platform import Platform, detect_platform
    from lib.sync_scan import scan_for_secrets
    from lib.learning_quality import (
        MIN_GUIDANCE_LEN,
        TEMPLATE_PREFIXES,
        TRANSIENT_SOURCES,
        guidance_of,
        hook_text,
        is_durable,
    )
except ImportError:
    from platform import Platform, detect_platform
    from sync_scan import scan_for_secrets
    from learning_quality import (
        MIN_GUIDANCE_LEN,
        TEMPLATE_PREFIXES,
        TRANSIENT_SOURCES,
        guidance_of,
        hook_text,
        is_durable,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Filename prefix that marks a memory document as recall-owned. Also the
#: signature used to find recall's own pointer lines inside MEMORY.md.
FILE_PREFIX = "recall-"

#: Frontmatter value recorded under ``metadata.source`` for every promoted file.
SOURCE_MARKER = "recall"

INDEX_NAME = "MEMORY.md"
INDEX_HEADER = "# Memory Index"

#: Claude Code inlines only the first ~200 lines of MEMORY.md. Promoted pointers
#: are capped well under that so recall can never crowd out the user's own
#: entries — the whole point of the bridge is to add signal, not to evict it.
MAX_PROMOTED_POINTERS = 40

#: Slug length cap, keeping filenames readable in the index.
MAX_SLUG_LEN = 48


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

_FALSEY = {"0", "false", "off", "no"}
_TRUTHY = {"1", "true", "on", "yes"}


def _env_flag(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in _FALSEY:
        return False
    if val in _TRUTHY:
        return True
    return None


def _claude_config_dir() -> Path:
    """The Claude Code config root — ``CLAUDE_CONFIG_DIR`` or ``~/.claude``."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def _read_bool_setting(path: Path, key: str):
    """Return ``path``'s ``key`` if it is a bool, else ``None`` (missing/unreadable)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


def auto_memory_setting(cwd: str = None):
    """Return Claude Code's ``autoMemoryEnabled`` setting, or ``None`` if unset.

    Claude Code's product toggle (``/memory``) writes this key with no env var
    set, and recall must honour it or it promotes into a directory the user
    told Claude Code not to read. Read down the settings ladder with the
    closest scope winning — project-local over project over user — matching
    Claude Code's own precedence.
    """
    value = _read_bool_setting(_claude_config_dir() / "settings.json", "autoMemoryEnabled")

    root = cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for parent in [Path(root), *Path(root).parents]:
        claude_dir = parent / ".claude"
        if not claude_dir.is_dir():
            continue
        proj = _read_bool_setting(claude_dir / "settings.json", "autoMemoryEnabled")
        if proj is not None:
            value = proj
        local = _read_bool_setting(claude_dir / "settings.local.json", "autoMemoryEnabled")
        if local is not None:
            value = local
        break  # nearest project directory wins; do not keep climbing
    return value


def is_enabled(cwd: str = None) -> bool:
    """Return whether recall should promote into the native memory directory.

    Codex has no per-project auto-memory directory, so promoting from a Codex
    session would plant files nothing reads — it is blocked explicitly. An
    *undetected* platform is allowed through: that is what a plain shell looks
    like when the user runs ``recall`` directly, and the target directory is
    still Claude Code's.

    Beyond recall's own ``RECALL_NATIVE_MEMORY=0`` opt-out, this mirrors Claude
    Code's auto-memory gate in its own precedence order, for the parts a
    subprocess can observe:

    * ``CLAUDE_CODE_DISABLE_AUTO_MEMORY`` is tri-state. A truthy value disables.
      A *falsey* value (``=0``/``false``) is an explicit **force-enable** that
      wins over the settings toggle below — mirroring the binary, where the
      force-enable branch short-circuits before ``autoMemoryEnabled`` is read.
      Getting this precedence wrong would invert the bug onto users who opted
      in, so it is tested directly.
    * ``autoMemoryEnabled: false`` in settings disables, with no env var set.
      This is the silent data-loss case the gate exists to catch.

    Not observable from a subprocess, so deliberately not checked: the
    in-session ``/memory`` toggle, safe mode, and the model-dependent remote
    disable. In those states recall may over-promote; it can never wrongly
    suppress, which is the safe direction to err.
    """
    if _env_flag("RECALL_NATIVE_MEMORY") is False:
        return False
    if os.environ.get("RECALL_AGENT", "").strip().lower() == "codex":
        return False
    if detect_platform() == Platform.CODEX:
        return False

    disable = _env_flag("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    if disable is True:
        return False
    if disable is False:
        return True  # explicit force-enable wins over the settings toggle
    if os.environ.get("CLAUDE_CODE_SIMPLE", "").strip():
        return False
    if auto_memory_setting(cwd) is False:
        return False
    return True


#: Key under ``recall-index.json``'s ``settings`` that opts a project into
#: promoting automatically when a learning is approved.
AUTO_PROMOTE_SETTING = "native_memory_auto_promote"


def auto_promote_enabled(index: dict = None) -> bool:
    """Return whether approving a learning may write to native memory.

    Default off, deliberately. Writing into Claude Code's own config directory
    is not something to switch on as a side effect of another command — the
    user turns it on with ``/recall memory enable``. ``/recall memory sync``
    stays available regardless, because that is an explicit instruction.
    """
    if not isinstance(index, dict):
        return False
    return bool(index.get("settings", {}).get(AUTO_PROMOTE_SETTING, False))


def index_injection_suppressed() -> bool:
    """Return whether a declared memory store is suppressing MEMORY.md inlining.

    See the module docstring: any non-empty ``CLAUDE_MEMORY_STORES`` turns off
    the auto-memory index injection that this bridge depends on.
    """
    return bool(os.environ.get("CLAUDE_MEMORY_STORES", "").strip())


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _projects_root() -> Path:
    """Return the ``projects`` root Claude Code is actually using.

    ``CLAUDE_CONFIG_DIR`` relocates the whole ``~/.claude`` tree, and the memory
    directory moves with it. Honouring it here keeps the bridge pointed at the
    real directory, and gives tests a way to run without touching the user's.
    """
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / ".claude"
    return base / "projects"


def memory_project_folder(cwd: str = None) -> str:
    """Return the project-folder slug Claude Code uses for *cwd*'s memory dir.

    Claude Code derives the slug from the *session's* working directory, with
    symlinks resolved. recall's own index slug can differ — it folds git
    worktrees back onto the main repo — so the memory directory is resolved
    independently here. When both a realpath-based and a literal slug exist on
    disk, the one that already holds a memory directory wins.
    """
    if cwd is None:
        cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    candidates = []
    for path in (os.path.realpath(cwd), cwd):
        slug = path.replace("/", "-")
        if slug not in candidates:
            candidates.append(slug)

    root = _projects_root()
    for slug in candidates:
        if (root / slug / "memory").is_dir():
            return slug
    for slug in candidates:
        if (root / slug).is_dir():
            return slug
    return candidates[0]


def memory_dir(cwd: str = None, project_folder: str = None) -> Path:
    """Return ``<config>/projects/<slug>/memory`` for *cwd*.

    Pass *project_folder* to name the slug outright. Otherwise it is derived
    from *cwd* — which matters, because recall's own project folder folds git
    worktrees back onto the main repo while Claude Code's memory directory
    stays keyed to the session's actual working directory. Promotion therefore
    reads learnings from recall's folder but writes to the directory the
    running session will actually load.
    """
    slug = project_folder or memory_project_folder(cwd)
    return _projects_root() / slug / "memory"


def index_path(cwd: str = None, project_folder: str = None) -> Path:
    """Return the path to the native ``MEMORY.md`` index for *cwd*."""
    return memory_dir(cwd, project_folder) / INDEX_NAME


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@dataclass
class MemoryDoc:
    """One native memory file: a single fact, plus the pointer line for it."""

    name: str
    title: str
    description: str
    type: str
    body: str
    key: str
    links: List[str] = field(default_factory=list)
    #: Pinned documents have their *full content* injected into every session,
    #: not just their index pointer. Claude Code allows four; recall claims at
    #: most one. See :func:`playbook_doc`.
    pinned: bool = False

    @property
    def filename(self) -> str:
        return f"{self.name}.md"


def _slugify(text: str, max_len: int = MAX_SLUG_LEN) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def _key_hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:6]


def _one_line(text: str, limit: int = 160) -> str:
    """Collapse *text* to a single line, for frontmatter and pointer hooks."""
    flat = " ".join((text or "").split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


def _escape_yaml(value: str) -> str:
    """Quote a scalar when plain style would be ambiguous or invalid."""
    flat = _one_line(value, limit=10_000)
    if not flat:
        return '""'
    if flat[0] in "&*!|>%@`[]{}#,\"'" or ": " in flat or flat.endswith(":"):
        return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return flat


def install_id() -> str:
    """A stable id for this recall installation, used as ``metadata.origin``.

    Deliberately a random opaque id rather than a hostname or username: these
    files are shaped to survive being carried into a shared store one day, and
    an identifier is all prune needs. Generated once and cached on disk.
    """
    global _INSTALL_ID
    if _INSTALL_ID:
        return _INSTALL_ID

    path = Path.home() / ".config" / "recall" / "install-id"
    try:
        _INSTALL_ID = path.read_text().strip()
    except OSError:
        _INSTALL_ID = ""

    if not _INSTALL_ID:
        import uuid
        _INSTALL_ID = uuid.uuid4().hex[:16]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_INSTALL_ID + "\n")
        except OSError:
            pass  # a non-persisted id still works for this process
    return _INSTALL_ID


_INSTALL_ID = ""


def body_hash(body: str) -> str:
    """Hash of a document's body, recorded so hand-edits are detectable."""
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:16]


def render(doc: MemoryDoc) -> str:
    """Render *doc* as a native memory file (frontmatter + body).

    Rendering is deterministic — no timestamps, no counters. Identical inputs
    produce a byte-identical file, so :func:`sync` skips the write and the
    file's mtime never moves. That keeps repeated syncs free and keeps recall
    from churning a directory Claude Code reads.
    """
    body = doc.body.strip()
    if doc.links:
        body += "\n\nRelated: " + " ".join(f"[[{link}]]" for link in doc.links)

    lines = [
        "---",
        f"name: {_escape_yaml(doc.name)}",
        f"description: {_escape_yaml(doc.description)}",
        "metadata:",
        f"  type: {doc.type}",
    ]
    if doc.pinned:
        lines.append("  pinned: true")
    lines += [
        f"  source: {SOURCE_MARKER}",
        f"  origin: {install_id()}",
        f"  recall_key: {_escape_yaml(doc.key)}",
        f"  content_sha256: {body_hash(body)}",
        "---",
        "",
        body,
    ]
    return "\n".join(lines) + "\n"


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict:
    """Extract the flat frontmatter fields recall cares about.

    Deliberately not a YAML parser: the hook path must stay dependency-free and
    fast, and only ``name``, ``description`` and the ``metadata`` block matter.
    """
    match = _FRONTMATTER_RE.match(text or "")
    if not match:
        return {}

    fields: dict = {}
    metadata: dict = {}
    in_metadata = False
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1] in (" ", "\t")
        if not indented:
            in_metadata = False
        key, sep, value = raw.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip("'\"")
        if key == "metadata":
            # Block style opens a nested mapping. Flow style ("metadata: {a: b}")
            # is valid YAML this parser deliberately does not read; treat it as
            # absent rather than storing a string under a key callers expect to
            # be a mapping.
            in_metadata = not value
            continue
        if in_metadata and indented:
            metadata[key] = value
        elif not indented:
            fields[key] = value
    if metadata:
        fields["metadata"] = metadata
    return fields


def _metadata_of(text: str) -> dict:
    """Return the ``metadata`` mapping from *text*, or ``{}`` if unreadable."""
    meta = parse_frontmatter(text).get("metadata")
    return meta if isinstance(meta, dict) else {}


def is_recall_owned(path: Path) -> bool:
    """Return whether *path* is a memory file recall wrote and may rewrite.

    Both the filename prefix and the frontmatter marker must agree. A file the
    user happened to name ``recall-notes.md`` is left alone.
    """
    if not path.name.startswith(FILE_PREFIX) or path.suffix != ".md":
        return False
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    return _metadata_of(text).get("source") == SOURCE_MARKER


def recall_key_of(path: Path) -> Optional[str]:
    """Return the ``recall_key`` recorded in *path*, if it is recall-owned."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    meta = _metadata_of(text)
    if meta.get("source") != SOURCE_MARKER:
        return None
    return meta.get("recall_key")


def is_own_origin(path: Path) -> bool:
    """Return whether *this* installation wrote *path*.

    Prune deletes files; deleting one another writer owns is the failure mode
    that matters the moment these documents live anywhere shared. Files written
    before ``origin`` existed carry no marker — those are treated as ours,
    because today the only writer is this machine and the alternative is
    stale files that can never be cleaned up. Revisit that default before
    pointing this at a shared store.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    meta = _metadata_of(text)
    if meta.get("source") != SOURCE_MARKER:
        return False
    origin = meta.get("origin")
    return not origin or origin == install_id()


def has_local_edits(path: Path) -> bool:
    """Return whether a recall-owned file was changed by hand after writing.

    ``content_sha256`` records what recall wrote. If the body no longer hashes
    to it, someone edited the file — and recall should neither silently
    overwrite that work nor prune it.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    meta = _metadata_of(text)
    recorded = meta.get("content_sha256")
    if not recorded:
        return False  # written before hashes were recorded
    match = _FRONTMATTER_RE.match(text)
    body = text[match.end():] if match else text
    return body_hash(body) != recorded


# ---------------------------------------------------------------------------
# Building documents from recall artifacts
# ---------------------------------------------------------------------------

def _learning_key(learning: dict) -> str:
    title = (learning.get("title") or "").strip()
    desc = " ".join((learning.get("description") or "").split())[:80]
    return f"learning:{title}|{desc}"


_guidance = guidance_of


def is_promotable(learning: dict):
    """Return ``(ok, reason)`` for whether *learning* belongs in native memory.

    Delegates to :func:`lib.learning_quality.is_durable`, which is also applied
    upstream when a learning is first proposed. Keeping the check here too is
    deliberate defense in depth: indexes written before the upstream gate
    existed still contain incident records, and this is the last point before
    anything is written into Claude Code's own directory.
    """
    return is_durable(learning)


def partition_learnings(learnings: List[dict]):
    """Split *learnings* into ``(promotable, [(learning, reason), ...])``."""
    keep, rejected = [], []
    for learning in learnings or []:
        ok, reason = is_promotable(learning)
        (keep if ok else rejected).append(learning if ok else (learning, reason))
    return keep, rejected


_hook_text = hook_text


def learning_to_doc(learning: dict) -> MemoryDoc:
    """Convert an approved recall learning into a ``feedback`` memory document.

    ``feedback`` is the documented type for guidance on how to work, which is
    exactly what a recall learning is: a rule derived from something that went
    wrong, plus the fix.
    """
    title = (learning.get("title") or "Untitled learning").strip()
    description = (learning.get("description") or "").strip()
    guidance = _guidance(learning)
    category = (learning.get("category") or "general").strip()

    key = _learning_key(learning)
    name = f"{FILE_PREFIX}learning-{_slugify(title)}"

    body_lines = [description or title, ""]
    body_lines.append(
        f"**Why:** recall recorded this from a recurring `{category}` failure "
        f"in this project, and you approved it via `/recall learn`."
    )
    body_lines.append(
        f"**How to apply:** {guidance}" if guidance
        else "**How to apply:** Watch for this pattern and stop before repeating it."
    )
    return MemoryDoc(
        name=name,
        title=title,
        description=_one_line(_hook_text(learning)),
        type="feedback",
        body="\n".join(body_lines),
        key=key,
    )


def sop_to_doc(sop_name: str, sop: dict) -> MemoryDoc:
    """Convert an SOP into a ``reference`` memory document.

    SOPs promote unconditionally: unlike an auto-extracted learning, somebody
    hand-wrote the procedure, which is itself the judgement call that it is
    worth keeping around.
    """
    description = (sop.get("description") or sop_name).strip()
    fixes = [str(f).strip() for f in (sop.get("fixes") or []) if str(f).strip()]
    patterns = [str(p).strip() for p in (sop.get("patterns") or []) if str(p).strip()]
    examples = sop.get("examples") or {}

    key = f"sop:{sop_name}"
    name = f"{FILE_PREFIX}sop-{_slugify(sop_name)}"

    body_lines = [description, ""]
    if patterns:
        body_lines.append(
            "**Trigger:** errors matching " + ", ".join(f"`{p}`" for p in patterns) + "."
        )
    if fixes:
        body_lines.append("**Fix:**")
        body_lines.extend(f"- {fix}" for fix in fixes)
    else:
        body_lines.append("**Fix:** see the SOP definition.")
    if examples.get("bad"):
        body_lines.append(f"- Avoid: `{examples['bad']}`")
    if examples.get("good"):
        body_lines.append(f"- Prefer: `{examples['good']}`")

    return MemoryDoc(
        name=name,
        title=sop_name,
        description=_one_line(description),
        type="reference",
        body="\n".join(body_lines),
        key=key,
    )


def _disambiguate(docs: List[MemoryDoc]) -> List[MemoryDoc]:
    """Give colliding slugs a stable suffix so each key keeps its own file."""
    seen: dict = {}
    out: List[MemoryDoc] = []
    for doc in docs:
        claimed = seen.get(doc.name)
        if claimed is not None and claimed != doc.key:
            doc = MemoryDoc(
                name=f"{doc.name}-{_key_hash(doc.key)}",
                title=doc.title,
                description=doc.description,
                type=doc.type,
                body=doc.body,
                key=doc.key,
                links=doc.links,
            )
        seen.setdefault(doc.name, doc.key)
        out.append(doc)
    return out


#: Claude Code injects the full content of at most this many pinned memories.
MAX_PINS = 4

#: recall claims one pin at most, ever. The other three belong to the user.
PLAYBOOK_NAME = f"{FILE_PREFIX}project-playbook"


def count_foreign_pins(target: Path) -> int:
    """How many pinned memories in *target* belong to someone other than recall."""
    if not target.is_dir():
        return 0
    total = 0
    for path in sorted(target.glob("*.md")):
        if path.name == INDEX_NAME or path.name.startswith(FILE_PREFIX):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if str(_metadata_of(text).get("pinned", "")).strip().lower() == "true":
            total += 1
    return total


def playbook_doc(docs: List[MemoryDoc]) -> Optional[MemoryDoc]:
    """Build the single pinned document that carries this project's rules.

    Pointer entries in ``MEMORY.md`` only get *read* if the model decides to
    follow them. A pinned memory has its whole body injected into every
    session, which is the difference between knowledge being available and
    knowledge being present. recall folds everything it promotes into one such
    document rather than pinning several, because the budget is four and three
    of them are not recall's to spend.

    Rendered deterministically from already-promoted content: it changes only
    when the user approves or prunes a learning, so its mtime stays put and it
    cannot float above the user's own pins in the recency ordering.
    """
    if not docs:
        return None

    lines = [
        "Rules that apply to this project, distilled by recall from past "
        "sessions and approved by the user.",
        "",
    ]
    for doc in docs:
        lines.append(f"- **{doc.title}** — {_one_line(doc.description, 140)}")
        action = _actionable_line(doc)
        if action:
            lines.append(f"  {action}")

    return MemoryDoc(
        name=PLAYBOOK_NAME,
        title="Project playbook",
        description="Approved rules for this project, distilled by recall",
        type="project",
        body="\n".join(lines),
        key="playbook",
        pinned=True,
    )


def _actionable_line(doc: MemoryDoc) -> str:
    """The one line from *doc* worth carrying into every session.

    Learnings put the guidance inline after the marker; SOPs use the marker as
    a header with the fixes listed beneath it. Both shapes have to resolve to a
    line, or the playbook lists a rule with no instruction attached.
    """
    lines = doc.body.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        for prefix in ("**How to apply:**", "**Fix:**"):
            if not stripped.startswith(prefix):
                continue
            inline = stripped[len(prefix):].strip()
            if inline:
                return _one_line(inline, 160)
            # Marker was a header — collect the bullets under it.
            bullets = []
            for follow in lines[i + 1:]:
                item = follow.strip()
                if not item.startswith("- "):
                    break
                bullets.append(item[2:].strip())
            if bullets:
                return _one_line("; ".join(bullets), 160)
    return ""


def normalize_sops(sops) -> dict:
    """Return a flat ``{name: sop}`` map from either shape.

    ``lib.sops.load_sops()`` returns the *file* shape — ``{"version": 1,
    "sops": {...}}`` — so unwrap it rather than treating ``"version"`` and
    ``"sops"`` as SOP names.
    """
    if not isinstance(sops, dict):
        return {}
    if "sops" in sops and isinstance(sops["sops"], dict):
        return sops["sops"]
    return {k: v for k, v in sops.items() if isinstance(v, dict)}


def build_docs(learnings: List[dict], sops: dict = None) -> List[MemoryDoc]:
    """Build the full set of documents recall wants present in native memory.

    SOPs are never dropped by the pointer cap. They are hand-authored, so a
    flood of auto-extracted learnings must not be able to evict them — only
    learnings are truncated.
    """
    learning_docs: List[MemoryDoc] = []
    sop_docs: List[MemoryDoc] = []
    seen_keys = set()

    promotable, _rejected = partition_learnings(learnings)
    for learning in promotable:
        doc = learning_to_doc(learning)
        if doc.key in seen_keys:
            continue
        seen_keys.add(doc.key)
        learning_docs.append(doc)

    for sop_name, sop in sorted(normalize_sops(sops).items()):
        if not isinstance(sop, dict):
            continue
        doc = sop_to_doc(sop_name, sop)
        if doc.key in seen_keys:
            continue
        seen_keys.add(doc.key)
        sop_docs.append(doc)

    learning_budget = max(0, MAX_PROMOTED_POINTERS - len(sop_docs))
    return _disambiguate(sop_docs + learning_docs[:learning_budget])


def over_cap_learnings(learnings: List[dict], sops: dict = None) -> int:
    """How many promotable learnings the pointer cap left out."""
    promotable, _ = partition_learnings(learnings)
    budget = max(0, MAX_PROMOTED_POINTERS - len(normalize_sops(sops)))
    return max(0, len(promotable) - budget)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    written: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    skipped: List[dict] = field(default_factory=list)
    index_updated: bool = False
    memory_dir: Optional[Path] = None
    #: Set when the write was refused outright rather than merely producing
    #: nothing — currently only "the memory directory does not exist".
    blocked: Optional[str] = None

    @property
    def changed(self) -> bool:
        return bool(self.written or self.removed or self.index_updated)


def _pointer_line(doc: MemoryDoc) -> str:
    title = _one_line(doc.title or doc.name, 60)
    hook = _one_line(doc.description or doc.title or doc.name, 100)
    return f"- [{title}]({doc.filename}) — {hook}"


_POINTER_TARGET_RE = re.compile(r"^\s*-\s*\[[^\]]*\]\(([^)]+)\)")


def _pointer_target(line: str) -> Optional[str]:
    match = _POINTER_TARGET_RE.match(line)
    return match.group(1) if match else None


def _is_recall_pointer(line: str, target_dir: Path = None) -> bool:
    """Return whether *line* is an index pointer recall owns and may rewrite.

    The filename prefix alone is not ownership — a user is free to write their
    own ``recall-notes.md`` and link it. When the linked file exists, it must
    also carry recall's frontmatter marker, matching the rule applied to files.
    A pointer whose target is missing is treated as recall's own orphan so the
    dangling line can still be pruned.
    """
    name = _pointer_target(line)
    if not name or not name.startswith(FILE_PREFIX):
        return False
    if target_dir is None:
        return True
    path = target_dir / name
    if not path.exists():
        return True
    return is_recall_owned(path)


def render_index(existing: str, docs: List[MemoryDoc], target_dir: Path = None) -> str:
    """Return ``MEMORY.md`` content with recall's pointer block refreshed.

    Every line that is not a recall pointer is preserved verbatim and in order,
    so entries the user or Claude wrote survive untouched.
    """
    lines = (existing or "").splitlines()
    kept = [line for line in lines if not _is_recall_pointer(line, target_dir)]

    while kept and not kept[-1].strip():
        kept.pop()

    if not kept:
        # Header only — the blank separator is added below, so adding one here
        # too would grow the file by a line on every sync.
        kept = [INDEX_HEADER]

    if docs:
        kept.append("")
        kept.extend(_pointer_line(doc) for doc in docs)

    return "\n".join(kept).lstrip("\n") + "\n"


def plan(
    learnings: List[dict],
    sops: dict = None,
    cwd: str = None,
    secret_scan: bool = True,
    project_folder: str = None,
    pin: bool = True,
):
    """Return ``(docs_that_would_land, skipped, target_dir)`` without writing.

    ``sync`` and ``--dry-run`` share this so a dry run can never predict a
    different outcome than the real thing.
    """
    target = memory_dir(cwd, project_folder)
    docs = build_docs(learnings, sops)
    skipped: List[dict] = []

    # Report what the quality gate held back, so a filtered learning never
    # looks like a lost one.
    for learning, reason in partition_learnings(learnings)[1]:
        skipped.append({
            "name": (learning.get("title") if isinstance(learning, dict) else None)
                    or "(untitled)",
            "reason": "not_durable",
            "detail": reason,
        })

    dropped = over_cap_learnings(learnings, sops)
    if dropped:
        skipped.append({
            "name": f"{dropped} more learning(s)",
            "reason": "over_cap",
            "detail": f"the index holds at most {MAX_PROMOTED_POINTERS} promoted entries",
        })

    # One pinned playbook, carrying the full text of everything promoted into
    # every session — but only if the user has a pin slot to spare.
    if pin and docs:
        book = playbook_doc(docs)
        if book is not None:
            foreign = count_foreign_pins(target)
            if foreign >= MAX_PINS:
                skipped.append({
                    "name": f"{PLAYBOOK_NAME}.md",
                    "reason": "pin_budget",
                    "detail": f"you already have {foreign} pinned memories "
                              f"(Claude Code loads {MAX_PINS}); recall will not evict one",
                })
            else:
                docs = docs + [book]

    keep: List[MemoryDoc] = []
    for doc in docs:
        if secret_scan:
            findings = scan_for_secrets(render(doc))
            if findings:
                skipped.append({
                    "name": doc.filename,
                    "reason": "secret_scan",
                    "findings": findings,
                })
                continue

        path = target / doc.filename
        if path.exists() and not is_recall_owned(path):
            skipped.append({"name": doc.filename, "reason": "not_recall_owned"})
            continue

        if path.exists() and has_local_edits(path):
            skipped.append({
                "name": doc.filename,
                "reason": "hand_edited",
                "detail": "you edited this file; recall will not overwrite it",
            })
            continue

        keep.append(doc)

    return keep, skipped, target


def sync(
    learnings: List[dict],
    sops: dict = None,
    cwd: str = None,
    prune: bool = True,
    secret_scan: bool = True,
    project_folder: str = None,
    create: bool = True,
    pin: bool = True,
) -> SyncResult:
    """Make the native memory directory match recall's distilled knowledge.

    Writes one file per learning/SOP, refreshes the pointer block in
    ``MEMORY.md``, and (when *prune*) removes recall-owned files that no longer
    correspond to anything approved. Never touches a file it does not own.

    *create* controls whether a missing memory directory may be brought into
    existence. Explicit user commands pass ``True``; anything that runs as a
    side effect passes ``False``, so recall can never switch on a Claude Code
    surface the user has not used.
    """
    docs, skipped, target = plan(
        learnings, sops, cwd=cwd, secret_scan=secret_scan,
        project_folder=project_folder, pin=pin,
    )
    result = SyncResult(memory_dir=target, skipped=skipped)

    if not target.is_dir() and not create:
        result.blocked = "memory directory does not exist"
        return result

    wanted_keys = set()
    for doc in docs:
        content = render(doc)
        path = target / doc.filename
        wanted_keys.add(doc.key)
        try:
            current = path.read_text(errors="replace") if path.exists() else None
        except OSError:
            current = None
        if current == content:
            result.unchanged.append(doc.filename)
            continue

        target.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        result.written.append(doc.filename)

    if prune and target.is_dir():
        promoted = {doc.filename for doc in docs}
        for path in sorted(target.glob(f"{FILE_PREFIX}*.md")):
            if path.name in promoted or not is_recall_owned(path):
                continue
            if recall_key_of(path) in wanted_keys:
                continue
            # Never delete another writer's file, or work someone edited here.
            if not is_own_origin(path):
                result.skipped.append({
                    "name": path.name,
                    "reason": "foreign_origin",
                    "detail": "written by another recall installation",
                })
                continue
            if has_local_edits(path):
                result.skipped.append({
                    "name": path.name,
                    "reason": "hand_edited",
                    "detail": "you edited this file; recall will not delete it",
                })
                continue
            path.unlink()
            result.removed.append(path.name)

    # The pointer block reflects only files recall actually owns on disk — a
    # doc skipped because a foreign file squats its name must not be advertised
    # in the index as recall's.
    landed = [doc for doc in docs if is_recall_owned(target / doc.filename)]
    idx = target / INDEX_NAME
    existing = idx.read_text(errors="replace") if idx.exists() else ""

    # Never conjure an index just to say it is empty.
    if not idx.exists() and not landed:
        return result

    updated = render_index(existing, landed, target)
    if updated != existing:
        target.mkdir(parents=True, exist_ok=True)
        idx.write_text(updated)
        result.index_updated = True

    return result


def clear(cwd: str = None, project_folder: str = None) -> SyncResult:
    """Remove every recall-owned memory file and pointer line.

    The inverse of :func:`sync`, for users who want the bridge off without
    hunting through the memory directory by hand.
    """
    return sync([], {}, cwd=cwd, prune=True, project_folder=project_folder,
                create=False)


def status(cwd: str = None, project_folder: str = None) -> dict:
    """Describe the current state of the bridge, for ``recall memory``."""
    target = memory_dir(cwd, project_folder)
    owned = []
    foreign = 0
    if target.is_dir():
        for path in sorted(target.glob("*.md")):
            if path.name == INDEX_NAME:
                continue
            if is_recall_owned(path):
                owned.append(path.name)
            else:
                foreign += 1

    idx = target / INDEX_NAME
    index_text = idx.read_text(errors="replace") if idx.exists() else ""
    pointers = [l for l in index_text.splitlines() if _is_recall_pointer(l, target)]

    return {
        "enabled": is_enabled(),
        "memory_dir": target,
        "memory_dir_exists": target.is_dir(),
        "index_exists": idx.exists(),
        "index_suppressed": index_injection_suppressed(),
        "promoted_files": owned,
        "other_files": foreign,
        "promoted_pointers": len(pointers),
        "platform": detect_platform().value,
    }


def store_env_declaration(cwd: str = None, mount: str = "recall") -> str:
    """Return the ``CLAUDE_MEMORY_STORES`` declaration for this project.

    Printed on request only. recall does not export this: see the module
    docstring for the measured reason.
    """
    import json

    return json.dumps([{
        "path": f"/v1/code/memory/grouping/{mount}",
        "mount": mount,
        "mode": "rw",
        "scope": "team",
        "promptIndex": INDEX_NAME,
    }], separators=(",", ":"))


def promoted_at() -> str:
    """UTC timestamp used when recording promotion time in the recall index."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
