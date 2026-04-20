"""
Markdown parsing, chunking, and metadata extraction.
"""

import hashlib
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Default tag patterns — override via MemoryIndex(tag_patterns={...})
# ---------------------------------------------------------------------------

DEFAULT_TAG_PATTERNS: dict[str, str] = {
    "trading": r"(?:거래|트레이딩|매매|PnL|승률|SL|TP|진입|포지션)",
    "strategy": r"(?:전략|strategy|필터|threshold|config|설정)",
    "bug": r"(?:버그|bug|에러|error|수정|fix)",
    "lesson": r"(?:교훈|실수|대참사|주의|반드시|lesson)",
    "system": r"(?:데몬|daemon|크론|cron|PID|프로세스|웹소켓)",
    "backtest": r"(?:백테스트|backtest|시뮬|simul)",
    "risk": r"(?:리스크|risk|손실|loss|청산|liquidat)",
    "performance": r"(?:성적|승률|win.*rate|R:R|수익|profit)",
}


def classify_file(path: Path, index_filename: str = "MEMORY.md") -> str:
    """Classify a memory file by kind: daily, lesson, or index."""
    if path.name == index_filename:
        return "index"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", path.stem):
        return "daily"
    return "lesson"


def extract_date(path: Path, content: str) -> str | None:
    """Try to extract a date from filename or content."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", path.stem)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4}-\d{2}-\d{2})", content[:200])
    if m:
        return m.group(1)
    return None


def infer_tags(content: str, patterns: dict[str, str] | None = None) -> list[str]:
    """Infer tags from content using keyword detection."""
    patterns = patterns or DEFAULT_TAG_PATTERNS
    tags = []
    for tag, pattern in patterns.items():
        if re.search(pattern, content, re.IGNORECASE):
            tags.append(tag)
    return tags


def chunk_markdown(content: str) -> list[dict]:
    """Split markdown into chunks by ## headings.

    Returns list of dicts with keys: heading, body.
    """
    lines = content.split("\n")
    chunks = []
    current_heading = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    chunks.append({"heading": current_heading, "body": body})
            current_heading = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            chunks.append({"heading": current_heading, "body": body})

    if not chunks:
        chunks.append({"heading": None, "body": content.strip()})

    return chunks


def extract_title(content: str, path: Path) -> str:
    """Extract first # heading or use filename."""
    m = re.match(r"^#\s+(.+)", content)
    if m:
        return m.group(1).strip()
    return path.stem


def content_hash(text: str) -> str:
    """SHA256 hash (truncated) for dedup / change detection."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]
