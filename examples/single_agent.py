"""
Single-agent configuration example.

One agent, one memory directory, one database.
This is the simplest setup — suitable for a single Claude Code workspace.

Directory layout:
    my-project/
    ├── MEMORY.md              # top-level index (optional)
    ├── memory/                # markdown memory files (source of truth)
    │   ├── 2026-01-15.md
    │   ├── 2026-01-16.md
    │   └── lessons.md
    └── .memory_index.db       # auto-generated, gitignore this
"""

from claude_vector_memory import MemoryIndex

# --- Basic usage ---

with MemoryIndex(source_dir="./memory") as idx:
    # Build/update the index
    idx.sync()

    # Search (hybrid mode — best quality)
    results = idx.search("deployment bug", limit=5)
    for r in results:
        print(f"  {r['source_path']} > {r['heading']}  (score: {r['score']:.3f})")

    # Get LLM-ready context string
    context = idx.retrieve("what went wrong with the deploy?")
    print(context)


# --- With custom paths ---

with MemoryIndex(
    source_dir="/path/to/my/memory/dir",
    db_path="/path/to/my/index.db",
    index_file="/path/to/MEMORY.md",  # or None to skip
) as idx:
    idx.sync()
    results = idx.search("query")


# --- With custom tag patterns ---

# Override the default tag patterns to match your domain
my_tags = {
    "deploy": r"(?:deploy|release|rollback|CI/CD)",
    "bug": r"(?:bug|error|fix|crash|exception)",
    "decision": r"(?:decided|decision|chose|trade-?off)",
    "learning": r"(?:learned|lesson|mistake|insight|TIL)",
}

with MemoryIndex(source_dir="./memory", tag_patterns=my_tags) as idx:
    idx.rebuild()  # rebuild to re-tag with new patterns
    tags = idx.all_tags()
    print("Tags:", tags)


# --- Agent hook pattern ---

def get_memory_context(query: str) -> str:
    """Call this from your agent hook / prompt injection."""
    with MemoryIndex(source_dir="./memory", quiet=True) as idx:
        return idx.retrieve(query, limit=5)


# Example: inject into an agent prompt
context = get_memory_context("SL stop-loss configuration")
prompt = f"""You are a helpful assistant. Use the following memory context:

{context}

Now answer the user's question: ..."""
