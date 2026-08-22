#!/usr/bin/env python3
"""Tests for lib/native_memory.py — the Claude Code auto-memory bridge."""

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import native_memory as nm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _learning(title="Use uv not pip", description="pip install fails in this repo",
              fix="Run `uv pip install`", category="python_error", source="failure"):
    return {
        "title": title,
        "description": description,
        "fix": fix,
        "category": category,
        "source": source,
    }


@pytest.fixture
def memdir(tmp_path, monkeypatch):
    """Point the bridge at a throwaway memory directory."""
    target = tmp_path / "memory"
    monkeypatch.setattr(nm, "memory_dir", lambda *a, **kw: target)
    return target


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def test_disabled_by_env_flag(monkeypatch):
    monkeypatch.setenv("RECALL_NATIVE_MEMORY", "0")
    assert nm.is_enabled() is False


def test_disabled_for_codex_agent(monkeypatch):
    monkeypatch.delenv("RECALL_NATIVE_MEMORY", raising=False)
    monkeypatch.setenv("RECALL_AGENT", "codex")
    assert nm.is_enabled() is False


def test_disabled_when_auto_memory_off(monkeypatch):
    monkeypatch.delenv("RECALL_NATIVE_MEMORY", raising=False)
    monkeypatch.delenv("RECALL_AGENT", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")
    assert nm.is_enabled() is False


def test_enabled_for_plain_shell(monkeypatch):
    """An undetected platform is a shell running `recall` directly — allowed."""
    for var in ("RECALL_NATIVE_MEMORY", "RECALL_AGENT",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CODEX_VERSION"):
        monkeypatch.delenv(var, raising=False)
    assert nm.is_enabled() is True


def test_index_injection_suppressed_by_store_declaration(monkeypatch):
    """Declaring a memory store turns off MEMORY.md inlining — measured on 2.1.229."""
    monkeypatch.delenv("CLAUDE_MEMORY_STORES", raising=False)
    assert nm.index_injection_suppressed() is False
    monkeypatch.setenv("CLAUDE_MEMORY_STORES", '[{"path":"/v1/code/memory/x"}]')
    assert nm.index_injection_suppressed() is True


# ---------------------------------------------------------------------------
# The autoMemoryEnabled settings gate
#
# The product's /memory toggle writes autoMemoryEnabled into settings with no
# env var set. Missing that key meant recall promoted into a directory the user
# told Claude Code not to read — silent data loss in shipped code. These tests
# are the merge gate for the fix; the precedence one is the trap.
# ---------------------------------------------------------------------------

import json as _json


def _clear_memory_env(monkeypatch):
    for var in ("RECALL_NATIVE_MEMORY", "RECALL_AGENT",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_SIMPLE",
                "CODEX_VERSION", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(var, raising=False)


def _write_user_setting(config_dir, **keys):
    (config_dir / "settings.json").write_text(_json.dumps(keys))


def test_settings_toggle_off_disables_promotion(monkeypatch, isolate_claude_config_dir):
    """The actual bug: toggle off in settings, no env var, must disable."""
    _clear_memory_env(monkeypatch)
    _write_user_setting(isolate_claude_config_dir, autoMemoryEnabled=False)
    assert nm.is_enabled() is False


def test_force_enable_env_wins_over_settings_toggle(monkeypatch, isolate_claude_config_dir):
    """THE TRAP. `=0` is an explicit force-enable that must beat autoMemoryEnabled:false.

    A naive "read the setting and return it" inverts the original bug onto every
    user who opted back in via the env var. This is why the fix ships with a test.
    """
    _clear_memory_env(monkeypatch)
    _write_user_setting(isolate_claude_config_dir, autoMemoryEnabled=False)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "0")
    assert nm.is_enabled() is True


def test_explicit_env_disable_still_wins(monkeypatch, isolate_claude_config_dir):
    """Regression guard: the pre-existing env disable must keep working."""
    _clear_memory_env(monkeypatch)
    _write_user_setting(isolate_claude_config_dir, autoMemoryEnabled=True)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")
    assert nm.is_enabled() is False


def test_absent_setting_defaults_to_enabled(monkeypatch, isolate_claude_config_dir):
    """No env var, no settings key — Claude Code's default is on, so is recall's."""
    _clear_memory_env(monkeypatch)
    assert nm.auto_memory_setting() is None
    assert nm.is_enabled() is True


def test_project_scope_overrides_user_scope(monkeypatch, isolate_claude_config_dir, tmp_path):
    """The sweep confirmed project scope IS honored for this key — closest wins."""
    _clear_memory_env(monkeypatch)
    _write_user_setting(isolate_claude_config_dir, autoMemoryEnabled=True)
    proj = tmp_path / "repo"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(_json.dumps({"autoMemoryEnabled": False}))

    assert nm.auto_memory_setting(str(proj)) is False
    assert nm.is_enabled(str(proj)) is False


def test_project_local_overrides_project(monkeypatch, isolate_claude_config_dir, tmp_path):
    """settings.local.json is the closest scope and wins over settings.json."""
    _clear_memory_env(monkeypatch)
    proj = tmp_path / "repo"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(_json.dumps({"autoMemoryEnabled": False}))
    (proj / ".claude" / "settings.local.json").write_text(_json.dumps({"autoMemoryEnabled": True}))

    assert nm.auto_memory_setting(str(proj)) is True


def test_setting_is_read_from_claude_config_dir(monkeypatch, isolate_claude_config_dir):
    """CLAUDE_CONFIG_DIR relocates the whole tree; the setting must follow it."""
    _clear_memory_env(monkeypatch)
    _write_user_setting(isolate_claude_config_dir, autoMemoryEnabled=False)
    # The isolated config dir IS the CLAUDE_CONFIG_DIR the fixture set.
    assert nm.auto_memory_setting() is False


def test_corrupt_settings_file_is_ignored(monkeypatch, isolate_claude_config_dir):
    """A half-written settings.json must not crash the gate — treat as unset."""
    _clear_memory_env(monkeypatch)
    (isolate_claude_config_dir / "settings.json").write_text("{not valid json")
    assert nm.auto_memory_setting() is None
    assert nm.is_enabled() is True


def test_claude_code_simple_disables(monkeypatch, isolate_claude_config_dir):
    """CLAUDE_CODE_SIMPLE strips the system prompt; auto-memory is off there."""
    _clear_memory_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_SIMPLE", "1")
    assert nm.is_enabled() is False


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def test_memory_project_folder_prefers_existing_memory_dir(tmp_path, isolate_claude_config_dir):
    real = tmp_path / "real-project"
    real.mkdir()
    slug = str(real.resolve()).replace("/", "-")
    (isolate_claude_config_dir / "projects" / slug / "memory").mkdir(parents=True)

    assert nm.memory_project_folder(str(real)) == slug


def test_memory_dir_ends_in_memory():
    assert nm.memory_dir("/some/project").name == "memory"


def test_memory_dir_honours_claude_config_dir(isolate_claude_config_dir):
    """Claude Code relocates its whole tree with CLAUDE_CONFIG_DIR; so do we."""
    resolved = nm.memory_dir("/some/project")
    assert str(resolved).startswith(str(isolate_claude_config_dir))


def test_memory_dir_targets_the_named_project_not_the_cwd(isolate_claude_config_dir):
    """Approving learnings for one project must not write into another's memory."""
    a = nm.memory_dir("/projects/alpha")
    b = nm.memory_dir("/projects/beta")
    assert a != b
    assert "-projects-alpha" in str(a)
    assert "-projects-beta" in str(b)


def test_explicit_project_folder_wins_over_cwd():
    resolved = nm.memory_dir("/projects/alpha", project_folder="-explicit-slug")
    assert resolved.parent.name == "-explicit-slug"


# ---------------------------------------------------------------------------
# Rendering and parsing
# ---------------------------------------------------------------------------

def test_render_roundtrips_through_parser():
    doc = nm.learning_to_doc(_learning())
    parsed = nm.parse_frontmatter(nm.render(doc))

    assert parsed["name"] == doc.name
    assert parsed["metadata"]["type"] == "feedback"
    assert parsed["metadata"]["source"] == "recall"
    assert parsed["metadata"]["recall_key"] == doc.key


def test_learning_body_uses_documented_convention():
    body = nm.render(nm.learning_to_doc(_learning()))
    assert "**Why:**" in body
    assert "**How to apply:** Run `uv pip install`" in body


def test_description_with_colon_is_quoted():
    doc = nm.learning_to_doc(_learning(description="note: this breaks"))
    parsed = nm.parse_frontmatter(nm.render(doc))
    assert parsed["description"] == "note: this breaks"


def test_parse_frontmatter_ignores_body_lines():
    text = "---\nname: a\nmetadata:\n  source: recall\n---\n\nname: not-frontmatter\n"
    parsed = nm.parse_frontmatter(text)
    assert parsed["name"] == "a"
    assert parsed["metadata"]["source"] == "recall"


# ---------------------------------------------------------------------------
# Promotion quality gate
# ---------------------------------------------------------------------------

class TestPromotionGate:
    """MEMORY.md loads into every session, so only durable guidance gets in."""

    def test_durable_learning_is_promotable(self):
        ok, _ = nm.is_promotable(_learning())
        assert ok

    def test_failure_streak_is_rejected(self):
        streak = {
            "title": "Recurring general errors (3x in session)",
            "description": "Hit 3 general errors. Example: `pytest -q`",
            "solution": "Error pattern: assertion failed somewhere",
            "source": "repeated_pattern",
        }
        ok, reason = nm.is_promotable(streak)
        assert not ok
        assert "failure streak" in reason

    def test_command_substitution_template_is_rejected(self):
        auto = _learning(
            title="Fix for cd failure",
            description="Command `cd /tmp && ls` failed with: No such file",
            fix="Use instead: `cd /tmp; ls`",
            source="failure_resolution",
        )
        ok, reason = nm.is_promotable(auto)
        assert not ok
        assert "one session" in reason

    def test_learning_without_a_fix_is_rejected(self):
        ok, reason = nm.is_promotable(_learning(fix=""))
        assert not ok
        assert "actionable" in reason

    def test_rejected_learnings_never_reach_disk(self, memdir):
        auto = _learning(title="Fix for ls failure", fix="Use instead: `ls -la`")
        result = nm.sync([auto], {})

        assert result.written == []
        assert not list(memdir.glob("recall-learning-*.md"))
        assert result.skipped[0]["reason"] == "not_durable"

    def test_rejections_are_reported_not_silent(self):
        _, rejected = nm.partition_learnings([_learning(fix="")])
        assert len(rejected) == 1
        learning, reason = rejected[0]
        assert learning["title"] == "Use uv not pip"
        assert reason


# ---------------------------------------------------------------------------
# Pointer text
# ---------------------------------------------------------------------------

def test_pointer_uses_the_real_title():
    doc = nm.learning_to_doc(_learning(title="Use uv for installs"))
    line = nm.render_index("", [doc]).splitlines()[-1]
    assert line.startswith("- [Use uv for installs](")


def test_pointer_hook_prefers_the_fix_over_a_command_echo():
    """A transcript of the failing command tells a future session nothing."""
    doc = nm.learning_to_doc(_learning(
        description="Command `pip install x` failed with: SSLError(...)",
        fix="Run `uv pip install` behind the proxy",
    ))
    assert "uv pip install" in doc.description
    assert "failed with" not in doc.description


# ---------------------------------------------------------------------------
# SOPs
# ---------------------------------------------------------------------------

def test_normalize_sops_unwraps_the_file_shape():
    """lib.sops.load_sops() returns {"version": 1, "sops": {...}}."""
    wrapped = {"version": 1, "sops": {"aws": {"description": "d"}}}
    assert nm.normalize_sops(wrapped) == {"aws": {"description": "d"}}


def test_sop_doc_uses_real_sop_keys():
    doc = nm.sop_to_doc("aws-profile", {
        "description": "Use the kare-dev-admin profile",
        "patterns": ["ExpiredToken", "AccessDenied"],
        "fixes": ["export AWS_PROFILE=kare-dev-admin"],
        "examples": {"bad": "aws s3 ls", "good": "AWS_PROFILE=kare-dev-admin aws s3 ls"},
    })
    body = nm.render(doc)

    assert doc.type == "reference"
    assert "`ExpiredToken`" in body and "`AccessDenied`" in body
    assert "export AWS_PROFILE=kare-dev-admin" in body
    assert "Prefer:" in body


def test_sops_are_promoted_without_the_learning_gate(memdir):
    """SOPs are hand-authored, so they do not need to earn their way in."""
    result = nm.sync([], {"version": 1, "sops": {"aws": {"description": "use profile"}}}, pin=False)
    assert len(result.written) == 1
    assert result.written[0].startswith("recall-sop-")


# ---------------------------------------------------------------------------
# Regressions found in review
# ---------------------------------------------------------------------------

class TestReviewRegressions:
    """Each of these is a defect a reviewer found in the first cut."""

    def test_flow_style_frontmatter_does_not_crash_ownership_check(self, tmp_path):
        """`metadata: {source: recall}` is valid YAML the parser doesn't read.

        It must be treated as absent, not stored as a string — is_recall_owned
        used to raise AttributeError calling .get() on it.
        """
        path = tmp_path / "recall-flow.md"
        path.write_text("---\nname: x\nmetadata: {source: recall}\n---\n\nbody\n")
        assert nm.is_recall_owned(path) is False
        assert nm.recall_key_of(path) is None

    def test_sops_survive_a_flood_of_learnings(self, memdir):
        """Hand-authored SOPs must not be evicted by auto-extracted learnings."""
        many = [_learning(title=f"Learning number {i}")
                for i in range(nm.MAX_PROMOTED_POINTERS + 5)]
        docs = nm.build_docs(many, {"critical-sop": {"description": "hand written"}})

        assert any(d.name.startswith("recall-sop-") for d in docs)
        assert len(docs) <= nm.MAX_PROMOTED_POINTERS

    def test_over_cap_learnings_are_reported(self, memdir):
        many = [_learning(title=f"Learning number {i}")
                for i in range(nm.MAX_PROMOTED_POINTERS + 3)]
        result = nm.sync(many, {})
        assert any(s["reason"] == "over_cap" for s in result.skipped)

    def test_no_pointer_to_a_foreign_file_on_name_collision(self, memdir):
        """Refusing to overwrite is not enough — we must not claim it either."""
        doc = nm.learning_to_doc(_learning())
        memdir.mkdir(parents=True)
        (memdir / doc.filename).write_text("hand written, not recall's\n")

        nm.sync([_learning()], {})

        index = (memdir / nm.INDEX_NAME).read_text() if (memdir / nm.INDEX_NAME).exists() else ""
        assert doc.filename not in index

    def test_foreign_recall_prefixed_pointer_survives(self, memdir):
        """A user's own recall-notes.md keeps its index line through clear()."""
        memdir.mkdir(parents=True)
        (memdir / "recall-notes.md").write_text(
            "---\nname: recall-notes\nmetadata:\n  type: user\n---\n\nmine\n")
        (memdir / nm.INDEX_NAME).write_text(
            "# Memory Index\n\n- [My Notes](recall-notes.md) — mine, keep\n")

        nm.clear()

        index = (memdir / nm.INDEX_NAME).read_text()
        assert "- [My Notes](recall-notes.md) — mine, keep" in index
        assert (memdir / "recall-notes.md").exists()

    def test_orphaned_recall_pointer_is_still_pruned(self, memdir):
        """A dangling pointer to a file recall removed must not linger."""
        memdir.mkdir(parents=True)
        (memdir / nm.INDEX_NAME).write_text(
            "# Memory Index\n\n- [Gone](recall-learning-gone.md) — stale\n")

        nm.clear()

        assert "recall-learning-gone.md" not in (memdir / nm.INDEX_NAME).read_text()

    def test_sync_does_not_create_the_memory_dir_when_create_false(self, memdir):
        """Side-effect promotion must never switch on a surface the user hasn't used."""
        result = nm.sync([_learning()], {}, create=False)

        assert not memdir.exists()
        assert result.blocked
        assert result.written == []

    def test_zero_promotion_does_not_conjure_an_index(self, memdir):
        """A sync that promotes nothing should not author an empty MEMORY.md."""
        nm.sync([_learning(fix="Use instead: `ls`")], {})
        assert not (memdir / nm.INDEX_NAME).exists()

    def test_dry_run_plan_matches_what_sync_writes(self, memdir):
        """A dry run that overcounts is worse than no dry run."""
        learnings = [
            _learning(title="Good one"),
            _learning(title="Leaky", fix="export KEY=AKIAIOSFODNN7EXAMPLE"),
            _learning(title="Auto", fix="Use instead: `ls`"),
        ]
        planned, skipped, _ = nm.plan(learnings, {})
        result = nm.sync(learnings, {})

        assert {d.filename for d in planned} == set(result.written)
        assert len(skipped) == len(result.skipped)


class TestAutoPromoteOptIn:
    """Writing into Claude Code's config tree is opt-in, never a side effect."""

    def test_off_by_default(self):
        assert nm.auto_promote_enabled({}) is False
        assert nm.auto_promote_enabled(None) is False

    def test_on_when_the_project_opted_in(self):
        index = {"settings": {nm.AUTO_PROMOTE_SETTING: True}}
        assert nm.auto_promote_enabled(index) is True


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_is_recall_owned_requires_prefix_and_marker(tmp_path):
    owned = tmp_path / "recall-learning-x.md"
    owned.write_text(nm.render(nm.learning_to_doc(_learning())))
    assert nm.is_recall_owned(owned)

    impostor = tmp_path / "recall-notes.md"
    impostor.write_text("---\nname: recall-notes\nmetadata:\n  type: user\n---\n\nmine\n")
    assert not nm.is_recall_owned(impostor)

    unprefixed = tmp_path / "my-note.md"
    unprefixed.write_text(nm.render(nm.learning_to_doc(_learning())))
    assert not nm.is_recall_owned(unprefixed)


def test_sync_refuses_to_overwrite_foreign_file(memdir):
    doc = nm.learning_to_doc(_learning())
    memdir.mkdir(parents=True)
    victim = memdir / doc.filename
    victim.write_text("hand written, not recall's\n")

    result = nm.sync([_learning()], {})

    assert victim.read_text() == "hand written, not recall's\n"
    assert result.skipped[0]["reason"] == "not_recall_owned"
    assert doc.filename not in result.written


# ---------------------------------------------------------------------------
# Index handling
# ---------------------------------------------------------------------------

def test_render_index_preserves_foreign_lines():
    existing = (
        "# Memory Index\n"
        "\n"
        "- [Mine](my-note.md) — something I wrote\n"
        "- [Stale](recall-learning-old.md) — recall's old pointer\n"
    )
    docs = [nm.learning_to_doc(_learning())]
    updated = nm.render_index(existing, docs)

    assert "- [Mine](my-note.md) — something I wrote" in updated
    assert "recall-learning-old.md" not in updated
    assert docs[0].filename in updated


def test_render_index_creates_header_when_absent():
    updated = nm.render_index("", [nm.learning_to_doc(_learning())])
    assert updated.startswith(nm.INDEX_HEADER)


def test_render_index_is_stable_across_reruns():
    docs = [nm.learning_to_doc(_learning())]
    once = nm.render_index("", docs)
    twice = nm.render_index(once, docs)
    assert once == twice


# ---------------------------------------------------------------------------
# Sync behaviour
# ---------------------------------------------------------------------------

def test_sync_writes_files_and_index(memdir):
    result = nm.sync([_learning()], {"aws": {"description": "d", "fix": "f"}}, pin=False)

    assert result.index_updated
    assert len(result.written) == 2
    index = (memdir / nm.INDEX_NAME).read_text()
    for name in result.written:
        assert (memdir / name).exists()
        assert name in index


def test_sync_is_idempotent(memdir):
    nm.sync([_learning()], {}, pin=False)
    second = nm.sync([_learning()], {}, pin=False)

    assert second.written == []
    assert second.index_updated is False
    assert len(second.unchanged) == 1


def test_sync_prunes_revoked_learnings(memdir):
    first = nm.sync([_learning(title="A"), _learning(title="B")], {}, pin=False)
    assert len(first.written) == 2

    second = nm.sync([_learning(title="A")], {}, pin=False)

    assert len(second.removed) == 1
    assert "b" in second.removed[0].lower()
    assert "recall-learning-b.md" not in (memdir / nm.INDEX_NAME).read_text()


def test_sync_skips_content_with_secrets(memdir):
    leaky = _learning(fix="export AWS_KEY=AKIAIOSFODNN7EXAMPLE")
    result = nm.sync([leaky], {})

    assert result.written == []
    assert result.skipped[0]["reason"] == "secret_scan"
    assert not list(memdir.glob("recall-*.md"))


def test_sync_does_not_prune_foreign_files(memdir):
    memdir.mkdir(parents=True)
    keeper = memdir / "recall-notes.md"
    keeper.write_text("---\nname: recall-notes\nmetadata:\n  type: user\n---\n\nmine\n")

    nm.sync([], {})

    assert keeper.exists()


def test_clear_removes_only_recall_files(memdir):
    nm.sync([_learning()], {}, pin=False)
    memdir_file = memdir / "user-note.md"
    memdir_file.write_text("---\nname: user-note\n---\n\nkeep me\n")
    (memdir / nm.INDEX_NAME).write_text(
        (memdir / nm.INDEX_NAME).read_text() + "- [Mine](user-note.md) — keep\n"
    )

    result = nm.clear()

    assert len(result.removed) == 1
    assert memdir_file.exists()
    index = (memdir / nm.INDEX_NAME).read_text()
    assert "- [Mine](user-note.md) — keep" in index
    assert "recall-learning" not in index


def test_pointer_cap_protects_the_index(memdir):
    many = [_learning(title=f"Learning number {i}") for i in range(nm.MAX_PROMOTED_POINTERS + 10)]
    result = nm.sync(many, {}, pin=False)
    assert len(result.written) == nm.MAX_PROMOTED_POINTERS


def test_colliding_titles_keep_separate_files():
    a = _learning(title="Same Title", description="first cause")
    b = _learning(title="Same Title", description="second cause")
    docs = nm.build_docs([a, b], {})

    assert len({d.name for d in docs}) == 2
    assert len({d.key for d in docs}) == 2


def test_store_env_declaration_shape():
    import json

    parsed = json.loads(nm.store_env_declaration(mount="recall"))
    assert parsed[0]["mount"] == "recall"
    assert parsed[0]["promptIndex"] == nm.INDEX_NAME
    # Mount names must match Claude Code's /^[A-Za-z0-9_-]+$/.
    assert parsed[0]["mount"].replace("_", "").replace("-", "").isalnum()


# ---------------------------------------------------------------------------
# Prune safety: origin and content hash
# ---------------------------------------------------------------------------

class TestPruneGuards:
    """Prune deletes files. Deleting another writer's file, or work someone
    edited by hand, is the failure mode that matters."""

    def test_render_records_origin_and_hash(self):
        parsed = nm.parse_frontmatter(nm.render(nm.learning_to_doc(_learning())))
        assert parsed["metadata"]["origin"] == nm.install_id()
        assert parsed["metadata"]["content_sha256"]

    def test_render_is_deterministic(self):
        """No timestamps: identical input must produce a byte-identical file,
        so sync skips the write and the file's mtime never moves."""
        doc = nm.learning_to_doc(_learning())
        assert nm.render(doc) == nm.render(doc)

    def test_foreign_origin_file_is_not_pruned(self, memdir):
        memdir.mkdir(parents=True)
        foreign = memdir / "recall-learning-someone-elses.md"
        foreign.write_text(
            "---\nname: recall-learning-someone-elses\nmetadata:\n"
            "  source: recall\n  origin: deadbeefdeadbeef\n  recall_key: learning:x\n"
            "---\n\ntheirs\n")

        result = nm.sync([], {})

        assert foreign.exists()
        assert any(s["reason"] == "foreign_origin" for s in result.skipped)

    def test_own_origin_file_is_pruned(self, memdir):
        nm.sync([_learning()], {}, pin=False)
        assert list(memdir.glob("recall-learning-*.md"))

        nm.sync([], {})
        assert not list(memdir.glob("recall-learning-*.md"))

    def test_hand_edited_file_is_not_overwritten(self, memdir):
        nm.sync([_learning()], {}, pin=False)
        path = next(memdir.glob("recall-learning-*.md"))
        edited = path.read_text() + "\nMy own note appended here.\n"
        path.write_text(edited)

        result = nm.sync([_learning()], {})

        assert path.read_text() == edited
        assert any(s["reason"] == "hand_edited" for s in result.skipped)

    def test_hand_edited_file_is_not_pruned(self, memdir):
        nm.sync([_learning()], {}, pin=False)
        path = next(memdir.glob("recall-learning-*.md"))
        path.write_text(path.read_text() + "\nMine.\n")

        result = nm.sync([], {})

        assert path.exists()
        assert any(s["reason"] == "hand_edited" for s in result.skipped)

    def test_untouched_file_is_still_considered_unchanged(self, memdir):
        nm.sync([_learning()], {}, pin=False)
        second = nm.sync([_learning()], {}, pin=False)
        assert second.written == []
        assert len(second.unchanged) == 1


# ---------------------------------------------------------------------------
# The pinned project playbook
# ---------------------------------------------------------------------------

def _pinned_foreign(memdir, name, pinned=True):
    memdir.mkdir(parents=True, exist_ok=True)
    (memdir / name).write_text(
        f"---\nname: {name[:-3]}\nmetadata:\n  type: project\n"
        f"  pinned: {'true' if pinned else 'false'}\n---\n\ntheirs\n")


class TestPinnedPlaybook:
    """Claude Code injects the full body of up to 4 pinned memories into every
    session, newest-mtime first. recall claims at most one of those slots."""

    def test_playbook_is_written_and_pinned(self, memdir):
        result = nm.sync([_learning()], {})

        assert f"{nm.PLAYBOOK_NAME}.md" in result.written
        text = (memdir / f"{nm.PLAYBOOK_NAME}.md").read_text()
        assert nm.parse_frontmatter(text)["metadata"]["pinned"] == "true"

    def test_playbook_carries_the_actionable_line(self, memdir):
        nm.sync([_learning()], {})
        body = (memdir / f"{nm.PLAYBOOK_NAME}.md").read_text()
        assert "Use uv not pip" in body
        assert "Run `uv pip install`" in body

    def test_only_one_pinned_file_is_ever_written(self, memdir):
        nm.sync([_learning(title=f"A"), _learning(title="B")], {})

        pinned = [p for p in memdir.glob("recall-*.md")
                  if nm.parse_frontmatter(p.read_text()).get("metadata", {}).get("pinned") == "true"]
        assert len(pinned) == 1

    def test_no_playbook_when_nothing_is_promoted(self, memdir):
        nm.sync([_learning(fix="Use instead: `ls`")], {})
        assert not (memdir / f"{nm.PLAYBOOK_NAME}.md").exists()

    def test_refuses_to_pin_when_the_user_has_spent_the_budget(self, memdir):
        for i in range(nm.MAX_PINS):
            _pinned_foreign(memdir, f"mine-{i}.md")

        result = nm.sync([_learning()], {})

        assert not (memdir / f"{nm.PLAYBOOK_NAME}.md").exists()
        assert any(s["reason"] == "pin_budget" for s in result.skipped)

    def test_pins_when_the_user_has_a_slot_free(self, memdir):
        for i in range(nm.MAX_PINS - 1):
            _pinned_foreign(memdir, f"mine-{i}.md")

        nm.sync([_learning()], {})

        assert (memdir / f"{nm.PLAYBOOK_NAME}.md").exists()

    def test_unpinned_user_files_do_not_count_against_the_budget(self, memdir):
        for i in range(nm.MAX_PINS + 2):
            _pinned_foreign(memdir, f"mine-{i}.md", pinned=False)

        nm.sync([_learning()], {})

        assert (memdir / f"{nm.PLAYBOOK_NAME}.md").exists()

    def test_playbook_mtime_does_not_move_on_a_no_op_sync(self, memdir):
        """The recency ordering is by mtime — a playbook that rewrote itself
        every sync would float up and evict the user's own pins."""
        nm.sync([_learning()], {})
        path = memdir / f"{nm.PLAYBOOK_NAME}.md"
        before = path.stat().st_mtime_ns

        nm.sync([_learning()], {})

        assert path.stat().st_mtime_ns == before

    def test_playbook_is_pruned_when_everything_is_revoked(self, memdir):
        nm.sync([_learning()], {})
        assert (memdir / f"{nm.PLAYBOOK_NAME}.md").exists()

        nm.sync([], {})

        assert not (memdir / f"{nm.PLAYBOOK_NAME}.md").exists()

    def test_sop_fixes_reach_the_playbook(self, memdir):
        """SOPs render **Fix:** as a header with bullets; the playbook must
        still carry the instruction, not just the SOP's title."""
        nm.sync([], {"version": 1, "sops": {"pytest": {
            "description": "Run the suite the fast way",
            "fixes": ["python3 -m pytest tests/ -q"],
        }}})

        body = (memdir / f"{nm.PLAYBOOK_NAME}.md").read_text()
        assert "python3 -m pytest tests/ -q" in body
