"""
claude-vector-memory — Hybrid search over markdown memory files.

SQLite + FTS5 + vector search index that keeps markdown as source of truth.

Usage:
    from claude_vector_memory import MemoryIndex

    with MemoryIndex(source_dir="./memory") as idx:
        idx.sync()
        results = idx.search("query")
        context = idx.retrieve("query")  # auto-sync + LLM-ready text
"""

from .chunking import DEFAULT_TAG_PATTERNS
from .index import MemoryIndex

__all__ = ["MemoryIndex", "DEFAULT_TAG_PATTERNS"]
__version__ = "0.1.0"
