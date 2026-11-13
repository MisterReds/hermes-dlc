"""Local RAG: documents -> chunks -> local embeddings -> SQLite -> brute-force cosine.

Brute force is enough up to ~100k chunks. Above that, move to sqlite-vec/LanceDB (ROADMAP, phase 4).
This is a knowledge base (docs, specs, code, notes); Honcho is memory about the user and dialogues.
They do not overlap.
"""

from __future__ import annotations

import heapq
import re
from pathlib import Path
from typing import Optional

from . import embed as E
from .store import connect

TEXT_EXT = {".md", ".txt", ".rst", ".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".kt", ".yaml",
            ".yml", ".toml", ".json", ".sql", ".sh", ".html", ".css", ".c", ".cpp", ".h", ".cs", ".php"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"}


def chunk(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Split on paragraphs, packing them up to `size`; split overlong paragraphs with overlap."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(p) > size:
            if buf:
                out.append(buf)
                buf = ""
            step = size - overlap
            out.extend(p[i:i + size] for i in range(0, len(p), step))
            continue
        if len(buf) + len(p) + 2 > size and buf:
            out.append(buf)
            buf = buf[-overlap:] + "\n\n" + p if overlap else p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        out.append(buf)
    return out


def _iter_files(root: Path, max_files: int):
    if root.is_file():
        yield root
        return
    n = 0
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in TEXT_EXT and p.stat().st_size < 2_000_000:
            yield p
            n += 1
            if n >= max_files:
                return


def ingest(collection: str, *, path: Optional[str] = None, text: Optional[str] = None,
           source: Optional[str] = None, replace: bool = True, max_files: int = 2000) -> dict:
    if not (path or text):
        raise ValueError("pass path or text")
    docs: list[tuple[str, str]] = []
    if text:
        docs.append((source or "inline", text))
    if path:
        root = Path(path).expanduser()
        if not root.exists():
            raise ValueError(f"{root} does not exist")
        for f in _iter_files(root, max_files):
            try:
                docs.append((str(f), f.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    conn = connect()
    model = E.model_name()
    total = 0
    for src, body in docs:
        pieces = chunk(body)
        if not pieces:
            continue
        vecs = E.embed(pieces, kind="doc")
        if replace:
            conn.execute("DELETE FROM chunks WHERE collection=? AND source=?", (collection, src))
        conn.executemany(
            "INSERT INTO chunks(collection,source,ord,text,embedding,model) VALUES(?,?,?,?,?,?)",
            [(collection, src, i, t, E.to_blob(v), model) for i, (t, v) in enumerate(zip(pieces, vecs))])
        conn.commit()
        total += len(pieces)
    return {"collection": collection, "documents": len(docs), "chunks": total, "model": model}


def search(query: str, *, collection: Optional[str] = None, k: int = 6, min_score: float = 0.0) -> dict:
    conn = connect()
    model = E.model_name()
    qv = E.embed([query], kind="query")[0]
    sql = "SELECT id,collection,source,ord,text,embedding FROM chunks WHERE model=?"
    args: list = [model]
    if collection:
        sql += " AND collection=?"
        args.append(collection)
    best = heapq.nlargest(
        k, ((E.cosine(qv, E.from_blob(r["embedding"])), r) for r in conn.execute(sql, args)),
        key=lambda x: x[0])
    hits = [{"score": round(s, 4), "collection": r["collection"], "source": r["source"],
             "chunk": r["ord"], "text": r["text"]} for s, r in best if s >= min_score]
    return {"query": query, "model": model, "hits": hits}


def collections() -> list[dict]:
    conn = connect()
    return [dict(r) for r in conn.execute(
        "SELECT collection, COUNT(*) chunks, COUNT(DISTINCT source) sources, model FROM chunks "
        "GROUP BY collection, model ORDER BY collection")]
