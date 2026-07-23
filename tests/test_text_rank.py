"""Tests for local text-ranking helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.text_rank import (
    rank_query_texts,
    rank_texts,
    score_text,
    slug_from_text,
    strip_noise,
    tokenize,
    top_terms,
)


def test_tokenize_removes_common_stop_words():
    assert "auth" in tokenize("Please fix the auth redirect")
    assert "the" not in tokenize("Please fix the auth redirect")


def test_top_terms_prefers_actionable_repeated_terms():
    terms = top_terms([
        "Fix checkout redirect failure",
        "Verify checkout tests",
        "Unrelated meeting note",
    ], limit=3)
    assert "checkout" in terms


def test_rank_texts_returns_original_extracts():
    ranked = rank_texts([
        "ok",
        "Fix the checkout redirect and verify the browser test",
        "Thanks",
    ], limit=1)
    assert ranked == ["Fix the checkout redirect and verify the browser test"]


def test_slug_from_text_is_short_and_safe():
    assert slug_from_text("Fix checkout redirect failure!") == "fix-checkout-redirect-failure"


def test_score_text_handles_subtoken_matches():
    assert score_text("recall", "plugin:recall-failures") > 0


def test_rank_query_texts_orders_relevant_text_first():
    ranked = rank_query_texts("payment gateway", [
        "update login page",
        "fix payment gateway timeout",
    ])
    assert ranked[0][0] == 1


def test_strip_noise_removes_spinner_status_but_keeps_real_content():
    text = (
        "Vibrating… (14m 46s · ↓ 33.6k tokens)\n"
        "\n"
        "Tip: Run /install-github-app to tag @claude right from your Github issues and PRs\n"
        "\n"
        "this was a prototype so it's not good"
    )
    cleaned = " ".join(strip_noise(text).split())
    assert "tokens)" not in cleaned
    assert "Tip:" not in cleaned
    assert "this was a prototype so it's not good" in cleaned


def test_strip_noise_does_not_eat_prose_mentioning_tip_mid_sentence():
    text = "Quick tip: use the --dry-run flag before applying this migration."
    assert "dry-run flag" in strip_noise(text)


def test_rank_texts_deprioritizes_spinner_noise_over_real_signal():
    ranked = rank_texts([
        "vitating… (14m 46s · ↓ 33.6k tokens) Tip: Run /install-github-app to tag @claude",
        "Fix the checkout redirect and verify the browser test",
    ], limit=1)
    assert ranked == ["Fix the checkout redirect and verify the browser test"]


def test_rank_texts_boosts_ratified_decisions_over_routine_activity():
    ranked = rank_texts([
        "cd into the repo and run the build script one more time",
        "Decided: muted text should be solid gray, not a lighter tint",
    ], limit=1)
    assert ranked == ["Decided: muted text should be solid gray, not a lighter tint"]
