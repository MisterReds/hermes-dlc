"""Tests without Hermes: fake OpenAI-compatible embedder (bag-of-words hashing) on a local port."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

DIM = 256


def _vec(text: str) -> list[float]:
    v = [0.0] * DIM
    for tok in re.findall(r"\w{3,}", text.lower()):
        v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class _H(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        data = [{"index": i, "embedding": _vec(t)} for i, t in enumerate(body["input"])]
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("DLC_HOME", str(tmp_path / "dlc"))
    monkeypatch.setenv("HERMES_ROOT", str(tmp_path / "hermes"))
    monkeypatch.setenv("DLC_EMBED_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("DLC_EMBED_MODEL", "fake")
    monkeypatch.setenv("DLC_DRY_PROFILES", "1")
    yield tmp_path
    srv.shutdown()


SOUL = "# PG migrations\n" + ("Ты специалист по миграциям PostgreSQL без простоя. " * 10)


def test_forge_find_learn_evolve(env):
    from dlc import library as L

    assert L.find("anything")["recommendation"] == "forge"
    r = L.forge("pg-migrations", "PostgreSQL migrations", "zero downtime postgresql schema migrations alembic",
                SOUL, domains=["postgresql", "alembic"], tier="expert")
    assert r["embedded"] and r["profile"] == "ag-pg-migrations"

    f = L.find("postgresql schema migrations zero downtime", domains=["alembic"])
    assert f["method"] == "semantic" and f["candidates"][0]["slug"] == "pg-migrations"
    assert f["recommendation"] in {"reuse", "adapt"}
    assert L.find("react landing page animation design")["recommendation"] == "forge"

    assert L.record_run("ag-pg-migrations", "completed", task_id="t1")["runs"] == 1
    assert L.record_run("ag-pg-migrations", "completed", task_id="t1")["runs"] == 1  # idempotent
    assert L.record_run("unknown-profile", "completed", task_id="t2") is None
    assert len(L.pending_retros()) == 1

    with pytest.raises(L.LibraryError):
        L.learn("pg-migrations", "be careful")
    out = L.learn("pg-migrations", "Backfill NOT NULL columns in 10k batches before adding the constraint",
                  kind="do", source_task="t1")
    assert out["unapplied_lessons"] == 1 and not L.pending_retros()

    ev = L.evolve("pg-migrations")
    assert ev["version"] == 2
    soul = open(ev["soul"], encoding="utf-8").read()
    assert "Backfill NOT NULL" in soul and soul.count(L.LESSONS_START) == 1
    L.learn("pg-migrations", "Run alembic upgrade head on an empty DB before handoff", kind="check")
    soul = open(L.evolve("pg-migrations")["soul"], encoding="utf-8").read()
    assert "alembic upgrade head" in soul and soul.count(L.LESSONS_START) == 1
    assert (env / "dlc" / "history" / "pg-migrations" / "v2.SOUL.md").exists()

    L.retire("pg-migrations", "test")
    assert L.list_agents("active") == []


def test_forge_validation(env):
    from dlc import library as L
    with pytest.raises(L.LibraryError):
        L.forge("Bad Slug", "x", "y", SOUL)
    with pytest.raises(L.LibraryError):
        L.forge("ok-slug", "x", "y", "short soul")


def test_keyword_fallback(env, monkeypatch):
    from dlc import library as L
    L.forge("figma-react", "Figma to React", "figma react components accessibility", SOUL, domains=["react"])
    monkeypatch.setenv("DLC_EMBED_URL", "http://127.0.0.1:9/v1")  # embedder unavailable
    f = L.find("figma react components")
    assert f["method"] in {"keyword", "mixed"} and f["candidates"][0]["slug"] == "figma-react"


def test_rag(env):
    from dlc import rag as R
    docs = env / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("Deploy goes through ArgoCD with canary releases.\n\nRollback via argo rollouts.")
    (docs / "b.md").write_text("The frontend is built with Vite and React Router.")
    (docs / "skip.bin").write_bytes(b"\x00\x01")
    out = R.ingest("proj", path=str(docs))
    assert out["documents"] == 2 and out["chunks"] >= 2
    hits = R.search("how do we deploy canary ArgoCD", collection="proj")["hits"]
    assert hits[0]["source"].endswith("a.md")
    R.ingest("proj", path=str(docs))  # re-ingest replaces, does not duplicate
    assert R.collections()[0]["chunks"] == out["chunks"]


def test_chunking():
    from dlc.rag import chunk
    parts = chunk("x" * 3000, size=1200, overlap=200)
    assert all(len(p) <= 1200 for p in parts) and len(parts) == 3


def test_tools_contract(env):
    from dlc.tools import TOOLS
    names = {t[0] for t in TOOLS}
    assert len(names) == len(TOOLS)
    for name, schema, handler, _ in TOOLS:
        assert schema["name"] == name and schema["parameters"]["type"] == "object"
    h = dict((t[0], t[2]) for t in TOOLS)
    res = json.loads(h["dlc_agent_forge"]({"slug": "X", "title": "t", "specialty": "s", "soul": "s"}))
    assert res["ok"] is False
    assert json.loads(h["dlc_agent_list"]({}))["agents"] == []
    assert "collections" in json.loads(h["dlc_rag_search"]({}))
