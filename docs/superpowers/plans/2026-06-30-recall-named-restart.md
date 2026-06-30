# Named Restart Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When you restart a recall checkpoint, the new session carries a meaningful name — one you gave at `/recall save <name>` or the `customTitle` your Claude session already had — and `--launch` opens a fresh, clean-context `claude -n "<name>"` process.

**Architecture:** Name capture is a pure scanner (`read_session_title`) over the Claude transcript plus a path finder (`find_current_claude_transcript`). `recall-save.py` resolves the name (explicit → `customTitle` → empty) and passes `--name` down to `recall-restart.py`, which dedups it to a unique lookup token, stores `entry['name']`, and emits `claude -n "<name>"` in the launch command. The `restart`/`load` verb is untouched — all changes live in the backing scripts both verbs route to.

**Tech Stack:** Python 3.8+ stdlib only (json, hashlib, shlex, pathlib, argparse); POSIX `sh` for the `bin/recall` wrapper; pytest with `importlib.util` module loading for hyphenated script filenames.

## Global Constraints

- **Zero new dependencies** — Python 3.8+ stdlib only. No pip installs.
- **Auto-name source is `customTitle` only** — never `aiTitle` (auto-generated) and never codex `agent_nickname` (subagents only). Spec §3.1, §5.
- **Plain (non-`--launch`) restart is unchanged** — it loads into the current session and renames nothing. Native `resume` is untouched. Spec §4.3.
- **Codex has no custom title** — codex `/recall save` keeps the summary-slug name; an explicit `/recall save <name>` is still honored for display/lookup, but no live title is set. Spec §3.4.
- **Display name vs lookup token:** the readable chosen name is passed to `-n`; the lookup token stays slug-based (via existing `entry_session_name()`) and must be unique. Spec §6.
- **Name is shell-escaped safely** in the launch command (names may contain spaces/metacharacters). Spec §4.3, §10.
- Run the full suite (`python3 -m pytest -q`) green after every task. Baseline before starting: **719 passed, 4 skipped**.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `lib/shared.py` | Pure transcript scanner `read_session_title(path)` | Add function |
| `bin/recall-save.py` | Locate current transcript; resolve name; thread `--name` down | Add `find_current_claude_transcript`, `resolve_restart_name`; modify `_latest_claude_session_mtime`, `register_restart`, `save_restart`, `main` |
| `bin/recall-restart.py` | Dedup name to unique token; store `entry['name']`; emit `claude -n` | Add `_resolve_unique_name`; modify `cmd_save`, argparse `save`, `_build_launch_command`; add `import shlex` |
| `bin/recall` | POSIX wrapper — forward `<name>` to `recall-save.py` (currently dropped) | Modify `save)` case |
| `commands/recall.md`, `skills/recall/SKILL.md`, `skills/recall/procedures/save.md` | Document `/recall save <name>` and the named `--launch` | Doc edits |
| `tests/test_shared_io.py`, `tests/test_recall_save.py`, `tests/test_recall_restart.py` | Coverage for the above | Add tests; update `TestCmdSave._make_args` |

Interface call chain (later tasks depend on earlier signatures):

```
bin/recall save <pwd> <name…>
  └─ recall-save.py main(--name)
       └─ save_restart(working_dir, platform, skip_index, name)
            ├─ find_current_claude_transcript(working_dir) -> Optional[Path]   # Task 2
            ├─ resolve_restart_name(explicit, platform, transcript) -> str      # Task 3
            │     └─ lib.shared.read_session_title(path) -> Optional[str]       # Task 1
            └─ register_restart(..., name=resolved) -> str                      # Task 3
                 └─ recall-restart.py save --name <resolved>
                      └─ cmd_save(args.name)
                           ├─ _resolve_unique_name(name, tokens, id) -> str     # Task 4
                           └─ entry['name'] = resolved                          # Task 4
                      └─ _build_launch_command(entry) -> "… | claude -n '<name>'" # Task 5
```

---

### Task 1: `read_session_title()` — pure transcript scanner

**Files:**
- Modify: `lib/shared.py` (add after `load_session_details`, ~line 384, in the "Session detail I/O" section)
- Test: `tests/test_shared_io.py`

**Interfaces:**
- Produces: `read_session_title(transcript_path) -> Optional[str]` — returns the most recent `customTitle` string from a Claude transcript JSONL, or `None` when the file is missing/unreadable/has no custom title.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_shared_io.py`:

```python
# ---------------------------------------------------------------------------
# read_session_title
# ---------------------------------------------------------------------------

from lib.shared import read_session_title


class TestReadSessionTitle:
    def test_returns_latest_custom_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text(
            '{"type":"custom-title","customTitle":"first","sessionId":"a"}\n'
            '{"type":"user","content":"hi"}\n'
            '{"type":"custom-title","customTitle":"second","sessionId":"a"}\n'
        )
        assert read_session_title(t) == "second"

    def test_returns_none_without_custom_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text(
            '{"type":"user","content":"hi"}\n'
            '{"type":"ai-title","aiTitle":"auto-generated"}\n'
        )
        assert read_session_title(t) is None

    def test_ignores_ai_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"ai-title","aiTitle":"do not use"}\n')
        assert read_session_title(t) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        assert read_session_title(tmp_path / "nope.jsonl") is None

    def test_skips_malformed_json_lines(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text('not json at all\n{"type":"custom-title","customTitle":"ok"}\n')
        assert read_session_title(t) == "ok"

    def test_ignores_empty_custom_title(self, tmp_path):
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":""}\n')
        assert read_session_title(t) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_shared_io.py::TestReadSessionTitle -v`
Expected: FAIL — `ImportError: cannot import name 'read_session_title'`

- [ ] **Step 3: Implement `read_session_title`**

In `lib/shared.py`, after `load_session_details` (the end of the "Session detail I/O" section, ~line 384), add:

```python
def read_session_title(transcript_path) -> Optional[str]:
    """Return the most recent user-given ``customTitle`` from a Claude transcript.

    Claude Code transcripts (``~/.claude/projects/<folder>/<uuid>.jsonl``) record a
    ``{"type": "custom-title", "customTitle": "<name>", ...}`` line whenever the user
    names the session. Returns the *last* such title in the file (the current name),
    or ``None`` when the file is missing, unreadable, or has no custom title.
    Auto-generated ``ai-title`` lines are deliberately ignored.
    """
    title = None
    try:
        with open(transcript_path, "r") as handle:
            for raw in handle:
                if '"custom-title"' not in raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "custom-title":
                    custom = obj.get("customTitle")
                    if custom:
                        title = custom
    except (OSError, IOError):
        return None
    return title
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shared_io.py::TestReadSessionTitle -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/shared.py tests/test_shared_io.py
git commit -m "feat(recall): add read_session_title transcript scanner for named restarts"
```

---

### Task 2: `find_current_claude_transcript()` — locate the live transcript

**Files:**
- Modify: `bin/recall-save.py` (`_latest_claude_session_mtime` ~lines 102-124)
- Test: `tests/test_recall_save.py`

**Interfaces:**
- Consumes: `get_project_folders` (already imported in `recall-save.py`).
- Produces: `find_current_claude_transcript(working_dir: str) -> Optional[Path]` — newest non-`agent-` `*.jsonl` across the project's folders, or `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recall_save.py`:

```python
import os


class TestFindCurrentClaudeTranscript:
    def test_returns_newest_non_agent_jsonl(self, tmp_path):
        mod = _import_recall_save()
        proj = tmp_path / ".claude" / "projects" / "myapp"
        proj.mkdir(parents=True)
        old = proj / "old.jsonl"
        new = proj / "new.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("myapp", "myapp")):
            assert mod.find_current_claude_transcript("/tmp/myapp") == new

    def test_excludes_agent_transcripts(self, tmp_path):
        mod = _import_recall_save()
        proj = tmp_path / ".claude" / "projects" / "myapp"
        proj.mkdir(parents=True)
        agent = proj / "agent-sub.jsonl"
        real = proj / "real.jsonl"
        agent.write_text("{}\n")
        real.write_text("{}\n")
        os.utime(agent, (3000, 3000))  # agent is newer but must be skipped
        os.utime(real, (2000, 2000))
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("myapp", "myapp")):
            assert mod.find_current_claude_transcript("/tmp/myapp") == real

    def test_returns_none_when_no_transcripts(self, tmp_path):
        mod = _import_recall_save()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("missing", "missing")):
            assert mod.find_current_claude_transcript("/tmp/missing") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_recall_save.py::TestFindCurrentClaudeTranscript -v`
Expected: FAIL — `AttributeError: module 'recall_save' has no attribute 'find_current_claude_transcript'`

- [ ] **Step 3: Implement and refactor**

In `bin/recall-save.py`, replace `_latest_claude_session_mtime` (~lines 102-124) with the path finder plus a thin mtime wrapper that reuses it:

```python
def find_current_claude_transcript(working_dir: str) -> Optional[Path]:
    """Return the newest non-agent Claude transcript JSONL for *working_dir*.

    A live Claude session writes its JSONL continuously, so the freshest
    non-``agent-`` transcript is the session the user is saving from.
    """
    try:
        folders = set(get_project_folders(working_dir))
    except (OSError, ValueError):
        return None
    newest_path = None
    newest_mtime = None
    for folder in folders:
        if not folder:
            continue
        claude_dir = Path.home() / ".claude" / "projects" / folder
        if not claude_dir.exists():
            continue
        for session_file in claude_dir.glob("*.jsonl"):
            if session_file.name.startswith("agent-"):
                continue
            try:
                mtime = session_file.stat().st_mtime
            except OSError:
                continue
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime
                newest_path = session_file
    return newest_path


def _latest_claude_session_mtime(working_dir: str) -> Optional[float]:
    """mtime of the newest Claude session JSONL for this project, if any."""
    path = find_current_claude_transcript(working_dir)
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass (including the existing mtime/auto-platform tests, unchanged behavior)**

Run: `python3 -m pytest tests/test_recall_save.py -v`
Expected: PASS — new `TestFindCurrentClaudeTranscript` passes and every pre-existing test in the file still passes (the mtime helper is behavior-preserving).

- [ ] **Step 5: Commit**

```bash
git add bin/recall-save.py tests/test_recall_save.py
git commit -m "feat(recall): locate current Claude transcript; reuse for mtime"
```

---

### Task 3: Resolve the name and thread `--name` through save

**Files:**
- Modify: `bin/recall-save.py` (`register_restart` ~lines 355-389; `save_restart` ~lines 448-490; `main` ~lines 493-499; import line ~24-30)
- Test: `tests/test_recall_save.py`

**Interfaces:**
- Consumes: `find_current_claude_transcript` (Task 2), `read_session_title` (Task 1).
- Produces:
  - `resolve_restart_name(explicit_name: str, platform: str, transcript_path: Optional[Path]) -> str`
  - `register_restart(..., resume_checkpoint: str = "", name: str = "") -> str` (new trailing `name` kwarg)
  - `save_restart(working_dir, platform="auto", skip_index=False, name="") -> int` (new trailing `name` kwarg)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recall_save.py`:

```python
class TestResolveRestartName:
    def test_explicit_name_wins(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"from-title"}\n')
        assert mod.resolve_restart_name("explicit", "claude", t) == "explicit"

    def test_uses_custom_title_when_no_explicit(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"from-title"}\n')
        assert mod.resolve_restart_name("", "claude", t) == "from-title"

    def test_empty_when_codex(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"from-title"}\n')
        assert mod.resolve_restart_name("", "codex", t) == ""

    def test_empty_when_no_title_and_no_explicit(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"user","content":"hi"}\n')
        assert mod.resolve_restart_name("", "claude", t) == ""


def test_register_restart_passes_name_when_set(tmp_path):
    mod = _import_recall_save()
    prompt_path = tmp_path / "recall-restarts" / "x.prompt"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("p")
    calls = []

    def fake_run(args, cwd=None, timeout=10):
        calls.append(args)
        return 0, "Saved"

    with mock.patch.object(mod, "get_project_dir", return_value=tmp_path), \
         mock.patch.object(mod, "run_command", side_effect=fake_run):
        mod.register_restart("/tmp/app", "sum", prompt_path, "proj", "sid",
                             name="My Session")
    assert "--name" in calls[0]
    assert "My Session" in calls[0]


def test_register_restart_omits_name_when_empty(tmp_path):
    mod = _import_recall_save()
    prompt_path = tmp_path / "recall-restarts" / "x.prompt"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("p")
    calls = []

    with mock.patch.object(mod, "get_project_dir", return_value=tmp_path), \
         mock.patch.object(mod, "run_command", side_effect=lambda a, cwd=None, timeout=10: (calls.append(a) or (0, "Saved"))):
        mod.register_restart("/tmp/app", "sum", prompt_path, "proj", "sid", name="")
    assert "--name" not in calls[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_recall_save.py::TestResolveRestartName tests/test_recall_save.py::test_register_restart_passes_name_when_set tests/test_recall_save.py::test_register_restart_omits_name_when_empty -v`
Expected: FAIL — `AttributeError: ... 'resolve_restart_name'` and the `name=` kwarg is rejected by `register_restart`.

- [ ] **Step 3a: Add `read_session_title` to the import**

In `bin/recall-save.py`, extend the `from lib.shared import (...)` block (~lines 24-30) to include `read_session_title`:

```python
from lib.shared import (  # noqa: E402
    get_project_dir,
    get_project_folders,
    get_restarts_dir,
    load_index,
    load_session_details,
    read_session_title,
)
```

- [ ] **Step 3b: Add `resolve_restart_name`**

In `bin/recall-save.py`, add above `register_restart` (~line 355):

```python
def resolve_restart_name(explicit_name: str, platform: str, transcript_path: Optional[Path]) -> str:
    """Resolve the restart display name.

    Order: explicit arg → the current Claude session's ``customTitle`` → ""
    (the caller then falls back to the summary slug). Codex sessions have no
    custom title, so only an explicit name applies there.
    """
    if explicit_name:
        return explicit_name
    if platform == "claude" and transcript_path is not None:
        return read_session_title(transcript_path) or ""
    return ""
```

- [ ] **Step 3c: Add the `name` kwarg to `register_restart`**

In `register_restart` (~lines 355-389), change the signature and append the flag:

```python
def register_restart(
    working_dir: str,
    summary: str,
    prompt_path: Path,
    project_folder: str,
    session_id: str,
    platform: str = "codex",
    resume_checkpoint: str = "",
    name: str = "",
) -> str:
```

and after the `resume_checkpoint` block (just before `code, output = run_command(args, ...)`), add:

```python
    if name:
        args.extend(["--name", name])
```

- [ ] **Step 3d: Wire `save_restart` and `main`**

In `save_restart` (~lines 448-490), change the signature to add `name: str = ""`, and after `entry_platform = registration_platform(working_dir, platform)` (~line 471) resolve the name and pass it into `register_restart`:

```python
def save_restart(working_dir: str, platform: str = "auto", skip_index: bool = False, name: str = "") -> int:
```

```python
    entry_platform = registration_platform(working_dir, platform)
    transcript_path = find_current_claude_transcript(working_dir) if entry_platform == "claude" else None
    resolved_name = resolve_restart_name(name, entry_platform, transcript_path)
    resume_checkpoint = cmux_get_resume_checkpoint()
    registration_output = register_restart(
        working_dir,
        summary,
        prompt_path,
        project_folder,
        session_id,
        entry_platform,
        resume_checkpoint=resume_checkpoint,
        name=resolved_name,
    )
```

In `main` (~lines 493-499), add the flag and pass it through:

```python
    parser.add_argument("--name", default="", help="Display name for the restart (auto-filled from session title when omitted)")
```

```python
    return save_restart(args.working_dir, platform=args.platform, skip_index=args.no_index, name=args.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_recall_save.py -v`
Expected: PASS — new tests pass and existing `register_restart`/`save` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add bin/recall-save.py tests/test_recall_save.py
git commit -m "feat(recall): resolve restart name from title and thread --name through save"
```

---

### Task 4: Dedup + store `entry['name']` in `recall-restart.py`

**Files:**
- Modify: `bin/recall-restart.py` (`cmd_save` ~lines 316-381; argparse `save` ~lines 744-758; add `_resolve_unique_name` near `entry_session_name` ~line 104)
- Test: `tests/test_recall_restart.py` (add tests; update `TestCmdSave._make_args` defaults)

**Interfaces:**
- Consumes: `slugify`, `entry_session_name`, `hashlib` (all already present).
- Produces:
  - `_resolve_unique_name(name: str, existing_tokens: set, entry_id) -> str`
  - `cmd_save` reads `args.name` and writes `entry['name']` (a possibly-deduped readable name; `''` when none).
  - `save` subparser accepts `--name` (default `''`).

- [ ] **Step 1: Update `TestCmdSave._make_args` and write the failing tests**

In `tests/test_recall_restart.py`, add `name="",` to the `defaults` dict inside `TestCmdSave._make_args` (~lines 318-331) so existing `cmd_save` tests keep working once `cmd_save` reads `args.name`:

```python
        defaults = dict(
            working_dir="/tmp/myapp",
            summary="fix auth bug",
            prompt_file="",
            role="lead",
            platform="claude-code",
            team="",
            goal="",
            comms_file="",
            session_id="",
            resume_checkpoint="",
            lead_id=None,
            workers=[],
            name="",
        )
```

Then add a new test class:

```python
class TestNamedRestartDedup:
    def _make_args(self, **kwargs):
        defaults = dict(
            working_dir="/tmp/myapp", summary="fix auth bug", prompt_file="",
            role="lead", platform="claude-code", team="", goal="", comms_file="",
            session_id="", resume_checkpoint="", lead_id=None, workers=[], name="",
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_resolve_unique_name_passthrough_when_no_collision(self):
        mod = _import_recall_restart()
        assert mod._resolve_unique_name("Auth Refactor", set(), 7) == "Auth Refactor"

    def test_resolve_unique_name_suffixes_on_collision(self):
        mod = _import_recall_restart()
        existing = {"auth-refactor"}
        result = mod._resolve_unique_name("Auth Refactor", existing, 7)
        assert result != "Auth Refactor"
        assert mod.slugify(result).startswith("auth-refactor-")
        assert mod.slugify(result) not in existing

    def test_explicit_name_is_stored(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda e, pf: saved.extend(e)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(name="My Feature"))
        assert saved[0]["name"] == "My Feature"

    def test_colliding_name_gets_unique_token(self, capsys):
        mod = _import_recall_restart()
        existing = [{"id": 1, "name": "Auth Refactor", "summary": "x"}]
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=existing), \
             mock.patch.object(mod, "save_agents", side_effect=lambda e, pf: saved.extend(e)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(name="auth refactor"))
        new_entry = saved[-1]
        assert mod.entry_session_name(new_entry).startswith("auth-refactor-")
        assert mod.entry_session_name(new_entry) != "auth-refactor"

    def test_no_name_falls_back_to_summary_slug(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda e, pf: saved.extend(e)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(name="", summary="Fix auth bug"))
        assert saved[0].get("name", "") == ""
        assert mod.entry_session_name(saved[0]) == "fix-auth-bug"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_recall_restart.py::TestNamedRestartDedup -v`
Expected: FAIL — `AttributeError: ... '_resolve_unique_name'` / `cmd_save` does not yet read `args.name`.

- [ ] **Step 3a: Add `_resolve_unique_name`**

In `bin/recall-restart.py`, add right after `entry_session_name` (~line 104):

```python
def _resolve_unique_name(name: str, existing_tokens: set, entry_id) -> str:
    """Return a display name whose slug lookup token is unique.

    When ``slugify(name)`` already exists among *existing_tokens*, append a short
    deterministic suffix derived from *entry_id* until the slug is unique, so
    restart-by-name stays unambiguous (design §4.2).
    """
    if slugify(str(name)) not in existing_tokens:
        return str(name)
    digest = hashlib.md5(str(entry_id).encode()).hexdigest()
    for length in range(4, len(digest) + 1):
        candidate = f"{name}-{digest[:length]}"
        if slugify(candidate) not in existing_tokens:
            return candidate
    return f"{name}-{entry_id}"
```

- [ ] **Step 3b: Resolve and store the name in `cmd_save`**

In `cmd_save` (~lines 316-373), after `next_id = max(...) + 1` (~line 326) add:

```python
    # Resolve a unique display name for named restarts (design §4.2, §6)
    resolved_name = args.name or ''
    if resolved_name:
        existing_tokens = {entry_session_name(e) for e in agents}
        resolved_name = _resolve_unique_name(resolved_name, existing_tokens, next_id)
```

and add `'name': resolved_name,` to the `entry` dict (alongside `'summary': summary,`):

```python
    entry = {
        'id': next_id,
        'date': str(date.today()),
        'session_id': session_id,
        'resume_checkpoint': resume_checkpoint,
        'working_directory': working_dir,
        'summary': summary,
        'name': resolved_name,
        'prompt_file': prompt_file,
        'platform': platform,
        'role': role,
        'team': team,
        'goal': goal,
        'comms_file': comms_file,
        'status': 'saved',
        'workers': workers,
        'lead_id': lead_id,
    }
```

- [ ] **Step 3c: Add `--name` to the `save` subparser**

In `main` (~lines 745-758), add to the `save` subparser definition:

```python
    save_parser.add_argument('--name', default='', help='Display name for the restart entry')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_recall_restart.py -v`
Expected: PASS — `TestNamedRestartDedup` passes and all existing `TestCmdSave` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add bin/recall-restart.py tests/test_recall_restart.py
git commit -m "feat(recall): dedup and store named restart entry name"
```

---

### Task 5: Emit `claude -n "<name>"` in the launch command

**Files:**
- Modify: `bin/recall-restart.py` (imports ~line 22; `_build_launch_command` ~lines 237-255)
- Test: `tests/test_recall_restart.py`

**Interfaces:**
- Consumes: `entry['name']` written by Task 4; `shlex` (new import).
- Produces: `_build_launch_command(entry, project_folder)` appends `-n <shlex.quote(name)>` to the `claude` invocation when `entry['name']` is set; unchanged (plain `claude`) when it is not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recall_restart.py`:

```python
import shlex


class TestBuildLaunchCommandName:
    def test_includes_quoted_name_with_spaces(self):
        mod = _import_recall_restart()
        entry = {"name": "Auth Refactor", "working_directory": "/tmp", "prompt_file": ""}
        cmd, _ = mod._build_launch_command(entry, "proj")
        assert f"-n {shlex.quote('Auth Refactor')}" in cmd

    def test_quotes_shell_metacharacters_safely(self):
        mod = _import_recall_restart()
        evil = "a; rm -rf $HOME"
        entry = {"name": evil, "working_directory": "/tmp", "prompt_file": ""}
        cmd, _ = mod._build_launch_command(entry, "proj")
        assert f"-n {shlex.quote(evil)}" in cmd

    def test_no_name_emits_plain_claude(self):
        mod = _import_recall_restart()
        entry = {"working_directory": "/tmp", "prompt_file": "", "summary": "do work"}
        cmd, _ = mod._build_launch_command(entry, "proj")
        assert "-n " not in cmd
        assert "| claude" in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_recall_restart.py::TestBuildLaunchCommandName -v`
Expected: FAIL — `test_includes_quoted_name_with_spaces` / `test_quotes_shell_metacharacters_safely` assert a `-n` segment that is not yet emitted.

- [ ] **Step 3: Implement**

In `bin/recall-restart.py`, add `import shlex` to the import block (~line 22, near `import subprocess`). Then in `_build_launch_command` (~lines 249-253), replace the final `if prompt_path: … else: …` block with:

```python
    name = entry.get('name', '')
    claude_cmd = "claude"
    if name:
        claude_cmd = f"claude -n {shlex.quote(name)}"

    if prompt_path:
        parts.append(f"cat '{prompt_path}' | {claude_cmd}")
    else:
        summary = entry.get('summary', 'Restart session')
        parts.append(f"echo '{summary}' | {claude_cmd}")

    return ' && '.join(parts), prompt_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_recall_restart.py -v`
Expected: PASS — `TestBuildLaunchCommandName` passes; existing launch/match tests still pass.

- [ ] **Step 5: Commit**

```bash
git add bin/recall-restart.py tests/test_recall_restart.py
git commit -m "feat(recall): launch named restart via claude -n with safe quoting"
```

---

### Task 6: Thread `<name>` through the `bin/recall` wrapper

**Files:**
- Modify: `bin/recall` (`save)` case ~lines 28-30)

**Interfaces:**
- Consumes: `recall-save.py --name` (Task 3).
- Produces: `bin/recall <pwd> save <name…>` forwards the joined name as `--name`. `bin/recall <pwd> save` (no name) is unchanged.

> No pytest harness exists for the POSIX wrapper; this task is verified by a syntax check, a grep, and the end-to-end smoke test in Final Verification.

- [ ] **Step 1: Implement**

In `bin/recall`, replace the `save)` case (lines 28-30):

```sh
  save)
    shift || true
    if [ "$#" -ge 1 ]; then
      exec python3 "$ROOT/bin/recall-save.py" "$CWD_ARG" --name "$*"
    fi
    exec python3 "$ROOT/bin/recall-save.py" "$CWD_ARG"
    ;;
```

- [ ] **Step 2: Verify wrapper syntax and dispatch**

Run:
```bash
sh -n bin/recall && echo "syntax ok"
grep -n -- '--name' bin/recall
```
Expected: `syntax ok`, and the grep shows the new `--name "$*"` line inside the `save)` case.

- [ ] **Step 3: Confirm the Python suite is unaffected**

Run: `python3 -m pytest -q`
Expected: PASS (all previously-passing tests still green; the wrapper change touches no Python).

- [ ] **Step 4: Commit**

```bash
git add bin/recall
git commit -m "feat(recall): forward /recall save <name> through the wrapper"
```

---

### Task 7: Document `/recall save <name>` and the named `--launch`

**Files:**
- Modify: `commands/recall.md` (~line 16); `skills/recall/SKILL.md` (command table); `skills/recall/procedures/save.md` (header note)

- [ ] **Step 1: Update `commands/recall.md`**

Replace the `/recall save` bullet (line 16) and adjust the `--launch` bullet (line 18):

```markdown
- `/recall save [name]` — checkpoint current work; names the restart (falls back to the Claude session title, then a summary slug)
```

and

```markdown
- `/recall restart --launch <n|name|text>` — open a checkpoint in a separate window as a fresh, named `claude` session
```

- [ ] **Step 2: Update `skills/recall/SKILL.md`**

In the command table, change the `/recall save` row to document the optional name, e.g.:

```markdown
| `/recall save [name]` | Distill current session into a restart prompt; names it (explicit name → session title → summary slug) |
```

- [ ] **Step 3: Update `skills/recall/procedures/save.md`**

Add a one-line note under the title that an optional name may be passed:

```markdown
`/recall save <name>` records `<name>` as the restart's name (used in the prompt box, `/resume` picker, and terminal title on `--launch`). With no argument, the name is taken from the Claude session's title, then a summary slug.
```

- [ ] **Step 4: Verify the docs mention the feature**

Run: `grep -rn "save \[name\]\|save <name>" commands/recall.md skills/recall/`
Expected: matches in all three files.

- [ ] **Step 5: Commit**

```bash
git add commands/recall.md skills/recall/SKILL.md skills/recall/procedures/save.md
git commit -m "docs(recall): document /recall save <name> and named --launch"
```

---

## Final Verification

- [ ] **Full suite green**

Run: `python3 -m pytest -q`
Expected: all previously-passing tests plus the new ones pass (baseline was 719 passed, 4 skipped; expect ~24 new tests).

- [ ] **End-to-end smoke (manual, in a real Claude project)**

```bash
# From a Claude Code project directory with at least one indexed session:
bin/recall "$PWD" save my-feature-x
bin/recall "$PWD" restart            # the entry lists under the name "my-feature-x"
```
Expected: the saved entry shows the name `my-feature-x`; `agents.json` for the project contains `"name": "my-feature-x"`.

- [ ] **Launch command shape (manual)**

```bash
python3 - <<'PY'
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("rr", "bin/recall-restart.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._build_launch_command({"name": "Auth Refactor", "working_directory": "/tmp", "prompt_file": ""}, "proj")[0])
PY
```
Expected output contains: `echo 'Restart session' | claude -n 'Auth Refactor'`

## Notes / Out of scope

- Version bump (→ **3.3.0**), tagging, and the go-public secret scan belong to the release stage, not this feature plan.
- Scope 2 (RAG/embeddings restart-context reconstruction), the `restart → load` grammar rename, same-window clean restart, and the SessionStart `sessionTitle` hook are explicitly out of scope (design §9, §10).
- Optional, deferred: feed the resolved name into the cmux surface (`"Recall: {name}"`) in `cmux_register_recall` (design §7 optional touch).
