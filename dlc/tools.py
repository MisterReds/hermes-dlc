"""Tool schemas and handlers. Contract: handler(args: dict, **kw) -> JSON string."""

from __future__ import annotations

import json
from typing import Any, Callable

from . import library as L
from . import rag as R
from .embed import EmbedError


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, **(data if isinstance(data, dict) else {"result": data})},
                      ensure_ascii=False, default=str)


def _guard(fn: Callable[[dict], Any]) -> Callable[..., str]:
    def handler(args: dict, **_kw) -> str:
        try:
            return _ok(fn(args or {}))
        except (L.LibraryError, ValueError, EmbedError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    handler.__name__ = fn.__name__
    return handler


def _s(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    params: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


_TIER = {"type": "string", "enum": list(L.TIERS),
         "description": "simple: generalist is enough; specialist: narrow skill; expert: rare competence + strong model"}
_DOMAINS = {"type": "array", "items": {"type": "string"}, "description": "Domain tags: stack, field, artifact type"}

TOOLS: list[tuple[str, dict, Callable, str]] = [
    ("dlc_agent_find", _schema(
        "dlc_agent_find",
        "Find a specialist agent in the library for a subtask. Returns candidates with similarity and "
        "success stats, plus a recommendation: reuse | adapt | forge. Call it BEFORE assigning any "
        "Kanban subtask. Describe the required competence, not the task text.",
        {"need": _s("What competence the subtask needs: field, stack, artifact type, quality criteria"),
         "domains": _DOMAINS, "tier": _TIER, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["need"]),
     _guard(lambda a: L.find(a["need"], domains=a.get("domains"), tier=a.get("tier"),
                             limit=int(a.get("limit", 5)))), "🔎"),

    ("dlc_agent_forge", _schema(
        "dlc_agent_forge",
        "Create a new specialist agent: a Hermes profile with a detailed SOUL.md, Kanban enabled, and a "
        "library record. Use when dlc_agent_find returned forge/adapt. Write the SOUL using the "
        "dlc:agent-forge skill: role, method, quality criteria, anti-patterns, definition of done.",
        {"slug": _s("Short id, e.g. postgres-migrations"), "title": _s("Role name"),
         "specialty": _s("1-3 sentences: what exactly it does better than a generalist"),
         "soul": _s("Full SOUL.md text (Markdown, >=200 characters)"),
         "domains": _DOMAINS, "tier": _TIER,
         "model": _s("Optional: model for this agent (strong for expert, cheap for simple)"),
         "parent_slug": _s("Agent it derives from (for adapt)"),
         "clone_from": _s("Profile to clone config/keys from; defaults to the active one"),
         "lean_skills": {"type": "boolean", "description": "Do not copy the bundled skill set (default true)"}},
        ["slug", "title", "specialty", "soul"]),
     _guard(lambda a: L.forge(a["slug"], a["title"], a["specialty"], a["soul"], domains=a.get("domains"),
                              tier=a.get("tier", "specialist"), model=a.get("model"),
                              parent_slug=a.get("parent_slug"), clone_from=a.get("clone_from"),
                              lean_skills=a.get("lean_skills", True))), "🛠"),

    ("dlc_agent_list", _schema(
        "dlc_agent_list", "Agent library with stats.",
        {"status": {"type": "string", "enum": ["active", "retired", "all"]}}),
     _guard(lambda a: {"agents": L.list_agents(a.get("status", "active"))}), "📚"),

    ("dlc_agent_learn", _schema(
        "dlc_agent_learn",
        "Record a lesson for an agent after a retrospective. A lesson is a concrete, checkable rule "
        "('do X when Y', 'never Z', 'check W before handing off'), not a general wish.",
        {"agent": _s("slug or agent profile"), "lesson": _s("The rule"),
         "kind": {"type": "string", "enum": ["do", "dont", "check", "context"]},
         "source_task": _s("Kanban task id the lesson came from (closes the retrospective)")},
        ["agent", "lesson"]),
     _guard(lambda a: L.learn(a["agent"], a["lesson"], kind=a.get("kind", "do"),
                              source_task=a.get("source_task"))), "🧠"),

    ("dlc_agent_evolve", _schema(
        "dlc_agent_evolve",
        "Bake accumulated lessons into the agent's SOUL.md (new version, old one goes to history). "
        "Call after 1+ new lessons. drop_lesson_ids removes stale or contradictory lessons.",
        {"agent": _s("slug or profile"),
         "drop_lesson_ids": {"type": "array", "items": {"type": "integer"}}},
        ["agent"]),
     _guard(lambda a: L.evolve(a["agent"], drop_lesson_ids=a.get("drop_lesson_ids"))), "🧬"),

    ("dlc_agent_retire", _schema(
        "dlc_agent_retire", "Take an agent out of rotation (the profile is kept).",
        {"agent": _s("slug or profile"), "reason": _s("Why"), "replaced_by": _s("Replacement slug")},
        ["agent", "reason"]),
     _guard(lambda a: L.retire(a["agent"], a["reason"], replaced_by=a.get("replaced_by"))), "🪦"),

    ("dlc_run_record", _schema(
        "dlc_run_record",
        "Record a result evaluation for a run (score 0..1, notes). Kanban hooks record the "
        "completed/blocked fact automatically; this adds the quality assessment from review.",
        {"agent": _s("slug or profile"), "task_id": _s("Kanban task id"),
         "outcome": {"type": "string", "enum": ["completed", "blocked", "failed", "rework"]},
         "score": {"type": "number", "minimum": 0, "maximum": 1},
         "complexity": {"type": "string", "enum": ["trivial", "simple", "moderate", "complex", "novel"]},
         "notes": _s("What was good or bad")},
        ["agent", "outcome"]),
     _guard(lambda a: L.record_run(a["agent"], a["outcome"], task_id=a.get("task_id"),
                                   complexity=a.get("complexity"), score=a.get("score"),
                                   notes=a.get("notes")) or {"ignored": "not a library agent"}), "📝"),

    ("dlc_retro_pending", _schema(
        "dlc_retro_pending",
        "Runs that have not had a retrospective yet. Use with the dlc:retrospective skill.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 50},
         "close": {"type": "object", "properties": {"agent": {"type": "string"}, "task_id": {"type": "string"}},
                   "description": "Close the retrospective without a lesson (nothing to learn)"}}),
     _guard(lambda a: (L.close_retro(a["close"]["agent"], a["close"]["task_id"]) or {"closed": a["close"]})
            if a.get("close") else {"pending": L.pending_retros(int(a.get("limit", 20)))}), "🔁"),

    ("dlc_rag_ingest", _schema(
        "dlc_rag_ingest",
        "Index a file/directory or text into the local knowledge base (local embeddings).",
        {"collection": _s("Collection name: project, docs, specs..."),
         "path": _s("File or directory"), "text": _s("Or raw text"), "source": _s("Source label for text")},
        ["collection"]),
     _guard(lambda a: R.ingest(a["collection"], path=a.get("path"), text=a.get("text"),
                               source=a.get("source"))), "📥"),

    ("dlc_rag_search", _schema(
        "dlc_rag_search",
        "Semantic search over the local knowledge base. Without query, lists collections.",
        {"query": _s("What to find"), "collection": _s("Limit to a collection"),
         "k": {"type": "integer", "minimum": 1, "maximum": 20}}),
     _guard(lambda a: R.search(a["query"], collection=a.get("collection"), k=int(a.get("k", 6)))
            if a.get("query") else {"collections": R.collections()}), "📖"),
]
