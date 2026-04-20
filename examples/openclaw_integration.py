"""
OpenClaw integration example.

Shows how to wire claude-vector-memory into an OpenClaw agent workspace.

OpenClaw agents have:
    - A workspace directory (configurable per agent in openclaw.json)
    - Session hooks (on-user-prompt-submit, on-pre-tool-use, etc.)
    - Separate memory storage per agent

This integration:
    1. Reads the agent's workspace from OpenClaw config
    2. Points MemoryIndex at the agent's memory/ subdirectory
    3. Provides a retrieve() call suitable for prompt injection
"""

import json
from pathlib import Path

from claude_vector_memory import MemoryIndex

# ---------------------------------------------------------------------------
# Read OpenClaw config to discover agent workspaces
# ---------------------------------------------------------------------------

OPENCLAW_CONFIG = Path.home() / ".openclaw/openclaw.json"


def get_agent_workspace(agent_id: str) -> Path | None:
    """Read an agent's workspace from openclaw.json."""
    if not OPENCLAW_CONFIG.exists():
        return None

    config = json.loads(OPENCLAW_CONFIG.read_text())
    agents = config.get("agents", {})

    # Check agent list
    for agent in agents.get("list", []):
        if agent.get("id") == agent_id:
            ws = agent.get("workspace")
            if ws:
                return Path(ws)

    # Fallback to default workspace
    default_ws = agents.get("defaults", {}).get("workspace")
    if default_ws:
        return Path(default_ws)

    return None


def memory_retrieve(agent_id: str, query: str, limit: int = 5) -> str:
    """Retrieve memory context for an OpenClaw agent.

    This is the main integration point. Call from:
        - Agent hooks (on-user-prompt-submit)
        - Agent boot scripts
        - Custom OpenClaw plugins
    """
    workspace = get_agent_workspace(agent_id)
    if workspace is None:
        return f"[No workspace found for agent: {agent_id}]"

    source_dir = workspace / "memory"
    if not source_dir.exists():
        return f"[No memory directory at: {source_dir}]"

    with MemoryIndex(source_dir=source_dir, quiet=True) as idx:
        return idx.retrieve(query, limit=limit)


# ---------------------------------------------------------------------------
# Example: use in an OpenClaw prompt-submit hook
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    agent_id = sys.argv[1] if len(sys.argv) > 1 else "main"
    query = sys.argv[2] if len(sys.argv) > 2 else "recent context"

    context = memory_retrieve(agent_id, query)
    print(context)
