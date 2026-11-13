"""Library of specialist agents.

An agent = a Hermes profile (own SOUL.md, model, skills) + a library record:
specialization, domains, complexity tier, run history, accumulated lessons.

Lifecycle:  find -> (reuse | adapt | forge) -> Kanban run -> record_run -> retrospective
            -> learn (lessons) -> evolve (rewrite the SOUL.md lessons section, version++)
            -> retire (if the agent is consistently worse than the alternatives).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from . import embed as E
from .store import connect, dlc_home, hermes_root

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,55}$")
PROFILE_PREFIX = os.environ.get("DLC_PROFILE_PREFIX", "ag-")
TIERS = ("simple", "specialist", "expert")
LESSONS_START = "<!-- dlc:lessons:start -->"
LESSONS_END = "<!-- dlc:lessons:end -->"

# Thresholds for the semantic match (cosine over normalized EmbeddingGemma vectors).
REUSE_AT = float(os.environ.get("DLC_REUSE_AT", "0.78"))
ADAPT_AT = float(os.environ.get("DLC_ADAPT_AT", "0.60"))
# Thresholds for the keyword fallback (Jaccard), used when there is no embedder.
KW_REUSE_AT, KW_ADAPT_AT = 0.45, 0.25


class LibraryError(ValueError):
    pass


# ----------------------------------------------------------------------------- helpers

def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[\w-]{3,}", text.lower())}


def _agent_text(title: str, specialty: str, domains: list[str]) -> str:
    return f"{title}. {specialty}. Domains: {', '.join(domains)}"


def _row(r) -> dict[str, Any]:
    d = dict(r)
    d.pop("embedding", None)
    d["domains"] = json.loads(d.get("domains") or "[]")
    return d


def profile_home(profile: str) -> Path:
    return hermes_root() / "profiles" / profile


def _hermes_cmd() -> list[str]:
    exe = shutil.which("hermes")
    return [exe] if exe else [sys.executable, "-m", "hermes_cli.main"]


def _run_hermes(args: list[str]) -> str:
    proc = subprocess.run(_hermes_cmd() + args, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise LibraryError(f"hermes {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def stats(conn, slug: str) -> dict[str, Any]:
    r = conn.execute(
        "SELECT COUNT(*) n, SUM(outcome='completed') ok, SUM(outcome!='completed') bad, AVG(score) avg_score "
        "FROM runs WHERE agent_slug=?", (slug,)).fetchone()
    n, ok = r["n"] or 0, r["ok"] or 0
    # Laplace smoothing: a new agent starts at 0.5, not 0 or 1.
    return {"runs": n, "completed": ok, "failed": r["bad"] or 0,
            "success_rate": round((ok + 1) / (n + 2), 3),
            "avg_score": None if r["avg_score"] is None else round(r["avg_score"], 3)}


# ----------------------------------------------------------------------------- find

def find(query: str, *, domains: Optional[list[str]] = None, tier: Optional[str] = None,
         limit: int = 5) -> dict[str, Any]:
    conn = connect()
    rows = conn.execute("SELECT * FROM agents WHERE status='active'").fetchall()
    if tier:
        rows = [r for r in rows if r["tier"] == tier]
    if not rows:
        return {"method": "none", "candidates": [], "recommendation": "forge",
                "reason": "library is empty or has no agents of this tier"}

    q_text = query + (f". Domains: {', '.join(domains)}" if domains else "")
    method = "semantic"
    try:
        qv = E.embed([q_text], kind="query")[0]
    except E.EmbedError:
        qv, method = None, "keyword"

    scored = []
    for r in rows:
        if qv is not None and r["embedding"]:
            sim = E.cosine(qv, E.from_blob(r["embedding"]))
        else:
            if method == "semantic":
                method = "mixed"
            a = _tokens(q_text)
            b = _tokens(_agent_text(r["title"], r["specialty"], json.loads(r["domains"])))
            sim = len(a & b) / (len(a | b) or 1)
        st = stats(conn, r["slug"])
        rank = sim * (0.75 + 0.25 * st["success_rate"])
        scored.append({**_row(r), "similarity": round(sim, 3), "rank": round(rank, 3), "stats": st})
    scored.sort(key=lambda x: x["rank"], reverse=True)
    top = scored[:limit]

    reuse_at, adapt_at = (REUSE_AT, ADAPT_AT) if method == "semantic" else (KW_REUSE_AT, KW_ADAPT_AT)
    best = top[0]
    if best["similarity"] >= reuse_at and best["stats"]["success_rate"] >= 0.4:
        rec, why = "reuse", f"{best['slug']} covers the task (sim={best['similarity']})"
    elif best["similarity"] >= adapt_at:
        rec, why = "adapt", (f"{best['slug']} is close but not exact: forge a narrow specialist "
                             f"with parent_slug={best['slug']}")
    else:
        rec, why = "forge", "no suitable specialist found"
    return {"method": method, "candidates": top, "recommendation": rec, "reason": why}


# ----------------------------------------------------------------------------- forge

def render_soul(title: str, specialty: str, soul: str, lessons: list[dict]) -> str:
    body = "\n".join(f"- [{l['kind']}] {l['lesson']}" for l in lessons) or "- (none yet)"
    return (f"{soul.rstrip()}\n\n## Lessons learned\n{LESSONS_START}\n"
            f"Rules distilled from past tasks. They take priority over general habits.\n{body}\n{LESSONS_END}\n")


def forge(slug: str, title: str, specialty: str, soul: str, *, domains: Optional[list[str]] = None,
          tier: str = "specialist", model: Optional[str] = None, parent_slug: Optional[str] = None,
          clone_from: Optional[str] = None, lean_skills: bool = True,
          create_profile: Optional[bool] = None) -> dict[str, Any]:
    if not SLUG_RE.match(slug):
        raise LibraryError("slug: lowercase latin letters/digits/-/_ only, max 56 chars")
    if tier not in TIERS:
        raise LibraryError(f"tier must be one of {TIERS}")
    if len(soul.strip()) < 200:
        raise LibraryError("soul is too short: a specialist needs a detailed SOUL "
                           "(role, method, quality criteria, anti-patterns). See the dlc:agent-forge skill")
    domains = domains or []
    conn = connect()
    if conn.execute("SELECT 1 FROM agents WHERE slug=?", (slug,)).fetchone():
        raise LibraryError(f"agent {slug} already exists: use learn/evolve or a different slug")
    profile = PROFILE_PREFIX + slug
    if create_profile is None:
        create_profile = os.environ.get("DLC_DRY_PROFILES", "0") != "1"

    if create_profile:
        # --description is read by the Kanban decomposer when it routes tasks across profiles.
        args = ["profile", "create", profile, "--no-alias", "--description", f"[dlc:{tier}] {title}: {specialty}"[:400]]
        args += ["--clone-from", clone_from] if clone_from else ["--clone"]
        if lean_skills:
            args.append("--no-skills")
        _run_hermes(args)
        if model:
            _run_hermes(["-p", profile, "config", "set", "model.default", model])
        _run_hermes(["-p", profile, "tools", "enable", "kanban"])

    home = profile_home(profile)
    home.mkdir(parents=True, exist_ok=True)
    (home / "SOUL.md").write_text(render_soul(title, specialty, soul, []), encoding="utf-8")
    _snapshot(slug, 1, home / "SOUL.md")

    try:
        vec = E.to_blob(E.embed([_agent_text(title, specialty, domains)])[0])
    except E.EmbedError:
        vec = None
    conn.execute(
        "INSERT INTO agents(slug,title,specialty,domains,tier,profile,model,parent_slug,embedding) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (slug, title, specialty, json.dumps(domains, ensure_ascii=False), tier, profile, model, parent_slug, vec))
    conn.commit()
    return {"slug": slug, "profile": profile, "home": str(home), "embedded": vec is not None,
            "next": f"assign Kanban tasks with --assignee {profile}"}


def _snapshot(slug: str, version: int, soul_path: Path) -> None:
    hist = dlc_home() / "history" / slug
    hist.mkdir(parents=True, exist_ok=True)
    if soul_path.exists():
        shutil.copy2(soul_path, hist / f"v{version}.SOUL.md")


# ----------------------------------------------------------------------------- learn / evolve

def by_profile(conn, profile: str):
    return conn.execute("SELECT * FROM agents WHERE profile=? OR slug=?", (profile, profile)).fetchone()


def record_run(agent: str, outcome: str, *, task_id: Optional[str] = None, board: Optional[str] = None,
               complexity: Optional[str] = None, score: Optional[float] = None,
               notes: Optional[str] = None) -> Optional[dict]:
    conn = connect()
    row = by_profile(conn, agent)
    if row is None:
        return None  # not a library agent: ignore
    conn.execute(
        "INSERT OR IGNORE INTO runs(agent_slug,task_id,board,outcome,complexity,score,notes) VALUES(?,?,?,?,?,?,?)",
        (row["slug"], task_id, board, outcome, complexity, score, notes))
    if score is not None or notes:
        conn.execute("UPDATE runs SET score=COALESCE(?,score), notes=COALESCE(?,notes) "
                     "WHERE agent_slug=? AND task_id IS ? AND outcome=?",
                     (score, notes, row["slug"], task_id, outcome))
    conn.commit()
    return {"slug": row["slug"], **stats(conn, row["slug"])}


def pending_retros(limit: int = 20) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT r.*, a.profile FROM runs r JOIN agents a ON a.slug=r.agent_slug "
        "WHERE r.retro_done=0 ORDER BY r.at LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def learn(slug: str, lesson: str, *, kind: str = "do", source_task: Optional[str] = None,
          close_retro: bool = True) -> dict:
    if kind not in ("do", "dont", "check", "context"):
        raise LibraryError("kind: do | dont | check | context")
    lesson = lesson.strip()
    if len(lesson) < 15:
        raise LibraryError("lesson is too vague: state a concrete, checkable rule")
    conn = connect()
    row = by_profile(conn, slug)
    if row is None:
        raise LibraryError(f"no agent {slug}")
    dup = conn.execute("SELECT id FROM lessons WHERE agent_slug=? AND lower(lesson)=lower(?)",
                       (row["slug"], lesson)).fetchone()
    if not dup:
        conn.execute("INSERT INTO lessons(agent_slug,lesson,kind,source_task) VALUES(?,?,?,?)",
                     (row["slug"], lesson, kind, source_task))
    if close_retro and source_task:
        conn.execute("UPDATE runs SET retro_done=1 WHERE agent_slug=? AND task_id=?", (row["slug"], source_task))
    conn.commit()
    pending = conn.execute("SELECT COUNT(*) FROM lessons WHERE agent_slug=? AND applied=0",
                           (row["slug"],)).fetchone()[0]
    return {"slug": row["slug"], "duplicate": bool(dup), "unapplied_lessons": pending}


def close_retro(slug: str, task_id: str) -> None:
    conn = connect()
    row = by_profile(conn, slug)
    if row:
        conn.execute("UPDATE runs SET retro_done=1 WHERE agent_slug=? AND task_id=?", (row["slug"], task_id))
        conn.commit()


def evolve(slug: str, *, drop_lesson_ids: Optional[list[int]] = None, max_lessons: int = 25) -> dict:
    """Rewrite the lessons section of SOUL.md. Previous version -> dlc/history/<slug>/vN.SOUL.md."""
    conn = connect()
    row = by_profile(conn, slug)
    if row is None:
        raise LibraryError(f"no agent {slug}")
    if drop_lesson_ids:
        conn.executemany("DELETE FROM lessons WHERE agent_slug=? AND id=?",
                         [(row["slug"], i) for i in drop_lesson_ids])
    lessons = [dict(r) for r in conn.execute(
        "SELECT * FROM lessons WHERE agent_slug=? ORDER BY id DESC LIMIT ?", (row["slug"], max_lessons))]
    soul_path = profile_home(row["profile"]) / "SOUL.md"
    current = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    _snapshot(row["slug"], row["version"], soul_path)

    block = "\n".join(f"- [{l['kind']}] {l['lesson']}" for l in reversed(lessons)) or "- (none yet)"
    new_block = f"{LESSONS_START}\nRules distilled from past tasks. They take priority over general habits.\n{block}\n{LESSONS_END}"
    if LESSONS_START in current and LESSONS_END in current:
        pre, rest = current.split(LESSONS_START, 1)
        post = rest.split(LESSONS_END, 1)[1]
        updated = pre + new_block + post
    else:
        updated = current.rstrip() + "\n\n## Lessons learned\n" + new_block + "\n"
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(updated, encoding="utf-8")
    conn.execute("UPDATE lessons SET applied=1 WHERE agent_slug=?", (row["slug"],))
    conn.execute("UPDATE agents SET version=version+1, updated_at=datetime('now') WHERE slug=?", (row["slug"],))
    conn.commit()
    return {"slug": row["slug"], "version": row["version"] + 1, "lessons_in_soul": len(lessons),
            "soul": str(soul_path)}


def retire(slug: str, reason: str, *, replaced_by: Optional[str] = None) -> dict:
    conn = connect()
    row = by_profile(conn, slug)
    if row is None:
        raise LibraryError(f"no agent {slug}")
    conn.execute("UPDATE agents SET status='retired', updated_at=datetime('now') WHERE slug=?", (row["slug"],))
    conn.execute("INSERT INTO lessons(agent_slug,lesson,kind) VALUES(?,?, 'context')",
                 (row["slug"], f"RETIRED: {reason}" + (f" -> {replaced_by}" if replaced_by else "")))
    conn.commit()
    return {"slug": row["slug"], "status": "retired", "profile_kept": row["profile"]}


def list_agents(status: str = "active") -> list[dict]:
    conn = connect()
    q = "SELECT * FROM agents" + ("" if status == "all" else " WHERE status=?")
    rows = conn.execute(q + " ORDER BY slug", () if status == "all" else (status,)).fetchall()
    return [{**_row(r), "stats": stats(conn, r["slug"])} for r in rows]
