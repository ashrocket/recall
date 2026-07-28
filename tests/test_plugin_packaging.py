import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_manifest_exposes_recall_skill():
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())

    claude_manifest = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text()
    )

    assert manifest["name"] == "recall"
    assert manifest["version"] == claude_manifest["version"]
    assert manifest["version"] == "3.4.2"
    assert manifest["skills"] == "./skills/"

    skill_root = ROOT / manifest["skills"].lstrip("./")
    skill_path = skill_root / "recall" / "SKILL.md"
    assert skill_path.exists()

    skill_text = skill_path.read_text()
    assert "name: recall" in skill_text
    assert "Use when searching local recall session memory" in skill_text
    assert "version: 3.4.2" in skill_text


def test_session_end_packaging_uses_the_durable_enqueue_path():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    session_end = hooks["hooks"]["SessionEnd"][0]["hooks"][0]
    assert session_end["timeout"] == 3
    wrapper = (ROOT / "hooks" / "scripts" / "session-end").read_text()
    assert "--enqueue" in wrapper
    assert "nohup" not in wrapper


def test_dev_cache_sync_finds_the_current_codex_version():
    helper = (ROOT / "bin" / "sync-dev.sh").read_text()
    assert "CODEX_CACHE_ROOT" in helper
    assert "sort -V" in helper
    assert "3.3.0" not in helper


def test_codex_manifest_has_required_interface_fields():
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
    interface = manifest["interface"]

    required = {
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "websiteURL",
        "privacyPolicyURL",
        "termsOfServiceURL",
        "defaultPrompt",
        "brandColor",
        "screenshots",
    }

    assert required.issubset(interface)
    assert "Interactive" in interface["capabilities"]
