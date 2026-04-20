"""
MemoryIndex — SQLite + FTS5 + vector search index over markdown memory files.

Keeps markdown files as canonical source of truth. Builds a queryable index
with full-text search, vector similarity, and hybrid ranking.

Usage:
    from claude_vector_memory import MemoryIndex

    with MemoryIndex(source_dir="/path/to/memory") as idx:
        idx.sync()
        results = idx.search("query")
        context = idx.retrieve("query")  # auto-sync + LLM-ready text
"""

import sqlite3
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .chunking import (
    DEFAULT_TAG_PATTERNS,
    chunk_markdown,
    classify_file,
    content_hash,
    extract_date,
    extract_title,
    infer_tags,
)
from .embedders import (
    OpenAIEmbedder,
    get_reranker,
    select_provider,
)

# ---------------------------------------------------------------------------
# sqlite-vec support (optional)
# ---------------------------------------------------------------------------

_vec_available = False


def _load_vec(conn: sqlite3.Connection) -> bool:
    global _vec_available
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        _vec_available = True
        return True
    except ImportError:
        print(
            "Note: sqlite-vec not installed. "
            "Install with: pip install claude-vector-memory",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"Note: sqlite-vec load failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    title       TEXT,
    heading     TEXT,
    content     TEXT    NOT NULL,
    date        TEXT,
    updated_at  TEXT    NOT NULL,
    tags        TEXT,
    content_hash TEXT   NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_hash
    ON chunks(source_path, content_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    title,
    heading,
    content,
    tags,
    content='chunks',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, title, heading, content, tags)
    VALUES (new.id, new.title, new.heading, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, title, heading, content, tags)
    VALUES ('delete', old.id, old.title, old.heading, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, title, heading, content, tags)
    VALUES ('delete', old.id, old.title, old.heading, old.content, old.tags);
    INSERT INTO chunks_fts(rowid, title, heading, content, tags)
    VALUES (new.id, new.title, new.heading, new.content, new.tags);
END;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# ---------------------------------------------------------------------------
# MemoryIndex
# ---------------------------------------------------------------------------


class MemoryIndex:
    """Main index class — builds and queries the memory index.

    All paths are configurable. The two key parameters:
        source_dir:  directory containing markdown memory files (source of truth)
        db_path:     path to the SQLite database (derived artifact)

    Optionally, an index_file can point to a top-level MEMORY.md outside source_dir.

    Example:
        with MemoryIndex(source_dir="./memory", db_path="./.memory_index.db") as idx:
            idx.sync()
            results = idx.search("query")
    """

    def __init__(
        self,
        source_dir: str | Path | None = None,
        db_path: str | Path | None = None,
        index_file: str | Path | None = None,
        tag_patterns: dict[str, str] | None = None,
        quiet: bool = False,
    ):
        """Initialize the memory index.

        Args:
            source_dir: Directory containing memory/*.md files.
                        Defaults to ./memory relative to cwd.
            db_path: Path to the SQLite database file.
                     Defaults to .memory_index.db next to source_dir.
            index_file: Optional top-level MEMORY.md file to include.
                        Defaults to MEMORY.md in source_dir's parent.
                        Set to None or "" to skip.
            tag_patterns: Custom tag inference patterns.
                          Keys are tag names, values are regex patterns.
                          Defaults to DEFAULT_TAG_PATTERNS.
            quiet: Suppress status messages to stderr.
        """
        # Resolve source directory
        if source_dir is None:
            self.source_dir = Path.cwd() / "memory"
        else:
            self.source_dir = Path(source_dir).resolve()

        # Resolve database path
        if db_path is None:
            self.db_path = self.source_dir.parent / ".memory_index.db"
        else:
            self.db_path = Path(db_path).resolve()

        # Resolve index file (MEMORY.md)
        if index_file is None:
            default_index = self.source_dir.parent / "MEMORY.md"
            self.index_file = default_index if default_index.exists() else None
        elif index_file == "" or index_file is False:
            self.index_file = None
        else:
            p = Path(index_file).resolve()
            self.index_file = p if p.exists() else None

        # The "workspace" is the common parent used for relative paths in DB
        self.workspace = self.source_dir.parent

        self.tag_patterns = tag_patterns or DEFAULT_TAG_PATTERNS
        self.quiet = quiet

        self.embedder = select_provider(quiet=quiet)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.has_vec = _load_vec(self.conn)
        self._init_schema()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript(SCHEMA_SQL)

        if self.has_vec:
            stored = cur.execute(
                "SELECT value FROM meta WHERE key = 'embed_dim'"
            ).fetchone()
            stored_dim = int(stored[0]) if stored else None
            stored_provider = cur.execute(
                "SELECT value FROM meta WHERE key = 'embed_provider'"
            ).fetchone()
            stored_prov_name = stored_provider[0] if stored_provider else None

            need_vec_rebuild = False

            if stored_dim is None or stored_dim != self.embedder.dim:
                cur.execute("DROP TABLE IF EXISTS chunks_vec")
                self.conn.commit()
                need_vec_rebuild = True
                if stored_dim is not None and not self.quiet:
                    print(
                        f"Note: embedding dimension changed ({stored_dim} -> {self.embedder.dim}). "
                        f"Vector index will be rebuilt on next sync/rebuild.",
                        file=sys.stderr,
                    )

            if stored_prov_name and stored_prov_name != self.embedder.name:
                if not need_vec_rebuild:
                    cur.execute("DROP TABLE IF EXISTS chunks_vec")
                    self.conn.commit()
                    need_vec_rebuild = True
                if not self.quiet:
                    print(
                        f"Note: embedding provider changed ({stored_prov_name} -> {self.embedder.name}). "
                        f"Vector index will be rebuilt on next sync/rebuild.",
                        file=sys.stderr,
                    )

            cur.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec "
                f"USING vec0(embedding float[{self.embedder.dim}])"
            )

            cur.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('embed_dim', ?)",
                (str(self.embedder.dim),),
            )
            cur.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('embed_provider', ?)",
                (self.embedder.name,),
            )

            if need_vec_rebuild:
                try:
                    cur.execute("DELETE FROM chunks_vec")
                except Exception:
                    pass

        self.conn.commit()

    def close(self):
        self.conn.close()

    # -- Staleness detection --------------------------------------------------

    def _get_file_mtime_iso(self, path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()

    def _stored_mtimes(self) -> dict[str, str]:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT key, value FROM meta WHERE key LIKE 'file_mtime:%'"
        ).fetchall()
        return {row[0].removeprefix("file_mtime:"): row[1] for row in rows}

    def _store_file_mtime(self, cur: sqlite3.Cursor, rel_path: str, mtime: str):
        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (f"file_mtime:{rel_path}", mtime),
        )

    def _remove_file_mtime(self, cur: sqlite3.Cursor, rel_path: str):
        cur.execute("DELETE FROM meta WHERE key = ?", (f"file_mtime:{rel_path}",))

    def stale_files(self) -> dict:
        """Check which source files have changed since last index.

        Returns dict with keys: modified, added, deleted, is_stale.
        """
        stored = self._stored_mtimes()
        current_files = self._gather_files()

        current_map: dict[str, Path] = {}
        for f in current_files:
            rel = str(f.relative_to(self.workspace))
            current_map[rel] = f

        modified = []
        added = []
        deleted = []

        for rel, fpath in current_map.items():
            current_mtime = self._get_file_mtime_iso(fpath)
            if rel not in stored:
                added.append(rel)
            elif stored[rel] != current_mtime:
                modified.append(rel)

        for rel in stored:
            if rel not in current_map:
                deleted.append(rel)

        return {
            "modified": modified,
            "added": added,
            "deleted": deleted,
            "is_stale": bool(modified or added or deleted),
        }

    def is_stale(self) -> bool:
        """Quick check: are any source files out of sync?"""
        return self.stale_files()["is_stale"]

    # -- Ingestion ------------------------------------------------------------

    def rebuild(self) -> dict:
        """Full rebuild: clear and re-ingest all memory files."""
        cur = self.conn.cursor()

        cur.execute("DELETE FROM chunks")
        cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('delete-all')")
        if self.has_vec:
            cur.execute("DELETE FROM chunks_vec")
        cur.execute("DELETE FROM meta WHERE key LIKE 'file_mtime:%'")
        cur.execute("DELETE FROM meta WHERE key IN ('last_rebuild', 'last_sync')")

        stats = {"files": 0, "chunks": 0}

        for fpath in self._gather_files():
            n = self._ingest_file(fpath, cur)
            stats["files"] += 1
            stats["chunks"] += n

        now = datetime.now().isoformat()
        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_rebuild', ?)",
            (now,),
        )
        self.conn.commit()
        stats["last_rebuild"] = now
        return stats

    def sync(self) -> dict:
        """Incremental sync: only re-ingest changed/new files, remove deleted.

        Returns dict with keys: modified, added, deleted, chunks_added, unchanged.
        """
        changes = self.stale_files()

        vec_needs_rebuild = False
        if self.has_vec:
            vec_count = self.conn.execute(
                "SELECT COUNT(*) FROM chunks_vec"
            ).fetchone()[0]
            chunk_count = self.conn.execute(
                "SELECT COUNT(*) FROM chunks"
            ).fetchone()[0]
            if chunk_count > 0 and vec_count == 0:
                vec_needs_rebuild = True

        if not changes["is_stale"] and not vec_needs_rebuild:
            return {
                "modified": 0,
                "added": 0,
                "deleted": 0,
                "chunks_added": 0,
                "unchanged": True,
            }

        cur = self.conn.cursor()
        total_chunks = 0

        for rel in changes["deleted"]:
            if self.has_vec:
                ids = [
                    r[0]
                    for r in cur.execute(
                        "SELECT id FROM chunks WHERE source_path = ?", (rel,)
                    ).fetchall()
                ]
                for cid in ids:
                    cur.execute("DELETE FROM chunks_vec WHERE rowid = ?", (cid,))
            cur.execute("DELETE FROM chunks WHERE source_path = ?", (rel,))
            self._remove_file_mtime(cur, rel)

        for rel in changes["modified"]:
            fpath = self.workspace / rel
            if self.has_vec:
                ids = [
                    r[0]
                    for r in cur.execute(
                        "SELECT id FROM chunks WHERE source_path = ?", (rel,)
                    ).fetchall()
                ]
                for cid in ids:
                    cur.execute("DELETE FROM chunks_vec WHERE rowid = ?", (cid,))
            cur.execute("DELETE FROM chunks WHERE source_path = ?", (rel,))
            n = self._ingest_file(fpath, cur)
            total_chunks += n

        for rel in changes["added"]:
            fpath = self.workspace / rel
            n = self._ingest_file(fpath, cur)
            total_chunks += n

        if vec_needs_rebuild and self.has_vec:
            self._rebuild_vectors(cur)

        now = datetime.now().isoformat()
        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_sync', ?)",
            (now,),
        )
        self.conn.commit()

        return {
            "modified": len(changes["modified"]),
            "added": len(changes["added"]),
            "deleted": len(changes["deleted"]),
            "chunks_added": total_chunks,
            "unchanged": False,
            "vectors_rebuilt": vec_needs_rebuild,
        }

    def _rebuild_vectors(self, cur: sqlite3.Cursor):
        rows = cur.execute(
            "SELECT id, title, heading, content FROM chunks"
        ).fetchall()
        for row in rows:
            full_text = f"{row['heading'] or ''}\n{row['content']}"
            vec = self.embedder.embed(full_text)
            vec_bytes = self.embedder.to_bytes(vec)
            cur.execute(
                "INSERT OR REPLACE INTO chunks_vec(rowid, embedding) VALUES (?, ?)",
                (row["id"], vec_bytes),
            )

    def _gather_files(self) -> list[Path]:
        files = []
        if self.index_file and self.index_file.exists():
            files.append(self.index_file)
        if self.source_dir.exists():
            for f in sorted(self.source_dir.glob("*.md")):
                files.append(f)
        return files

    def _ingest_file(self, path: Path, cur: sqlite3.Cursor) -> int:
        content = path.read_text(encoding="utf-8")
        rel_path = str(path.relative_to(self.workspace))
        index_filename = self.index_file.name if self.index_file else "MEMORY.md"
        kind = classify_file(path, index_filename=index_filename)
        title = extract_title(content, path)
        file_date = extract_date(path, content)
        mtime = self._get_file_mtime_iso(path)

        self._store_file_mtime(cur, rel_path, mtime)

        chunks = chunk_markdown(content)
        count = 0

        for i, chunk in enumerate(chunks):
            body = chunk["body"]
            heading = chunk["heading"]

            full_text = f"{heading or ''}\n{body}"
            tags = infer_tags(full_text, self.tag_patterns)
            chash = content_hash(body)

            cur.execute(
                """INSERT OR REPLACE INTO chunks
                   (source_path, kind, title, heading, content, date,
                    updated_at, tags, content_hash, chunk_index)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rel_path,
                    kind,
                    title,
                    heading,
                    body,
                    file_date,
                    mtime,
                    ",".join(tags),
                    chash,
                    i,
                ),
            )
            row_id = cur.lastrowid

            if self.has_vec and row_id:
                vec = self.embedder.embed(full_text)
                vec_bytes = self.embedder.to_bytes(vec)
                cur.execute(
                    "INSERT OR REPLACE INTO chunks_vec(rowid, embedding) VALUES (?, ?)",
                    (row_id, vec_bytes),
                )

            count += 1

        return count

    # -- Search ---------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        kind: str | None = None,
        tag: str | None = None,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Search the memory index.

        Args:
            query: search query text
            limit: max results
            kind: filter by kind ('daily', 'lesson', 'index')
            tag: filter by tag
            mode: 'hybrid' (default), 'fts', or 'vector'
        """
        if mode == "vector":
            if self.has_vec:
                return self._vector_search(query, limit, kind, tag)
            return self._fts_search(query, limit, kind, tag)
        elif mode == "fts":
            return self._fts_search(query, limit, kind, tag)
        else:
            return self._hybrid_search(query, limit, kind, tag)

    def _fts_search(
        self, query: str, limit: int, kind: str | None, tag: str | None
    ) -> list[dict]:
        import re

        fts_query = re.sub(r"[^\w\s\uac00-\ud7a3]", "", query)
        if not fts_query.strip():
            return []

        words = fts_query.split()
        fts_expr = " OR ".join(words)

        sql = """
            SELECT c.id, c.source_path, c.kind, c.title, c.heading,
                   snippet(chunks_fts, 2, '>>>', '<<<', '...', 40) AS snippet,
                   c.date, c.tags, c.updated_at,
                   bm25(chunks_fts, 1.0, 2.0, 5.0, 1.0) AS score
            FROM chunks_fts f
            JOIN chunks c ON c.id = f.rowid
            WHERE chunks_fts MATCH ?
        """
        params: list = [fts_expr]

        if kind:
            sql += " AND c.kind = ?"
            params.append(kind)
        if tag:
            sql += " AND c.tags LIKE ?"
            params.append(f"%{tag}%")

        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        cur = self.conn.cursor()
        try:
            rows = cur.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            simple = " OR ".join(f'"{w}"' for w in words if w)
            if not simple:
                return []
            params[0] = simple
            try:
                rows = cur.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []

        return [self._row_to_result(r) for r in rows]

    def _vector_search(
        self, query: str, limit: int, kind: str | None, tag: str | None
    ) -> list[dict]:
        if hasattr(self.embedder, "embed_query"):
            vec = self.embedder.embed_query(query)
        else:
            vec = self.embedder.embed(query)
        vec_bytes = self.embedder.to_bytes(vec)

        sql = """
            SELECT v.rowid, v.distance
            FROM chunks_vec v
            WHERE embedding MATCH ?
            AND k = ?
            ORDER BY distance
        """
        fetch_limit = limit * 3 if (kind or tag) else limit

        cur = self.conn.cursor()
        try:
            vec_rows = cur.execute(sql, (vec_bytes, fetch_limit)).fetchall()
        except Exception:
            return []

        results = []
        for vr in vec_rows:
            row_id = vr[0]
            distance = vr[1]
            chunk = cur.execute(
                "SELECT * FROM chunks WHERE id = ?", (row_id,)
            ).fetchone()
            if not chunk:
                continue
            if kind and chunk["kind"] != kind:
                continue
            if tag and tag not in (chunk["tags"] or ""):
                continue

            r = self._row_to_result(chunk)
            r["score"] = -distance
            results.append(r)

            if len(results) >= limit:
                break

        return results

    def _hybrid_search(
        self, query: str, limit: int, kind: str | None, tag: str | None
    ) -> list[dict]:
        """Hybrid search: FTS5 + vector + recency via RRF + cross-encoder reranking."""
        pool_size = max(limit * 3, 20)

        fts_results = self._fts_search(query, pool_size, kind, tag)
        vec_results = (
            self._vector_search(query, pool_size, kind, tag) if self.has_vec else []
        )

        all_results: dict[int, dict] = {}
        for r in fts_results:
            all_results[r["id"]] = r
        for r in vec_results:
            if r["id"] not in all_results:
                all_results[r["id"]] = r

        if not all_results:
            return []

        k = 60
        rrf_scores: dict[int, float] = {}

        for rank, r in enumerate(fts_results):
            rrf_scores[r["id"]] = rrf_scores.get(r["id"], 0) + 1.0 / (k + rank + 1)
        for rank, r in enumerate(vec_results):
            rrf_scores[r["id"]] = rrf_scores.get(r["id"], 0) + 1.0 / (k + rank + 1)

        today = date.today()
        for chunk_id in rrf_scores:
            r = all_results[chunk_id]
            d = r.get("date")
            if d:
                try:
                    mem_date = date.fromisoformat(d)
                    age_days = (today - mem_date).days
                    recency = 1.0 + 0.2 * max(0.0, 1.0 - age_days / 180.0)
                    rrf_scores[chunk_id] *= recency
                except (ValueError, TypeError):
                    pass

        rerank_pool = max(limit * 2, 10)
        ranked = sorted(rrf_scores.items(), key=lambda x: -x[1])[:rerank_pool]

        if self.embedder.name == "local" and len(ranked) > 1:
            ranked = self._rerank(query, ranked, all_results)

        results = []
        for chunk_id, score in ranked[:limit]:
            r = dict(all_results[chunk_id])
            r["score"] = score
            results.append(r)

        return results

    def _rerank(
        self,
        query: str,
        ranked: list[tuple[int, float]],
        all_results: dict[int, dict],
    ) -> list[tuple[int, float]]:
        reranker = get_reranker()
        if reranker is None:
            return ranked

        try:
            pairs = []
            chunk_ids = []
            for chunk_id, _ in ranked:
                r = all_results[chunk_id]
                passage = r.get("snippet", "") or ""
                if r.get("heading"):
                    passage = f"{r['heading']}\n{passage}"
                pairs.append((query, passage))
                chunk_ids.append(chunk_id)

            scores = reranker.predict(pairs)

            rrf_map = dict(ranked)
            rrf_max = max(s for _, s in ranked) if ranked else 1.0

            reranked = []
            ce_min = float(min(scores))
            ce_max = float(max(scores))
            ce_range = ce_max - ce_min if ce_max > ce_min else 1.0

            for i, chunk_id in enumerate(chunk_ids):
                ce_norm = (float(scores[i]) - ce_min) / ce_range
                rrf_norm = rrf_map[chunk_id] / rrf_max if rrf_max > 0 else 0
                combined = 0.7 * ce_norm + 0.3 * rrf_norm
                reranked.append((chunk_id, combined))

            reranked.sort(key=lambda x: -x[1])
            return reranked
        except Exception:
            return ranked

    def _row_to_result(self, row) -> dict:
        keys = row.keys()
        content = row["content"] if "content" in keys else ""
        snippet = row["snippet"] if "snippet" in keys else content[:200]
        return {
            "id": row["id"] if "id" in keys else 0,
            "source_path": row["source_path"],
            "kind": row["kind"],
            "title": row["title"],
            "heading": row["heading"],
            "snippet": snippet,
            "date": row["date"],
            "tags": row["tags"],
            "updated_at": row["updated_at"],
            "score": row["score"] if "score" in keys else 0,
        }

    # -- Programmatic helpers -------------------------------------------------

    def search_as_context(
        self,
        query: str,
        limit: int = 5,
        kind: str | None = None,
        tag: str | None = None,
        mode: str = "hybrid",
    ) -> str:
        """Search and return results formatted as LLM context."""
        results = self.search(query, limit=limit, kind=kind, tag=tag, mode=mode)
        if not results:
            return f"[No memory results for: {query}]"

        parts = [f"Memory search results for: {query}", ""]
        for i, r in enumerate(results, 1):
            heading = f" > {r['heading']}" if r["heading"] else ""
            d = f" [{r['date']}]" if r["date"] else ""
            tags = f" (tags: {r['tags']})" if r["tags"] else ""
            parts.append(f"[{i}] {r['source_path']}{heading}{d}{tags}")
            parts.append(r["snippet"])
            parts.append("")

        return "\n".join(parts)

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        kind: str | None = None,
        tag: str | None = None,
        mode: str = "hybrid",
        auto_sync: bool = True,
    ) -> str:
        """One-call agent helper: auto-sync if stale, then return LLM-ready context.

        This is the recommended entry point for agent/automation use.
        """
        if auto_sync and self.is_stale():
            self.sync()
        return self.search_as_context(query, limit=limit, kind=kind, tag=tag, mode=mode)

    def doctor(self) -> dict:
        """Diagnose the memory index configuration and health."""
        checks = []

        files = self._gather_files()
        checks.append((
            "source_files",
            len(files) > 0,
            f"{len(files)} memory files found" if files else "No memory files found",
        ))

        checks.append((
            "sqlite_vec",
            self.has_vec,
            "sqlite-vec loaded"
            if self.has_vec
            else "sqlite-vec not available (pip install claude-vector-memory)",
        ))

        total = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        checks.append((
            "index_populated",
            total > 0,
            f"{total} chunks indexed"
            if total
            else "Index is empty — run 'rebuild' or 'sync'",
        ))

        fts_count = 0
        try:
            fts_count = self.conn.execute(
                "SELECT COUNT(*) FROM chunks_fts"
            ).fetchone()[0]
        except Exception:
            pass
        fts_ok = fts_count == total
        checks.append((
            "fts_sync",
            fts_ok,
            f"FTS5 index: {fts_count} entries"
            + ("" if fts_ok else f" (expected {total})"),
        ))

        if self.has_vec:
            vec_count = 0
            try:
                vec_count = self.conn.execute(
                    "SELECT COUNT(*) FROM chunks_vec"
                ).fetchone()[0]
            except Exception:
                pass
            vec_ok = vec_count == total
            checks.append((
                "vec_sync",
                vec_ok,
                f"Vector index: {vec_count} entries"
                + ("" if vec_ok else f" (expected {total}, run 'sync' to fix)"),
            ))

        checks.append((
            "embed_provider",
            True,
            f"Provider: {self.embedder.name} ({self.embedder.dim}d)",
        ))

        if self.embedder.name == "openai":
            ok, msg = OpenAIEmbedder.validate_api_key(self.embedder.api_key)
            checks.append(("openai_key_format", ok, msg))
            ok, msg = self.embedder.test_connection()
            checks.append(("openai_connection", ok, msg))

        if self.embedder.name == "local":
            checks.append((
                "local_model",
                True,
                f"Model: {self.embedder.model_name} ({self.embedder.dim}d)",
            ))
            reranker = get_reranker()
            checks.append((
                "cross_encoder_reranker",
                reranker is not None,
                "Cross-encoder reranker: loaded"
                if reranker
                else "Cross-encoder reranker: not available (hybrid still works without it)",
            ))

        stale = self.stale_files()
        checks.append((
            "freshness",
            not stale["is_stale"],
            "Index is fresh"
            if not stale["is_stale"]
            else (
                f"Index is stale: {len(stale['modified'])} modified, "
                f"{len(stale['added'])} new, {len(stale['deleted'])} deleted"
            ),
        ))

        all_ok = all(ok for _, ok, _ in checks)
        return {
            "checks": checks,
            "summary": "All checks passed" if all_ok else "Some checks failed",
            "all_ok": all_ok,
        }

    def all_tags(self) -> list[tuple[str, int]]:
        """Return all tags with their occurrence counts, sorted by frequency."""
        cur = self.conn.cursor()
        rows = cur.execute("SELECT tags FROM chunks WHERE tags != ''").fetchall()
        counter: Counter = Counter()
        for row in rows:
            for tag in row[0].split(","):
                tag = tag.strip()
                if tag:
                    counter[tag] += 1
        return counter.most_common()

    def stats(self) -> dict:
        """Return index statistics."""
        cur = self.conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        by_kind = dict(
            cur.execute(
                "SELECT kind, COUNT(*) FROM chunks GROUP BY kind"
            ).fetchall()
        )
        files = cur.execute(
            "SELECT COUNT(DISTINCT source_path) FROM chunks"
        ).fetchone()[0]
        last_rebuild = cur.execute(
            "SELECT value FROM meta WHERE key = 'last_rebuild'"
        ).fetchone()
        last_sync = cur.execute(
            "SELECT value FROM meta WHERE key = 'last_sync'"
        ).fetchone()
        vec_count = 0
        if self.has_vec:
            try:
                vec_count = cur.execute(
                    "SELECT COUNT(*) FROM chunks_vec"
                ).fetchone()[0]
            except Exception:
                pass

        embed_provider = cur.execute(
            "SELECT value FROM meta WHERE key = 'embed_provider'"
        ).fetchone()
        embed_dim = cur.execute(
            "SELECT value FROM meta WHERE key = 'embed_dim'"
        ).fetchone()

        return {
            "total_chunks": total,
            "files_indexed": files,
            "by_kind": by_kind,
            "vector_entries": vec_count,
            "has_vec": self.has_vec,
            "embed_provider": embed_provider[0] if embed_provider else "unknown",
            "embed_dim": int(embed_dim[0]) if embed_dim else 0,
            "last_rebuild": last_rebuild[0] if last_rebuild else None,
            "last_sync": last_sync[0] if last_sync else None,
            "db_path": str(self.db_path),
            "source_dir": str(self.source_dir),
        }

    def status(self) -> dict:
        """Return full status including staleness info."""
        s = self.stats()
        s["staleness"] = self.stale_files()
        s["tags"] = self.all_tags()
        return s
