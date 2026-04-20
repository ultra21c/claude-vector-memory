#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# OpenClaw hook example: auto-sync memory index on agent session start.
#
# Place this in your OpenClaw hooks directory or reference from openclaw.json.
#
# This hook runs memory-index sync before the agent starts, ensuring
# the search index is up-to-date with the latest markdown memory files.
# ---------------------------------------------------------------------------

set -euo pipefail

# Determine which agent is starting (passed by OpenClaw as $OPENCLAW_AGENT_ID)
AGENT_ID="${OPENCLAW_AGENT_ID:-main}"

# Map agent IDs to their memory source directories
case "$AGENT_ID" in
    main)
        SOURCE_DIR="$HOME/.openclaw/workspace/memory"
        ;;
    sangchul)
        SOURCE_DIR="$HOME/.openclaw/workspace-sangchul/memory"
        ;;
    *)
        echo "[memory-index] Unknown agent: $AGENT_ID, skipping sync"
        exit 0
        ;;
esac

# Skip if source directory doesn't exist
if [ ! -d "$SOURCE_DIR" ]; then
    echo "[memory-index] Source dir not found: $SOURCE_DIR, skipping"
    exit 0
fi

# Run incremental sync (fast — only processes changed files)
echo "[memory-index] Syncing index for agent=$AGENT_ID source=$SOURCE_DIR"
memory-index --source "$SOURCE_DIR" --quiet sync

echo "[memory-index] Sync complete for $AGENT_ID"
