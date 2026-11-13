"""Local embeddings over an OpenAI-compatible /v1/embeddings endpoint.

Default: Ollama + EmbeddingGemma (Google, 768 dims, runs locally).
  DLC_EMBED_URL   = http://localhost:11434/v1
  DLC_EMBED_MODEL = embeddinggemma
  DLC_EMBED_KEY   = (optional, for non-local endpoints)

EmbeddingGemma was trained with task prefixes; without them retrieval quality drops,
so queries and documents get different prefixes.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from array import array
from typing import Sequence

QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "


class EmbedError(RuntimeError):
    pass


def model_name() -> str:
    return os.environ.get("DLC_EMBED_MODEL", "embeddinggemma")


def _uses_gemma_prefixes() -> bool:
    flag = os.environ.get("DLC_EMBED_PREFIXES")
    if flag is not None:
        return flag.lower() in {"1", "true", "yes"}
    return "gemma" in model_name().lower()


def embed(texts: Sequence[str], *, kind: str = "doc") -> list[list[float]]:
    if not texts:
        return []
    if _uses_gemma_prefixes():
        prefix = QUERY_PREFIX if kind == "query" else DOC_PREFIX
        texts = [prefix + t for t in texts]
    url = os.environ.get("DLC_EMBED_URL", "http://localhost:11434/v1").rstrip("/") + "/embeddings"
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("DLC_EMBED_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    out: list[list[float]] = []
    batch = int(os.environ.get("DLC_EMBED_BATCH", "32"))
    for i in range(0, len(texts), batch):
        body = json.dumps({"model": model_name(), "input": list(texts[i:i + batch])}).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            raise EmbedError(f"embedding endpoint {url} failed: {exc}") from exc
        out.extend(_normalize(d["embedding"]) for d in sorted(data["data"], key=lambda d: d["index"]))
    return out


def _normalize(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def to_blob(v: Sequence[float]) -> bytes:
    return array("f", v).tobytes()


def from_blob(b: bytes) -> array:
    a = array("f")
    a.frombytes(b)
    return a


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # Both vectors are normalized at write time, so the dot product is enough.
    return sum(x * y for x, y in zip(a, b))
