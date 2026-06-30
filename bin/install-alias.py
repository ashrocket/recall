#!/usr/bin/env python3
"""
Install or remove the personal /recall shortcut at ~/.claude/commands/recall.md.

Usage:
  install-alias.py check     Print "MISSING" or "EXISTS\\n---\\n<contents>"
  install-alias.py write     Create or overwrite ~/.claude/commands/recall.md
  install-alias.py remove    Delete ~/.claude/commands/recall.md if present
"""

import sys
from pathlib import Path

ALIAS_PATH = Path.home() / ".claude" / "commands" / "recall.md"

ALIAS_CONTENT = """Search, save, and restart recall sessions for the current project.

Personal shortcut for `/recall:recall` — see that command's docs for full usage. Regenerate this file with `/recall:install-alias`. Delete this file to remove the shortcut.

Invoke the `recall:recall` skill via the `Skill` tool with `args: "$ARGUMENTS"`. The skill handles all subcommand dispatch (save, restart, learn, search, cleanup, etc.).
"""


def cmd_check() -> int:
    if ALIAS_PATH.exists():
        print("EXISTS")
        print("---")
        print(ALIAS_PATH.read_text(), end="")
    else:
        print("MISSING")
    return 0


def cmd_write() -> int:
    ALIAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALIAS_PATH.write_text(ALIAS_CONTENT)
    print(f"WROTE {ALIAS_PATH}")
    return 0


def cmd_remove() -> int:
    if ALIAS_PATH.exists():
        ALIAS_PATH.unlink()
        print(f"REMOVED {ALIAS_PATH}")
    else:
        print(f"NOT_FOUND {ALIAS_PATH}")
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "write", "remove"):
        print(__doc__, file=sys.stderr)
        return 2
    return {"check": cmd_check, "write": cmd_write, "remove": cmd_remove}[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
