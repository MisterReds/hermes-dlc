"""Hermes DLC plugin: planning, specialist agent library, local RAG.

Enable it: plugins.enabled: [dlc] in ~/.hermes/config.yaml (and in each profile's config.yaml:
profiles created by `--clone` copy it).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
_SKILLS = Path(__file__).parent / "skills"

ORCHESTRATOR_PROTOCOL = """\
[DLC] Work protocol for non-trivial tasks:
1. Triage first (skill dlc:task-planning): complexity trivial/simple/moderate/complex/novel.
   trivial/simple -> do it yourself, no Kanban. moderate+ -> plan, decompose, Kanban.
2. For each subtask: dlc_agent_find on the COMPETENCE it needs. reuse -> assign that profile;
   adapt/forge -> dlc_agent_forge (skill dlc:agent-forge). Do not hand narrow work to generalists.
3. Every subtask needs a definition of done and a check; complex ones get review (kanban review).
4. After tasks finish: dlc_retro_pending -> retrospective (skill dlc:retrospective) ->
   dlc_agent_learn -> dlc_agent_evolve. The library has to get better with every task.
5. Project knowledge: dlc_rag_search before guessing; dlc_rag_ingest for new docs."""

WORKER_PROTOCOL = """\
[DLC] You are a library specialist working a Kanban task. Stay inside your specialization.
If the task is outside your competence, kanban_block with an exact description of the competence
needed (the orchestrator will forge a specialist). Before kanban_complete: self-check against the
definition of done. In the summary add a 'Lessons:' section with 0-3 concrete rules that would have
made this task faster or more accurate (they feed the retrospective)."""


def _prompt_section(_info) -> str:
    if os.environ.get("HERMES_KANBAN_TASK"):
        return WORKER_PROTOCOL
    text = ORCHESTRATOR_PROTOCOL
    try:
        from .library import pending_retros
        n = len(pending_retros(50))
        if n:
            text += f"\n[DLC] Pending retrospectives: {n}. Run them when there is a pause."
    except Exception as exc:  # the prompt must never break because of the DB
        logger.debug("dlc: pending_retros failed: %s", exc)
    return text


def _on_kanban(outcome: str):
    def hook(**kw) -> None:
        assignee = kw.get("assignee")
        if not assignee:
            return
        try:
            from .library import record_run
            notes = kw.get("summary") or kw.get("reason")
            record_run(assignee, outcome, task_id=kw.get("task_id"), board=kw.get("board"),
                       notes=(str(notes)[:2000] if notes else None))
        except Exception as exc:
            logger.warning("dlc: failed to record kanban %s for %s: %s", outcome, assignee, exc)
    return hook


def _slash_agents(raw_args: str = "") -> str:
    from .library import list_agents
    status = (raw_args or "").strip() or "active"
    rows = list_agents(status if status in {"active", "retired", "all"} else "active")
    if not rows:
        return "Agent library is empty."
    lines = [f"{'slug':28} {'tier':10} {'v':>3} {'runs':>5} {'ok%':>5}  specialty"]
    for a in rows:
        st = a["stats"]
        lines.append(f"{a['slug']:28} {a['tier']:10} {a['version']:>3} {st['runs']:>5} "
                     f"{int(st['success_rate'] * 100):>4}%  {a['specialty'][:70]}")
    return "\n".join(lines)


def register(ctx) -> None:
    from .tools import TOOLS

    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(name=name, toolset="dlc", schema=schema, handler=handler, emoji=emoji)

    ctx.register_hook("kanban_task_completed", _on_kanban("completed"))
    ctx.register_hook("kanban_task_blocked", _on_kanban("blocked"))

    for skill_dir in sorted(p for p in _SKILLS.iterdir() if (p / "SKILL.md").exists()):
        ctx.register_skill(skill_dir.name, skill_dir / "SKILL.md")

    ctx.register_system_prompt_section("dlc.protocol", _prompt_section, max_chars=2000)
    ctx.register_command("agents", _slash_agents, description="DLC agent library", args_hint="[active|retired|all]")
