"""
Multi-agent configuration example.

Multiple agents share the same engine (claude-vector-memory package),
but each agent has:
    - its own source directory (markdown memory files)
    - its own database file (derived index)

This is the SAFEST recommended layout — no cross-agent write conflicts.

Directory layout:
    ~/.openclaw/
    ├── workspace/                    # main agent workspace
    │   ├── MEMORY.md
    │   ├── memory/
    │   │   ├── 2026-01-15.md
    │   │   └── lessons.md
    │   └── .memory_index.db          # main agent's index
    │
    ├── workspace-sangchul/           # sangchul agent workspace
    │   ├── MEMORY.md
    │   ├── memory/
    │   │   ├── 2026-03-06.md
    │   │   └── process-lessons.md
    │   └── .memory_index.db          # sangchul's index
    │
    └── workspace-research/           # research agent workspace
        ├── memory/
        │   ├── papers.md
        │   └── findings.md
        └── .memory_index.db          # research agent's index
"""

from pathlib import Path

from claude_vector_memory import MemoryIndex

# ---------------------------------------------------------------------------
# Option 1: Each agent creates its own MemoryIndex instance
# ---------------------------------------------------------------------------

AGENTS = {
    "main": {
        "source_dir": Path.home() / ".openclaw/workspace/memory",
    },
    "sangchul": {
        "source_dir": Path.home() / ".openclaw/workspace-sangchul/memory",
    },
    "research": {
        "source_dir": Path.home() / ".openclaw/workspace-research/memory",
        # Custom DB location (e.g., faster SSD)
        "db_path": "/tmp/research_memory.db",
    },
}


def get_agent_index(agent_id: str) -> MemoryIndex:
    """Factory: create a MemoryIndex for a specific agent."""
    config = AGENTS[agent_id]
    return MemoryIndex(
        source_dir=config["source_dir"],
        db_path=config.get("db_path"),  # None = auto (next to source_dir)
        quiet=True,
    )


# Per-agent usage
with get_agent_index("sangchul") as idx:
    idx.sync()
    context = idx.retrieve("trading strategy lesson")
    print(context)


# ---------------------------------------------------------------------------
# Option 2: Cross-agent search (read from multiple agents)
# ---------------------------------------------------------------------------

def search_all_agents(query: str, limit: int = 3) -> list[dict]:
    """Search across all agents and merge results."""
    all_results = []
    for agent_id in AGENTS:
        with get_agent_index(agent_id) as idx:
            idx.sync()
            results = idx.search(query, limit=limit)
            for r in results:
                r["agent"] = agent_id  # tag which agent this came from
            all_results.extend(results)

    # Sort by score descending, take top N
    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return all_results[:limit]


# Cross-agent search example
results = search_all_agents("deployment problem", limit=5)
for r in results:
    print(f"  [{r['agent']}] {r['source_path']} > {r['heading']}")


# ---------------------------------------------------------------------------
# Option 3: Per-agent custom tag patterns
# ---------------------------------------------------------------------------

AGENT_TAG_PATTERNS = {
    "sangchul": {
        "trading": r"(?:거래|트레이딩|매매|PnL|승률|SL|TP)",
        "strategy": r"(?:전략|strategy|필터|threshold|config)",
        "bug": r"(?:버그|bug|에러|error|수정|fix)",
        "risk": r"(?:리스크|risk|손실|loss|청산|liquidat)",
    },
    "research": {
        "paper": r"(?:paper|arxiv|journal|publication)",
        "finding": r"(?:finding|result|conclusion|evidence)",
        "method": r"(?:method|approach|algorithm|technique)",
    },
}


def get_agent_index_with_tags(agent_id: str) -> MemoryIndex:
    config = AGENTS[agent_id]
    return MemoryIndex(
        source_dir=config["source_dir"],
        db_path=config.get("db_path"),
        tag_patterns=AGENT_TAG_PATTERNS.get(agent_id),
        quiet=True,
    )
