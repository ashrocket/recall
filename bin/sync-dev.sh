#!/usr/bin/env bash
# Sync the dev repo to the installed Claude Code plugin cache.
# Run from anywhere inside the recall repo.
#
# Usage: bin/sync-dev.sh [--dry-run]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PLUGIN_JSON="$HOME/.claude/plugins/installed_plugins.json"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# Find the installed path from installed_plugins.json
INSTALL_PATH=$(python3 - <<'EOF'
import json, sys, os
path = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
try:
    data = json.load(open(path))
    entries = data.get("plugins", {}).get("recall@recall", [])
    if entries:
        print(entries[0]["installPath"])
except Exception as e:
    sys.stderr.write(f"Error reading installed_plugins.json: {e}\n")
    sys.exit(1)
EOF
)

if [[ -z "$INSTALL_PATH" ]]; then
    echo "Error: recall not found in $PLUGIN_JSON"
    echo "Install first: /plugin marketplace add ashrocket/recall"
    exit 1
fi

echo "Dev:       $REPO_ROOT"
echo "Installed: $INSTALL_PATH"
$DRY_RUN && echo "(dry run — no files will change)" && echo ""

INSTALL_PATHS=("$INSTALL_PATH")
CODEX_INSTALL_PATH="$HOME/.codex/plugins/cache/recall/recall/3.3.0"
if [[ -d "$CODEX_INSTALL_PATH" && "$CODEX_INSTALL_PATH" != "$INSTALL_PATH" ]]; then
    INSTALL_PATHS+=("$CODEX_INSTALL_PATH")
fi

RSYNC_OPTS=(-a --itemize-changes)
$DRY_RUN && RSYNC_OPTS+=(--dry-run)

for INSTALL_PATH in "${INSTALL_PATHS[@]}"; do
    echo ""
    echo "Sync target: $INSTALL_PATH"

    # Sync code directories — delete stale files so old commands/scripts don't linger
    CODE_DIRS=(bin commands hooks lib migrations skills sops .claude-plugin .codex-plugin)
    for dir in "${CODE_DIRS[@]}"; do
        src="$REPO_ROOT/$dir"
        dst="$INSTALL_PATH/$dir"
        [[ -d "$src" ]] || continue
        echo "→ $dir/"
        rsync "${RSYNC_OPTS[@]}" --delete \
            --exclude="__pycache__" --exclude="*.pyc" \
            "$src/" "$dst/"
    done

    # Sync top-level files (README, AGENTS.md, LICENSE, etc.) — no --delete here
    echo "→ root files"
    rsync "${RSYNC_OPTS[@]}" \
        --exclude=".git/" \
        --exclude="__pycache__/" \
        --exclude="*.pyc" \
        --exclude=".pytest_cache/" \
        --exclude="target/" \
        --exclude="BACKLOG.md" \
        --exclude=".DS_Store" \
        --exclude=".claude/" \
        --exclude="bug*.md" \
        --exclude="tests/" \
        --exclude="restarts/" \
        --exclude="worker/" \
        --exclude="docs/" \
        --exclude="bin/" \
        --exclude="commands/" \
        --exclude="hooks/" \
        --exclude="lib/" \
        --exclude="migrations/" \
        --exclude="skills/" \
        --exclude="sops/" \
        --exclude=".claude-plugin/" \
        --exclude=".codex-plugin/" \
        "$REPO_ROOT/" "$INSTALL_PATH/"

    # Copy compiled fast-path binaries when the dev repo has them. Build artifacts
    # are otherwise excluded so rsync does not copy the full Cargo target cache.
    if [[ -d "$REPO_ROOT/target/release" ]]; then
        FAST_BINS=()
        for bin in recall-sessions-rs session-start-rs; do
            [[ -x "$REPO_ROOT/target/release/$bin" ]] && FAST_BINS+=("$bin")
        done
        if [[ ${#FAST_BINS[@]} -gt 0 ]]; then
            echo "→ target/release/ fast binaries"
            $DRY_RUN || mkdir -p "$INSTALL_PATH/target/release"
            for bin in "${FAST_BINS[@]}"; do
                rsync "${RSYNC_OPTS[@]}" "$REPO_ROOT/target/release/$bin" "$INSTALL_PATH/target/release/$bin"
            done
        fi
    fi
done

if ! $DRY_RUN; then
    # Update gitCommitSha to reflect current state
    GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
    GIT_DIRTY=false
    if ! git -C "$REPO_ROOT" diff-index --quiet HEAD -- 2>/dev/null || [[ -n "$(git -C "$REPO_ROOT" ls-files --others --exclude-standard)" ]]; then
        GIT_DIRTY=true
    fi
    python3 - <<EOF
import json, os
path = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
data = json.load(open(path))
entries = data.get("plugins", {}).get("recall@recall", [])
dirty = "$GIT_DIRTY" == "true"
for entry in entries:
    entry["gitCommitSha"] = "$GIT_SHA"
    if dirty:
        entry["devSyncDirty"] = True
    else:
        entry.pop("devSyncDirty", None)
if entries:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    suffix = " (dirty source tree)" if dirty else ""
    print(f"Updated gitCommitSha → $GIT_SHA{suffix}")
EOF
    echo ""
    echo "Sync complete. Restart Claude Code to pick up changes."
fi
