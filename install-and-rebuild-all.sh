#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/lucas/working/claude-vector-memory"
cd "$PROJECT_DIR"

echo "[1/4] Installing claude-vector-memory with all extras..."
uv sync --all-extras

echo "[2/4] Rebuilding Sangchul memory index..."
uv run memory-index \
  --source /Users/lucas/.openclaw/workspace-sangchul/memory \
  --index-file /Users/lucas/.openclaw/workspace-sangchul/MEMORY.md \
  rebuild

echo "[3/4] Rebuilding Cheolsu(main) memory index..."
uv run memory-index \
  --source /Users/lucas/.openclaw/workspace/memory \
  --index-file /Users/lucas/.openclaw/workspace/MEMORY.md \
  rebuild

echo "[4/4] Running health checks..."
uv run memory-index \
  --source /Users/lucas/.openclaw/workspace-sangchul/memory \
  --index-file /Users/lucas/.openclaw/workspace-sangchul/MEMORY.md \
  doctor

uv run memory-index \
  --source /Users/lucas/.openclaw/workspace/memory \
  --index-file /Users/lucas/.openclaw/workspace/MEMORY.md \
  doctor

echo "Done. Highest-quality memory system is installed and rebuilt for Sangchul + Cheolsu."
