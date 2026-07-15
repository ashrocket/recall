#!/usr/bin/env python3
"""
Display and formatting helpers for recall-sessions.py.

Pure formatters and show_* functions are kept here so that
recall-sessions.py can focus on I/O, cleanup mutations, and dispatch.
"""

import re
from datetime import datetime

from lib.shared import save_index


def format_date(date_input) -> str:
    """Format date consistently."""
    if isinstance(date_input, str):
        try:
            dt = datetime.fromisoformat(date_input.replace('Z', '+00:00'))
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError, AttributeError):
            return date_input[:19]
    elif isinstance(date_input, datetime):
        return date_input.strftime('%Y-%m-%d %H:%M:%S')
    return str(date_input)


def _matches_terms(text: str, terms: list) -> bool:
    """Return True if all terms appear in text (case-insensitive AND match)."""
    text_lower = text.lower()
    return all(t in text_lower for t in terms)


def normalize_search_query(query: str | None) -> str:
    """Normalize a user-entered recall search query without destroying path syntax."""
    normalized = " ".join((query or "").strip().split())
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in ("'", '"'):
        normalized = normalized[1:-1].strip()
    return normalized


def literal_search_terms(query: str | None) -> list[str]:
    """Return literal AND-search terms, ignoring standalone punctuation."""
    terms = []
    for raw in normalize_search_query(query).lower().split():
        term = raw.strip("'\"`")
        term = term.strip("?!,;:")
        if term:
            terms.append(term)
    return terms


def compile_regex_query(query: str | None):
    """Compile slash-delimited recall regex queries.

    Returns ``(regex, error)``. ``regex`` is ``None`` for non-regex queries.
    A leading bare ``*`` is treated as ``.*`` because users often type
    ``/*.ext/`` when they mean "anything ending with .ext".
    """
    normalized = normalize_search_query(query)
    if not normalized.startswith("/"):
        return None, None

    closing = normalized.rfind("/")
    if closing <= 0:
        return None, None

    flags_text = normalized[closing + 1:]
    if flags_text and flags_text != "i":
        # Treat normal absolute paths like /Users/me/repo as literal searches,
        # while still surfacing errors for slash-delimited regex attempts.
        return None, None

    if closing != len(normalized) - 1 and flags_text != "i":
        return None, None

    pattern = normalized[1:closing]
    if pattern.startswith("*"):
        pattern = "." + pattern

    flags = re.IGNORECASE
    try:
        return re.compile(pattern, flags), None
    except re.error as exc:
        return None, str(exc)


def is_regex_query(query: str | None) -> bool:
    """Return True when the query uses slash-delimited regex syntax."""
    regex, error = compile_regex_query(query)
    return regex is not None or error is not None


def matches_search_query(text: str, query: str | None) -> bool:
    """Return True if *text* matches a literal or slash-delimited regex query."""
    regex, error = compile_regex_query(query)
    if error:
        return False
    if regex:
        return bool(regex.search(text or ""))
    return _matches_terms(text or "", literal_search_terms(query))


def show_stats(index: dict, project_folder: str):
    """Show skill and learning usage statistics."""
    print("## Recall Usage Statistics")
    print()

    usage = index.get('usage', {})

    # Skill usage
    skills = usage.get('skills', {})
    if skills:
        print("### Skill Invocations")
        print()
        sorted_skills = sorted(skills.items(), key=lambda x: x[1].get('count', 0), reverse=True)
        for skill_name, data in sorted_skills:
            count = data.get('count', 0)
            last_used = data.get('last_used', 'never')[:10]
            sessions = len(data.get('sessions', []))
            print(f"  **{skill_name}**: {count} uses across {sessions} sessions (last: {last_used})")
        print()
    else:
        print("### Skill Invocations")
        print("  No skill usage tracked yet.")
        print()

    # Learning displays
    learnings_shown = usage.get('learnings_shown', {})
    if learnings_shown:
        print("### Learnings Displayed")
        print()
        sorted_learnings = sorted(learnings_shown.items(), key=lambda x: x[1].get('count', 0), reverse=True)
        for learning_key, data in sorted_learnings:
            count = data.get('count', 0)
            last_shown = data.get('last_shown', 'never')[:10]
            print(f"  **{learning_key}**: shown {count} times (last: {last_shown})")
        print()
    else:
        print("### Learnings Displayed")
        print("  No learning displays tracked yet.")
        print()

    # Summary
    total_skills = sum(s.get('count', 0) for s in skills.values())
    total_learnings = sum(l.get('count', 0) for l in learnings_shown.values())
    print("### Summary")
    print(f"  Total skill invocations: {total_skills}")
    print(f"  Total learning displays: {total_learnings}")
    print(f"  Unique skills used: {len(skills)}")
    print(f"  Unique learnings shown: {len(learnings_shown)}")

    # Identify unused learnings
    all_learnings = index.get('learnings', [])
    learning_keys = set()
    for l in all_learnings:
        if isinstance(l, dict):
            key = f"{l.get('category', 'general')}/{l.get('title', 'Unknown')}"
            learning_keys.add(key)

    shown_keys = set(learnings_shown.keys())
    unused = learning_keys - shown_keys
    if unused:
        print()
        print("### Unused Learnings (never displayed)")
        for key in sorted(unused):
            print(f"  - {key}")


def show_failures(index: dict, project_folder: str):
    """Show failure patterns across sessions."""
    print("## Failure Patterns Across Sessions")
    print()

    failure_patterns = index.get('failure_patterns', {})

    # Track that we're showing learnings (for usage stats)
    learnings = index.get('learnings', [])
    learnings_to_track = []

    # Always show learnings first if available
    if learnings:
        print("## Learnings & Best Practices")
        print()
        for learning in learnings:
            if isinstance(learning, dict):
                cat = learning.get('category', 'general')
                title = learning.get('title', 'Unknown')
                desc = learning.get('description', '')
                solution = learning.get('solution', '')

                # Track this learning was shown
                learnings_to_track.append(f"{cat}/{title}")

                print(f"### [{cat}] {title}")
                if desc:
                    print(f"  {desc}")
                fix = learning.get('fix', '')
                guidance = fix or solution
                if guidance:
                    first_line = guidance.split('\n')[0]
                    suffix = '...' if '\n' in guidance else ''
                    print(f"  **Fix:** {first_line}{suffix}")
                tools = learning.get('tools', {})
                if tools:
                    print("  **Tools:**")
                    for name, usage in tools.items():
                        print(f"    - {name}: {usage}")
                examples = learning.get('examples', [])
                if examples:
                    print("  **Examples:**")
                    for ex in examples[:3]:
                        print(f"    `{ex}`")
                print()
            else:
                print(f"  - {learning}")
        print()

        # Update usage stats for displayed learnings
        if learnings_to_track:
            if 'usage' not in index:
                index['usage'] = {'skills': {}, 'learnings_shown': {}}
            if 'learnings_shown' not in index['usage']:
                index['usage']['learnings_shown'] = {}

            now = datetime.now().isoformat()
            for learning_key in learnings_to_track:
                if learning_key not in index['usage']['learnings_shown']:
                    index['usage']['learnings_shown'][learning_key] = {'count': 0, 'first_shown': now}
                index['usage']['learnings_shown'][learning_key]['count'] += 1
                index['usage']['learnings_shown'][learning_key]['last_shown'] = now

            # Save updated index
            save_index(index, project_folder)

    if not failure_patterns:
        if not learnings:
            print("No failure patterns or learnings recorded yet.")
        return

    # Sort by frequency
    sorted_patterns = sorted(
        failure_patterns.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    for pattern, failures in sorted_patterns:
        pattern_name = pattern.replace('_', ' ').title()
        print(f"### {pattern_name} ({len(failures)} occurrences)")
        print()

        # Show recent failures of this type
        for f in failures[-5:]:  # Last 5
            date = f.get('date', 'unknown')[:10]
            cmd = f.get('command', 'unknown')[:60]
            error = f.get('error', '')[:100]
            print(f"  **{date}**: `{cmd}`")
            if error:
                print(f"    Error: {error}...")
        print()
