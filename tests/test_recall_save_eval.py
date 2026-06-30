"""Tests for bin/recall-save-eval.py."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock


def _import_recall_save_eval():
    script = Path(__file__).resolve().parent.parent / "bin" / "recall-save-eval.py"
    spec = importlib.util.spec_from_file_location("recall_save_eval", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["recall_save_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_unique_llm_prompt_path_adds_llm_suffix(tmp_path):
    mod = _import_recall_save_eval()
    local = tmp_path / "fix-auth.prompt"
    local.write_text("local")
    result = mod.unique_llm_prompt_path(str(local))
    assert result == tmp_path / "fix-auth.llm.prompt"


def test_build_log_entry_records_prompt_stats(tmp_path):
    mod = _import_recall_save_eval()
    local = tmp_path / "local.prompt"
    llm = tmp_path / "llm.prompt"
    local.write_text("local restart prompt")
    llm.write_text("llm restart prompt with more detail")

    entry = mod.build_log_entry(
        working_dir="/tmp/app",
        local_prompt=str(local),
        llm_prompt=str(llm),
        winner="llm",
        reason="More specific next steps.",
    )

    assert entry["winner"] == "llm"
    assert entry["judge"] == "llm"
    assert entry["local"]["words"] == 3
    assert entry["llm"]["words"] == 6


def test_append_log_writes_jsonl(tmp_path):
    mod = _import_recall_save_eval()
    entry = {"winner": "tie"}
    with mock.patch.object(mod, "get_project_dir", return_value=tmp_path):
        path = mod.append_log("proj", entry)

    assert path == tmp_path / "recall-save-evals.jsonl"
    lines = path.read_text().splitlines()
    assert json.loads(lines[0])["winner"] == "tie"
