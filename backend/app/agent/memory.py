"""Long-term (pgvector) memory + rolling per-session summary."""
from __future__ import annotations

import json
import logging
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChatMessage, LongTermMemory
from .llm import build_embeddings

log = logging.getLogger("agrisense.agent.memory")

_embeddings = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = build_embeddings()
    return _embeddings


async def save_memory(db: AsyncSession, user_id: int, content: str) -> None:
    """Embed ``content`` and persist it as a user-scoped memory row."""
    content = (content or "").strip()
    if not content:
        return
    vector = await _get_embeddings().aembed_query(content)
    row = LongTermMemory(user_id=user_id, content=content, embedding=vector)
    db.add(row)
    await db.commit()


async def recall_memory(
    db: AsyncSession, user_id: int, query: str, k: int
) -> List[str]:
    """Return up to ``k`` memories nearest to ``query`` by cosine distance."""
    query = (query or "").strip()
    if not query:
        return []
    vector = await _get_embeddings().aembed_query(query)
    stmt = (
        select(LongTermMemory.content)
        .where(LongTermMemory.user_id == user_id)
        .order_by(LongTermMemory.embedding.cosine_distance(vector))
        .limit(k)
    )
    result = await db.execute(stmt)
    return [row for row in result.scalars().all()]


async def refresh_summary(
    db: AsyncSession, session, cutoff_id: int, model
) -> None:
    """Roll older messages (id <= cutoff_id) into a dense <=200 word summary.

    Best-effort: prepends the previous summary and swallows any error.
    """
    try:
        if cutoff_id <= (session.summary_upto_id or 0):
            return
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session.id,
                ChatMessage.id > (session.summary_upto_id or 0),
                ChatMessage.id <= cutoff_id,
            )
            .order_by(ChatMessage.id)
        )
        result = await db.execute(stmt)
        msgs = result.scalars().all()
        if not msgs:
            return

        convo = "\n".join(f"{m.role}: {m.content}" for m in msgs)
        prompt = [
            SystemMessage(
                content=(
                    "You maintain a running summary of an agriculture "
                    "assistant conversation. Produce a dense summary of at "
                    "most 200 words that preserves facts, user preferences, "
                    "crops, locations, and decisions. Merge the previous "
                    "summary with the new messages; do not lose earlier facts."
                )
            ),
            HumanMessage(
                content=(
                    f"Previous summary:\n{session.summary or '(none)'}\n\n"
                    f"New messages:\n{convo}"
                )
            ),
        ]
        resp = await model.ainvoke(prompt)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        session.summary = text.strip()
        session.summary_upto_id = cutoff_id
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Automatic memory extraction — no tool call required.
#
# ``save_memory``/``recall_memory`` remain available as explicit tools, but
# gating ALL long-term memory on the primary model choosing to invoke one is
# fragile (a model that never calls it means the farmer is never remembered).
# Consumer assistants (ChatGPT/Gemini) extract durable facts from ordinary
# conversation in the background; this mirrors that — every turn, best-effort,
# swallowing all errors so it can never break the visible reply.
# --------------------------------------------------------------------------- #
_EXTRACT_PROMPT = (
    "You extract durable, personal facts about a farmer from one turn of an "
    "agricultural-advisor chat, for long-term memory across FUTURE sessions.\n"
    "Extract things like: their name, family, occupation, long-term goals, "
    "communication preferences, recurring experiences or opinions.\n"
    "Do NOT extract: structured farm data tracked elsewhere (location, area, "
    "soil, water source, budget, season, crop pick for the CURRENT plan), "
    "weather values, one-off arithmetic, or anything already in the 'Known "
    "facts' list below (even if reworded).\n"
    "Reply with ONLY a JSON array of short third-person sentences, e.g. "
    '["The farmer\'s name is Karim."]. If nothing new and durable, reply '
    "with exactly []."
)

DUPLICATE_DISTANCE_THRESHOLD = 0.15


async def _is_duplicate(db: AsyncSession, user_id: int, vector, threshold: float) -> bool:
    stmt = (
        select(LongTermMemory.embedding.cosine_distance(vector))
        .where(LongTermMemory.user_id == user_id)
        .order_by(LongTermMemory.embedding.cosine_distance(vector))
        .limit(1)
    )
    nearest = (await db.execute(stmt)).scalar_one_or_none()
    return nearest is not None and nearest < threshold


def _parse_fact_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        facts = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(facts, list):
        return []
    return [str(f).strip() for f in facts if str(f).strip()]


async def auto_extract_memories(
    db: AsyncSession,
    user_id: int,
    model,
    user_text: str,
    assistant_text: str,
    known: List[str],
) -> List[str]:
    """Best-effort: pull durable personal facts out of one turn and save them.

    Runs unconditionally (no tool call, no farmer intent needed) so memory
    keeps working even when the primary model never calls ``save_memory``.
    Deduplicates against existing memories by embedding distance so the same
    fact isn't re-saved every turn. Returns the facts actually saved; never
    raises.
    """
    saved: List[str] = []
    try:
        known_blob = "\n".join(f"- {k}" for k in known) or "(none yet)"
        prompt = [
            SystemMessage(content=_EXTRACT_PROMPT),
            HumanMessage(
                content=(
                    f"Known facts about this farmer so far:\n{known_blob}\n\n"
                    f"Farmer said: {user_text}\n"
                    f"Assistant replied: {assistant_text}"
                )
            ),
        ]
        resp = await model.ainvoke(prompt)
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        for fact in _parse_fact_list(raw):
            if len(fact) > 400:
                continue
            vector = await _get_embeddings().aembed_query(fact)
            if await _is_duplicate(db, user_id, vector, DUPLICATE_DISTANCE_THRESHOLD):
                continue
            row = LongTermMemory(user_id=user_id, content=fact, embedding=vector)
            db.add(row)
            await db.commit()
            saved.append(fact)
    except Exception:
        log.warning("auto_extract_memories failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
    return saved
