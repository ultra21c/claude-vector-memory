"""
CLI entry point for claude-vector-memory.

Usage:
    memory-index sync                          # incremental update
    memory-index rebuild                       # full rebuild
    memory-index search "query" -n 5           # search
    memory-index status                        # stats + staleness
    memory-index doctor                        # health check

    # Or via python -m:
    python -m claude_vector_memory sync
"""

import argparse
import sys

from .index import MemoryIndex


def _print_results(results: list[dict]):
    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        heading_str = f" > {r['heading']}" if r["heading"] else ""
        date_str = f"  [{r['date']}]" if r["date"] else ""
        tags_str = f"  tags: {r['tags']}" if r["tags"] else ""
        score_str = f"  (score: {r['score']:.4f})" if r["score"] else ""

        print(f"\n--- Result {i}{score_str} ---")
        print(f"  {r['source_path']}{heading_str}{date_str}")
        if tags_str:
            print(f" {tags_str}")

        snippet = r["snippet"].replace("\n", "\n    ")
        print(f"    {snippet}")


def _warn_if_stale(idx: MemoryIndex):
    changes = idx.stale_files()
    if not changes["is_stale"]:
        return
    parts = []
    if changes["modified"]:
        parts.append(f"{len(changes['modified'])} modified")
    if changes["added"]:
        parts.append(f"{len(changes['added'])} new")
    if changes["deleted"]:
        parts.append(f"{len(changes['deleted'])} deleted")
    detail = ", ".join(parts)
    print(
        f"Warning: index is stale ({detail} file(s)). Run 'sync' to update.",
        file=sys.stderr,
    )


def _run_verify(idx: MemoryIndex):
    queries = ["process management", "bug fix", "strategy", "lesson learned"]
    modes = ["fts", "hybrid"]
    if idx.has_vec:
        modes.insert(1, "vector")

    s = idx.stats()
    print(
        f"Verification — provider: {s['embed_provider']} ({s['embed_dim']}d), "
        f"chunks: {s['total_chunks']}, vectors: {s['vector_entries']}"
    )
    print("=" * 70)

    for q in queries:
        print(f'\nQuery: "{q}"')
        print("-" * 50)

        for mode in modes:
            results = idx.search(q, limit=3, mode=mode)
            print(f"\n  [{mode.upper()}]")
            if not results:
                print("    (no results)")
                continue
            for i, r in enumerate(results, 1):
                heading = f" > {r['heading']}" if r["heading"] else ""
                score = f" [{r['score']:.4f}]" if r["score"] else ""
                print(f"    {i}. {r['source_path']}{heading}{score}")

        print()


def main():
    parser = argparse.ArgumentParser(
        prog="memory-index",
        description="claude-vector-memory: hybrid search over markdown memory files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Commands:
  sync       Incremental update (recommended)
  rebuild    Full rebuild from scratch
  search     Hybrid, full-text, or vector search
  status     Index stats + staleness info
  tags       List all known tags
  verify     Compare search modes side-by-side
  doctor     Health check

Examples:
  memory-index --source ./memory sync
  memory-index --source ./memory search "bug fix"
  memory-index --source ./memory --db ./my_index.db search "query"
  memory-index doctor
""",
    )

    # Global options
    parser.add_argument(
        "--source",
        "-s",
        help="Path to memory directory (default: ./memory)",
    )
    parser.add_argument(
        "--db",
        help="Path to database file (default: .memory_index.db next to source)",
    )
    parser.add_argument(
        "--index-file",
        help="Path to top-level MEMORY.md (default: auto-detect)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress status messages",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("sync", help="Incremental sync — update only changed files")
    sub.add_parser("rebuild", help="Full rebuild from scratch")

    sp_search = sub.add_parser("search", help="Search the memory index")
    sp_search.add_argument("query", help="Search query")
    sp_search.add_argument(
        "-n", "--limit", type=int, default=5, help="Max results (default: 5)"
    )
    sp_search.add_argument("-k", "--kind", help="Filter by kind: daily, lesson, index")
    sp_search.add_argument("-t", "--tag", help="Filter by tag")
    sp_search.add_argument(
        "-m",
        "--mode",
        default="hybrid",
        choices=["hybrid", "fts", "vector"],
        help="Search mode (default: hybrid)",
    )
    sp_search.add_argument(
        "--vec", action="store_true", help="Shortcut for --mode vector"
    )

    sub.add_parser("status", help="Show index stats and staleness info")
    sub.add_parser("stats", help="Alias for status")
    sub.add_parser("tags", help="List all known tags with counts")
    sub.add_parser("verify", help="Compare search modes side-by-side")
    sub.add_parser("doctor", help="Health check")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print("\nQuick start:")
        print("  memory-index --source ./memory sync")
        print("  memory-index --source ./memory search 'query'")
        print("  memory-index doctor")
        return

    idx = MemoryIndex(
        source_dir=args.source,
        db_path=args.db,
        index_file=args.index_file,
        quiet=args.quiet,
    )

    try:
        if args.command == "sync":
            result = idx.sync()
            if result["unchanged"]:
                print("Index is up to date. No changes needed.")
            else:
                parts = []
                if result["added"]:
                    parts.append(f"{result['added']} added")
                if result["modified"]:
                    parts.append(f"{result['modified']} modified")
                if result["deleted"]:
                    parts.append(f"{result['deleted']} deleted")
                print(
                    f"Synced: {', '.join(parts)}. "
                    f"{result['chunks_added']} chunks indexed."
                )
                if result.get("vectors_rebuilt"):
                    print("Vector embeddings rebuilt with new provider/dimension.")

        elif args.command == "rebuild":
            print("Rebuilding memory index...")
            stats = idx.rebuild()
            print(f"Done: {stats['files']} files, {stats['chunks']} chunks indexed.")
            if idx.has_vec:
                print(
                    f"Vector embeddings: {stats['chunks']} entries "
                    f"({idx.embedder.name} {idx.embedder.dim}d)"
                )
            else:
                print("Vector search: not available (sqlite-vec not loaded)")
            print(f"Database: {idx.db_path}")

        elif args.command == "search":
            _warn_if_stale(idx)
            mode = "vector" if args.vec else args.mode
            results = idx.search(
                args.query,
                limit=args.limit,
                kind=args.kind,
                tag=args.tag,
                mode=mode,
            )
            _print_results(results)

        elif args.command in ("status", "stats"):
            s = idx.status()
            print("Memory Index Status")
            print(f"  Source dir:     {s['source_dir']}")
            print(f"  Database:       {s['db_path']}")
            print(f"  Files indexed:  {s['files_indexed']}")
            print(f"  Total chunks:   {s['total_chunks']}")
            print(f"  By kind:        {s['by_kind']}")
            print(f"  Embeddings:     {s['embed_provider']} ({s['embed_dim']}d)")
            print(f"  Vector entries: {s['vector_entries']}")
            print(f"  sqlite-vec:     {'yes' if s['has_vec'] else 'no'}")
            print(f"  Last rebuild:   {s['last_rebuild'] or 'never'}")
            print(f"  Last sync:      {s['last_sync'] or 'never'}")

            stale = s["staleness"]
            if stale["is_stale"]:
                print(f"\n  ** Index is STALE **")
                if stale["modified"]:
                    print(f"     Modified: {', '.join(stale['modified'])}")
                if stale["added"]:
                    print(f"     New:      {', '.join(stale['added'])}")
                if stale["deleted"]:
                    print(f"     Deleted:  {', '.join(stale['deleted'])}")
                print(f"     Run 'sync' to update.")
            else:
                print(f"\n  Index is up to date.")

            if s["tags"]:
                tag_str = ", ".join(f"{t}({c})" for t, c in s["tags"])
                print(f"\n  Tags: {tag_str}")

        elif args.command == "tags":
            tags = idx.all_tags()
            if not tags:
                print("No tags found. Run 'rebuild' or 'sync' first.")
            else:
                print("Tags (by frequency):")
                for tag, count in tags:
                    print(f"  {tag:15s} {count}")

        elif args.command == "verify":
            _warn_if_stale(idx)
            _run_verify(idx)

        elif args.command == "doctor":
            result = idx.doctor()
            print("Memory Index Doctor")
            print("=" * 50)
            for name, ok, msg in result["checks"]:
                icon = "OK" if ok else "!!"
                print(f"  [{icon}] {name}: {msg}")
            print()
            if result["all_ok"]:
                print("All checks passed.")
            else:
                print("Some checks need attention — see details above.")
                for name, ok, msg in result["checks"]:
                    if not ok:
                        if name == "index_populated":
                            print("\n  Next step: memory-index rebuild")
                        elif name in ("freshness", "vec_sync", "fts_sync"):
                            print("\n  Next step: memory-index sync")
                        elif name == "sqlite_vec":
                            print(
                                "\n  Next step: pip install claude-vector-memory"
                            )
                        break

    finally:
        idx.close()
