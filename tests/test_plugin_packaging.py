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
    assert manifest["skills"] == "./skills/"

    skill_root = ROOT / manifest["skills"].lstrip("./")
    skill_path = skill_root / "recall" / "SKILL.md"
    assert skill_path.exists()

    skill_text = skill_path.read_text()
    assert "name: recall" in skill_text
    assert "Use when searching local recall session memory" in skill_text


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
