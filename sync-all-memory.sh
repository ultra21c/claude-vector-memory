#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/lucas/working/claude-vector-memory"
cd "$PROJECT_DIR"

echo "Syncing Sangchul memory..."
uv run memory-index \
  --source /Users/lucas/.openclaw/workspace-sangchul/memory \
  --index-file /Users/lucas/.openclaw/workspace-sangchul/MEMORY.md \
  sync

echo "Syncing Cheolsu(main) memory..."
uv run memory-index \
  --source /Users/lucas/.openclaw/workspace/memory \
  --index-file /Users/lucas/.openclaw/workspace/MEMORY.md \
  sync

echo "Done."
