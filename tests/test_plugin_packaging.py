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


def test_every_module_parses_on_the_oldest_supported_python():
    """recall declares Python 3.10+, and it is installed as a plugin on whatever
    interpreter the user already has.

    A syntax feature from a newer Python is not a type error caught in review —
    it is an ImportError on someone else's machine. PEP 701 (nested same-quote
    f-strings) is the easy one to introduce by accident, and `ast.parse
    (feature_version=...)` does NOT catch it, so this shells out to a real older
    interpreter when one is available.
    """
    import shutil
    import subprocess
    from pathlib import Path

    older = next(
        (shutil.which(name) for name in ("python3.10", "python3.11")
         if shutil.which(name)),
        None,
    )
    if older is None:
        pytest.skip("no python3.10/3.11 available to check against")

    repo = Path(__file__).resolve().parent.parent
    sources = sorted(
        p for pattern in ("bin/*.py", "lib/*.py", "hooks/scripts/*.py",
                          "migrations/*.py", "tests/*.py")
        for p in repo.glob(pattern)
    )

    failures = []
    for source in sources:
        result = subprocess.run(
            [older, "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())", str(source)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            last = [l for l in result.stderr.strip().splitlines() if l.strip()][-1]
            failures.append(f"{source.relative_to(repo)}: {last}")

    assert not failures, (
        "these modules use syntax newer than recall's declared floor:\n  "
        + "\n  ".join(failures)
    )
