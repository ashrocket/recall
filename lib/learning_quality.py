"""
One definition of what makes a learning worth keeping.

recall proposes learnings automatically from session failures. Left unchecked
the proposals drift toward *incident records* — "this command failed, here is
the next command that happened to run" — which read like knowledge but carry no
rule. They cost the user a review decision, sit in the index forever, and are
worthless to a future session.

This module is the single bar those proposals must clear. It is applied at two
points:

* **Upstream**, in :func:`lib.knowledge.add_pending_learning`, so a proposal
  that cannot state a rule never reaches the review queue at all. This is the
  one that matters — nothing downstream can recover a decision the user should
  never have been asked to make.
* **Downstream**, in :mod:`lib.native_memory`, as defense in depth before
  anything is written into Claude Code's memory directory.

The bar is deliberately about *form*, not truth. recall cannot tell whether a
fix is correct; it can tell whether the proposal states a fix at all, in words
that would still mean something in a different session.
"""

import re


#: Sources whose output describes an incident rather than a rule. A count of
#: how often something failed belongs in ``/recall failures``, which is built
#: from the index's failure patterns — not in a learning.
TRANSIENT_SOURCES = {"repeated_pattern"}

#: Prefixes recall's own extractor used to emit. "Use instead: `<command>`" is a
#: verbatim substitution for one invocation and "Error pattern: …" is an echo of
#: stderr. Both are retained here because older indexes still contain them.
TEMPLATE_PREFIXES = ("use instead:", "error pattern:")

#: Below this, a "fix" is not instruction enough to act on.
MIN_GUIDANCE_LEN = 12

#: A title that only counts occurrences ("Recurring general errors (3x …)").
_COUNTING_TITLE_RE = re.compile(r"^recurring\b", re.IGNORECASE)

#: A description that is a transcript of the failing command.
COMMAND_ECHO_RE = re.compile(r"^Command `.*` failed with", re.DOTALL)


def guidance_of(learning: dict) -> str:
    """Return the actionable part of *learning*, whichever field holds it."""
    if not isinstance(learning, dict):
        return ""
    return (learning.get("fix") or learning.get("solution") or "").strip()


def is_durable(learning: dict):
    """Return ``(ok, reason)`` for whether *learning* states a reusable rule.

    ``reason`` is user-facing: it is printed when a proposal is dropped or held
    back, so it explains the judgement rather than naming an internal rule.
    """
    if not isinstance(learning, dict):
        return False, "not a learning record"

    if (learning.get("source") or "").strip() in TRANSIENT_SOURCES:
        return False, "records a failure streak, not a rule"

    title = (learning.get("title") or "").strip()
    if _COUNTING_TITLE_RE.match(title):
        return False, "records a failure streak, not a rule"

    guidance = guidance_of(learning)
    if len(guidance) < MIN_GUIDANCE_LEN:
        return False, "no actionable fix recorded"

    if guidance.lower().startswith(TEMPLATE_PREFIXES):
        return False, "auto-extracted command substitution, specific to one session"

    return True, ""


def hook_text(learning: dict) -> str:
    """Pick the one line that best describes *learning* to a future reader.

    A description that is a transcript of the failing command says nothing a
    future session can use; the fix does.
    """
    if not isinstance(learning, dict):
        return ""
    description = (learning.get("description") or "").strip()
    if not description or COMMAND_ECHO_RE.match(description):
        return guidance_of(learning) or (learning.get("title") or "").strip()
    return description
