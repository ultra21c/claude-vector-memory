"""
Embedding providers for the memory index.

Three providers available:
    - local: Neural model via sentence-transformers (best quality, no API key)
    - openai: OpenAI text-embedding-3-small (requires API key)
    - tfidf: Enhanced TF-IDF with character n-grams (zero dependencies)
"""

import hashlib
import math
import os
import re
import struct
import sys
from collections import Counter

DEFAULT_EMBED_DIM = 256


class EnhancedTFIDFEmbedder:
    """Enhanced TF-IDF embedder with character n-grams and higher dimensions.

    256 dimensions with character trigrams, word bigrams, and three independent
    hash functions. Zero external dependencies. Works with any language.
    """

    name = "tfidf"

    def __init__(self, dim: int = DEFAULT_EMBED_DIM):
        self.dim = dim

    def _tokenize(self, text: str) -> tuple[list[str], list[str], list[str]]:
        text_lower = text.lower()
        words = re.findall(r"[a-zA-Z]{2,}|[\uac00-\ud7a3]+", text_lower)

        trigrams = []
        for word in words:
            if len(word) >= 3:
                for i in range(len(word) - 2):
                    trigrams.append(f"_c_{word[i:i+3]}")

        bigrams = []
        for i in range(len(words) - 1):
            bigrams.append(f"_b_{words[i]}_{words[i+1]}")

        return words, trigrams, bigrams

    def embed(self, text: str) -> list[float]:
        words, trigrams, bigrams = self._tokenize(text)
        if not words:
            return [0.0] * self.dim

        vec = [0.0] * self.dim

        word_counts = Counter(words)
        for token, count in word_counts.items():
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            bucket = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[bucket] += sign * math.log1p(count)

        tri_counts = Counter(trigrams)
        for token, count in tri_counts.items():
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            bucket = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[bucket] += sign * math.log1p(count) * 0.5

        bi_counts = Counter(bigrams)
        for token, count in bi_counts.items():
            h = int(hashlib.blake2b(token.encode(), digest_size=16).hexdigest(), 16)
            bucket = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[bucket] += sign * math.log1p(count) * 0.7

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]

        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def to_bytes(self, vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)


class OpenAIEmbedder:
    """OpenAI embeddings via API. Requires OPENAI_API_KEY.

    Uses text-embedding-3-small (1536d) by default.
    """

    name = "openai"
    BATCH_LIMIT = 20

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
    ):
        self.api_key = api_key
        self.model = model
        self.dim = dim

    @staticmethod
    def validate_api_key(api_key: str) -> tuple[bool, str]:
        if not api_key:
            return False, "OPENAI_API_KEY is empty"
        if not api_key.startswith(("sk-", "sk-proj-")):
            return False, (
                f"OPENAI_API_KEY looks wrong (starts with '{api_key[:6]}...'). "
                f"Expected 'sk-...' or 'sk-proj-...'"
            )
        if len(api_key) < 20:
            return False, "OPENAI_API_KEY is too short — likely truncated"
        return True, "API key format OK"

    def test_connection(self) -> tuple[bool, str]:
        import requests as req

        try:
            resp = req.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": ["test"], "model": self.model},
                timeout=10,
            )
            if resp.status_code == 401:
                return False, "Authentication failed — check OPENAI_API_KEY"
            if resp.status_code == 404:
                return False, f"Model '{self.model}' not found"
            if resp.status_code == 429:
                return False, "Rate limited — try again in a moment"
            resp.raise_for_status()
            data = resp.json()
            actual_dim = len(data["data"][0]["embedding"])
            return True, f"Connected. Model: {self.model}, native dim: {actual_dim}"
        except req.ConnectionError:
            return False, "Cannot reach api.openai.com — check network"
        except req.Timeout:
            return False, "Connection timed out"
        except Exception as e:
            return False, f"Unexpected error: {e}"

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if len(texts) <= self.BATCH_LIMIT:
            return self._embed_batch_raw(texts)
        results = []
        for i in range(0, len(texts), self.BATCH_LIMIT):
            batch = texts[i : i + self.BATCH_LIMIT]
            results.extend(self._embed_batch_raw(batch))
        return results

    def _embed_batch_raw(self, texts: list[str]) -> list[list[float]]:
        import requests as req

        try:
            resp = req.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": texts, "model": self.model},
                timeout=30,
            )
        except req.ConnectionError:
            raise RuntimeError("Cannot reach api.openai.com — check your network")
        except req.Timeout:
            raise RuntimeError(f"OpenAI API timed out embedding {len(texts)} texts")

        if resp.status_code == 401:
            raise RuntimeError("OpenAI authentication failed. Check OPENAI_API_KEY.")
        if resp.status_code == 429:
            raise RuntimeError("OpenAI rate limit hit. Wait and retry.")
        resp.raise_for_status()
        data = resp.json()
        embeddings = sorted(data["data"], key=lambda x: x["index"])
        return [e["embedding"][: self.dim] for e in embeddings]

    def to_bytes(self, vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)


class LocalModelEmbedder:
    """Local neural embedding model via sentence-transformers.

    Uses intfloat/multilingual-e5-small by default (384d) — a high-quality
    multilingual model. Runs locally on CPU or MPS. No API key needed.
    """

    name = "local"
    DEFAULT_MODEL = "intfloat/multilingual-e5-small"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = None
        self._dim = None
        self._is_e5 = "e5" in self.model_name.lower()

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._load_model()
        return self._dim

    def _load_model(self):
        if self._model is not None:
            return
        import logging

        for name in ("transformers", "sentence_transformers", "huggingface_hub"):
            logging.getLogger(name).setLevel(logging.ERROR)
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_name)
        self._dim = self._model.get_embedding_dimension()

    def _prefix_query(self, text: str) -> str:
        return f"query: {text}" if self._is_e5 else text

    def _prefix_passage(self, text: str) -> str:
        return f"passage: {text}" if self._is_e5 else text

    def embed(self, text: str) -> list[float]:
        self._load_model()
        prefixed = self._prefix_passage(text)
        vec = self._model.encode(prefixed, normalize_embeddings=True)
        return vec.tolist()

    def embed_query(self, text: str) -> list[float]:
        self._load_model()
        prefixed = self._prefix_query(text)
        vec = self._model.encode(prefixed, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        prefixed = [self._prefix_passage(t) for t in texts]
        vecs = self._model.encode(prefixed, normalize_embeddings=True, batch_size=32)
        return vecs.tolist()

    def to_bytes(self, vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)


# ---------------------------------------------------------------------------
# Cross-encoder reranker (singleton, lazy-loaded)
# ---------------------------------------------------------------------------

_reranker_instance = None


def get_reranker():
    """Lazy-load the cross-encoder reranker singleton.

    Uses cross-encoder/ms-marco-MiniLM-L-6-v2 — fast and high-quality.
    Returns None if sentence-transformers is not available.
    """
    global _reranker_instance
    if _reranker_instance is not None:
        return _reranker_instance
    try:
        from sentence_transformers import CrossEncoder

        _reranker_instance = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return _reranker_instance
    except Exception:
        return None


def select_provider(quiet: bool = False):
    """Select embedding provider based on environment configuration.

    Set MEMORY_EMBEDDING_PROVIDER to: local, openai, tfidf, or auto (default).
    """
    provider = os.environ.get("MEMORY_EMBEDDING_PROVIDER", "auto").lower()

    valid_providers = ("auto", "local", "tfidf", "openai")
    if provider not in valid_providers:
        if not quiet:
            print(
                f"Warning: unknown MEMORY_EMBEDDING_PROVIDER='{provider}'. "
                f"Valid: {', '.join(valid_providers)}. Falling back to auto.",
                file=sys.stderr,
            )
        provider = "auto"

    if provider == "auto":
        try:
            import sentence_transformers  # noqa: F401

            provider = "local"
        except ImportError:
            provider = "tfidf"

    if provider == "local":
        try:
            model_name = os.environ.get("MEMORY_EMBEDDING_MODEL", None)
            embedder = LocalModelEmbedder(model_name=model_name)
            _ = embedder.dim  # trigger lazy load
            if not quiet:
                print(
                    f"Embedding: {embedder.model_name} ({embedder.dim}d, local)",
                    file=sys.stderr,
                )
            return embedder
        except ImportError:
            if not quiet:
                print(
                    "Warning: sentence-transformers not installed. "
                    "Falling back to TF-IDF.\n"
                    "  To fix: pip install claude-vector-memory[neural]",
                    file=sys.stderr,
                )
            return EnhancedTFIDFEmbedder()
        except Exception as e:
            if not quiet:
                print(
                    f"Warning: local model failed: {e}. Falling back to TF-IDF.",
                    file=sys.stderr,
                )
            return EnhancedTFIDFEmbedder()

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            if not quiet:
                print(
                    "Warning: MEMORY_EMBEDDING_PROVIDER=openai but OPENAI_API_KEY not set. "
                    "Falling back to TF-IDF.",
                    file=sys.stderr,
                )
            return EnhancedTFIDFEmbedder()

        ok, msg = OpenAIEmbedder.validate_api_key(api_key)
        if not ok:
            if not quiet:
                print(f"Warning: {msg}. Falling back to TF-IDF.", file=sys.stderr)
            return EnhancedTFIDFEmbedder()

        model = os.environ.get("MEMORY_EMBEDDING_MODEL", "text-embedding-3-small")
        dim_str = os.environ.get("MEMORY_EMBEDDING_DIM", "1536")
        try:
            dim = int(dim_str)
        except ValueError:
            if not quiet:
                print(
                    f"Warning: MEMORY_EMBEDDING_DIM='{dim_str}' not a number. Using 1536.",
                    file=sys.stderr,
                )
            dim = 1536

        return OpenAIEmbedder(api_key, model=model, dim=dim)

    return EnhancedTFIDFEmbedder()
