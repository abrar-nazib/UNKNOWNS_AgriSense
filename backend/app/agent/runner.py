"""Agent turn runner: orchestration only.

Message construction/replay/persistence-mapping lives in ``messages.py``
(separated by type: System / Human / AI tool_calls / Tool responses); this
module drives the graph and yields contract SSE event dicts.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..logging_setup import trunc
from ..models import ChatMessage, ChatSession, User
from ..schemas import serialize_message
from . import memory as memory_mod
from .graph import build_graph
from .llm import build_chat_model
from .messages import (
    build_system_messages,
    fill_trace_result,
    history_to_lc_messages,
    text_of,
    tool_call_traces,
)
from .tools import (
    build_czis_tools,
    build_farm_tools,
    build_finance_tool,
    build_memory_tools,
    build_patterns_tool,
    build_soil_tool,
    build_static_tools,
    build_weather_tool,
)

log = logging.getLogger("agrisense.agent")

SYSTEM_PROMPT = (
    "You are AgriSense, an expert agricultural advisor for Bangladeshi "
    "farmers. Give practical, accurate, concise advice on crops, soil, "
    "pests, weather, irrigation, and markets.\n"
    "\n"
    "LANGUAGE: pick the reply language from the farmer's LAST message ONLY "
    "(not earlier turns; switch immediately when they switch):\n"
    "- Bengali script (বাংলা) -> reply in Bengali.\n"
    "- Banglish (Bengali written in Latin letters, e.g. 'amar jomi ase') -> "
    "reply in Bengali script.\n"
    "- English -> reply in English.\n"
    "- Mixed -> use the dominant language of that message (Banglish counts "
    "as Bengali).\n"
    "\n"
    "FARM PROFILE & INTAKE (slot-filling):\n"
    "- At the start of a planning conversation call get_farm_profile to see "
    "what is already known. NEVER re-ask something already saved.\n"
    "- Whenever the farmer states a fact about their farm (place, size, "
    "soil, water, budget, season, previous crop, preferences), immediately "
    "save it with update_farm_profile. Save only what they explicitly said "
    "— never guess or infer values.\n"
    "- SIX fields are MANDATORY before any crop recommendation or plan: "
    "location, farm_size, soil_type, water_availability, budget, season "
    "(see missing_required_fields). You MUST NOT recommend crops, "
    "varieties, fertilizer plans or profits while ANY of them is missing — "
    "collect them first. Ask for missing ones with ONE or at most two "
    "targeted questions per turn — do not interrogate with a long list.\n"
    "- SOIL: the profile auto-fills soil from the national survey for the "
    "farm's upazila (soil_source=survey_default_confirm_with_farmer — an "
    "upazila-level DEFAULT). When you see that source, state the assumed "
    "soil and ask the farmer to confirm it; their statement overrides it. "
    "Use get_soil_context for the full survey breakdown (land type, "
    "drainage, pH). If soil_type is in missing_required_fields (no survey "
    "for that upazila), ask the farmer for their soil (sandy/loam/clay) "
    "and save it — never guess.\n"
    "- Land units: bigha and kani vary by region. If the farmer gives such "
    "a unit, ask how many shotok it is locally when practical; if they "
    "confirm, pass local_unit_factor_decimal. If a conversion was ASSUMED "
    "(see warnings), tell the farmer which assumption was used.\n"
    "- Relay any warnings from update_farm_profile (e.g. implausible "
    "area/budget) and confirm with the farmer before planning.\n"
    "- Once all required fields are present, summarize the profile in the "
    "farmer's language and confirm it is correct before recommending.\n"
    "\n"
    "MULTIPLE FARMS: one farmer can own several farms; every profile fact, "
    "plan and recommendation applies to the ACTIVE farm only.\n"
    "- The registered address only prefills the FIRST farm's location.\n"
    "- If the farmer mentions land in a different place or another field "
    "('আমার নওগাঁর জমি', 'my other plot'), call list_farms: if it matches an "
    "existing farm, select_farm it; otherwise create_farm — never overwrite "
    "the current farm's location with a different field's.\n"
    "- When it is unclear WHICH farm the farmer means, ask them to choose "
    "(name the farms from list_farms) before saving facts or advising.\n"
    "- A NEWLY created farm starts empty: collect ALL six mandatory fields "
    "for it (soil via get_soil_context) before giving any guidance on it.\n"
    "\n"
    "DATE & TIME: the CURRENT Bangladesh date-time is injected into the "
    "system context every turn — that value is authoritative. Your training "
    "data is stale: NEVER state or assume a date/year from memory (e.g. "
    "2024). All season timing, sowing windows, forecast dates and \"today\" "
    "references MUST use the injected current date (or get_current_time for "
    "a precise timestamp).\n"
    "\n"
    "TOOL PROTOCOL: tools are invoked ONLY through native function calls. "
    "NEVER write text that looks like a tool call or trace (e.g. '[tool "
    "get_weather ... -> ...]') in a reply — such text is not executed and "
    "would be shown to the farmer verbatim. If you need data, actually call "
    "the tool and wait for its result.\n"
    "\n"
    "GROUNDING RULES:\n"
    "- Weather: ALWAYS call get_weather for anything weather-related. Only "
    "cite values the tool returned. If it reports WEATHER_UNAVAILABLE, say "
    "live weather is unavailable — never invent forecast numbers. Forecasts "
    "reach at most 16 days ahead; beyond that, do not state daily weather. "
    "For PAST weather ('how much rain fell last week?') pass past_days (up "
    "to 92) — rows marked kind=past are recorded values; cite them as such "
    "and never guess historical weather either.\n"
    "- Explain recommendations by naming the specific inputs behind them "
    "(the farmer's stated facts and retrieved data).\n"
    "- Finance: whenever the farmer asks about cost, profit, revenue, ROI or "
    "break-even for a crop, call calculate_financials — NEVER compute or "
    "state these numbers yourself. Pass crop_id+variety_id (from "
    "czis_crop_context) when you have them so fertilizer cost is included "
    "from the real CZIS dose; without them fertilizer cost is omitted (say "
    "so). Present the itemized cost breakdown and the low/base/high "
    "scenario, and state plainly which numbers are czis_computed (real), "
    "seeded_demo_value (placeholder pending a real price feed — say this "
    "explicitly), or farmer_estimate. A farmer's own stated yield or price "
    "always overrides the seeded ones — pass it via "
    "farmer_yield_kg_per_decimal / farmer_price_tk_per_kg (also how to "
    "answer 'what if the price drops' questions). If it returns "
    "FINANCE_REFERENCE_UNKNOWN, say no reference data exists for that crop "
    "and ask the farmer for their own cost/price estimates — never invent "
    "numbers.\n"
    "\n"
    "Other tools: get_current_time, calculator for arithmetic, save_memory/"
    "recall_memory for durable personal facts (preferences, experiences) — "
    "farm facts belong in the farm profile, not memory. Be clear and friendly."
)


async def _touch_session(db: AsyncSession, session: ChatSession) -> None:
    from datetime import datetime, timezone

    session.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def _message_count(db: AsyncSession, session_id: int) -> int:
    result = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.session_id == session_id
        )
    )
    return int(result.scalar_one())


async def stream_agent_turn(
    db: AsyncSession,
    user: User,
    session_or_none: Optional[ChatSession],
    message: str,
) -> AsyncGenerator[dict, None]:
    """Run one user turn; yield event dicts matching the frozen contract."""
    session = session_or_none
    log.info(
        "turn start: user=%s session=%s message=%s",
        user.id,
        session.id if session else "NEW",
        trunc(message, 200),
    )
    try:
        # ---- get-or-create session -------------------------------------- #
        if session is None:
            title = message.strip()[:60] or "New chat"
            session = ChatSession(user_id=user.id, title=title)
            db.add(session)
            await db.commit()
            await db.refresh(session)

        yield {"type": "session", "session_id": session.id}

        # ---- persist user message + echo bubble ------------------------- #
        user_msg = ChatMessage(
            session_id=session.id, role="user", content=message, tool_trace=[]
        )
        db.add(user_msg)
        await db.commit()
        await db.refresh(user_msg)
        yield {"type": "message", "message": serialize_message(user_msg)}

        # ---- build tool groups (per specialist node) -------------------- #
        static_tools = build_static_tools()
        weather_tool = build_weather_tool(user)
        farm_tools = build_farm_tools(user)
        soil_tool = build_soil_tool(user)
        patterns_tool = build_patterns_tool(user)
        czis_tools = build_czis_tools(user)
        finance_tool = build_finance_tool(user)
        memory_tools = build_memory_tools(user.id, db)
        tool_groups = {
            "intake": static_tools + farm_tools + [soil_tool],
            "advisor": static_tools
            + [weather_tool]
            + farm_tools
            + [soil_tool, patterns_tool, finance_tool]
            + czis_tools
            + memory_tools,
            # Dedicated crop-recommendation specialist: everything needed to
            # ground a ranked shortlist (profile + soil survey + recorded
            # pattern economics + CZIS catalog/varieties + weather + costed
            # projection), same hard six-field gate.
            "recommender": static_tools
            + [weather_tool]
            + farm_tools
            + [soil_tool, patterns_tool, finance_tool]
            + czis_tools,
        }
        all_tool_names = sorted(
            {t.name for group in tool_groups.values() for t in group}
        )

        # ---- preload farm context for routing/state --------------------- #
        from .tools import _farm_payload, _get_or_create_active_farm

        try:
            farm = await _get_or_create_active_farm(db, user)
            farm_context = _farm_payload(farm)
        except Exception:
            log.exception("farm context preload failed — continuing without")
            farm_context = {}

        # ---- auto-recall top-K memories --------------------------------- #
        yield {
            "type": "progress",
            "stage": "memory",
            "detail": "recalling relevant memories",
        }
        recalled = await memory_mod.recall_memory(
            db, user.id, message, settings.MEMORY_TOP_K
        )

        # ---- load windowed history + summary prefix --------------------- #
        hist_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.id.desc())
            .limit(settings.HISTORY_LIMIT)
        )
        history = list(reversed(hist_result.scalars().all()))
        total_count = await _message_count(db, session.id)

        lc_messages: list = build_system_messages(
            SYSTEM_PROMPT, session.summary, recalled
        )
        lc_messages.extend(history_to_lc_messages(history))

        # ---- run the graph ---------------------------------------------- #
        # Reply language lives in graph STATE: the classify node re-detects
        # it from this user message and every specialist node injects the
        # directive from state (see state.py / graph.py).
        graph = build_graph(tool_groups)
        inputs = {
            "messages": lc_messages,
            "intent": "",
            "active_agent": "",
            "farm_context": farm_context,
            "reply_language": "",
        }
        log.info(
            "graph invoke: session=%s models=[%s|lite=%s] history_msgs=%d "
            "lc_msgs=%d recalled_memories=%d tools=%s",
            session.id,
            settings.OPENROUTER_MODEL,
            settings.OPENROUTER_MODEL_LITE,
            len(history),
            len(lc_messages),
            len(recalled),
            all_tool_names,
        )

        # tool_call_id -> (db ChatMessage, index in its tool_trace)
        tool_call_map: dict[str, tuple[ChatMessage, int]] = {}

        async for mode, chunk in graph.astream(
            inputs, stream_mode=["updates", "custom"]
        ):
            if mode == "custom":
                yield {
                    "type": "progress",
                    "stage": chunk.get("stage", "tool")
                    if isinstance(chunk, dict)
                    else "tool",
                    "detail": chunk.get("detail", "")
                    if isinstance(chunk, dict)
                    else str(chunk),
                }
                continue

            if mode != "updates" or not isinstance(chunk, dict):
                continue

            for _node, payload in chunk.items():
                if not isinstance(payload, dict):
                    continue
                # Routing decision from the classify node -> progress frame.
                if _node == "classify" and payload.get("intent"):
                    detail = f"specialist: {payload['intent']}"
                    if payload.get("reply_language"):
                        detail += f" · reply: {payload['reply_language']}"
                    yield {
                        "type": "progress",
                        "stage": "routing",
                        "detail": detail,
                    }
                    continue
                for msg in payload.get("messages", []) or []:
                    if isinstance(msg, AIMessage):
                        text = text_of(msg.content)
                        traces = tool_call_traces(msg)
                        for entry in traces:
                            log.info(
                                "model tool_call [%s]: %s args=%s",
                                _node,
                                entry["tool"],
                                trunc(entry["args"], 300),
                            )
                        if text:
                            log.info(
                                "model answer [%s]: %d chars: %s",
                                _node,
                                len(text),
                                trunc(text, 200),
                            )
                            if text.lstrip().startswith("[tool "):
                                # Guard: the model imitated the old text-trace
                                # format instead of calling a tool. Should be
                                # impossible with native replay — surface loud.
                                log.warning(
                                    "model IMITATED tool-trace text instead of "
                                    "calling a tool (session=%s): %s",
                                    session.id,
                                    trunc(text, 300),
                                )
                        # Persist a bubble (carries text and/or tool_trace).
                        db_msg = ChatMessage(
                            session_id=session.id,
                            role="assistant",
                            content=text,
                            tool_trace=traces,
                            model=settings.OPENROUTER_MODEL,
                        )
                        db.add(db_msg)
                        await db.commit()
                        await db.refresh(db_msg)
                        for idx, tc in enumerate(msg.tool_calls or []):
                            tc_id = tc.get("id")
                            if tc_id:
                                tool_call_map[tc_id] = (db_msg, idx)
                        yield {
                            "type": "message",
                            "message": serialize_message(db_msg),
                        }

                    elif isinstance(msg, ToolMessage):
                        owner = tool_call_map.get(msg.tool_call_id)
                        if owner is None:
                            continue
                        db_msg, idx = owner
                        new_trace = fill_trace_result(
                            list(db_msg.tool_trace or []), idx, msg
                        )
                        if new_trace is not None:
                            log.info(
                                "tool result: %s -> %s",
                                new_trace[idx].get("tool", "?"),
                                trunc(new_trace[idx]["result"], 400),
                            )
                            db_msg.tool_trace = new_trace  # reassign -> tracked
                            await db.commit()
                            await db.refresh(db_msg)
                            yield {
                                "type": "message_update",
                                "message": serialize_message(db_msg),
                            }

        # ---- bump session, refresh rolling summary on overflow ---------- #
        await _touch_session(db, session)

        new_total = await _message_count(db, session.id)
        if new_total > settings.HISTORY_LIMIT:
            # Summarize everything that has now fallen outside the window.
            offset = new_total - settings.HISTORY_LIMIT
            cutoff_result = await db.execute(
                select(ChatMessage.id)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.id)
                .offset(offset - 1)
                .limit(1)
            )
            cutoff_id = cutoff_result.scalar_one_or_none()
            if cutoff_id and cutoff_id > (session.summary_upto_id or 0):
                yield {
                    "type": "progress",
                    "stage": "summary",
                    "detail": "updating conversation summary",
                }
                try:
                    summary_model = build_chat_model()
                    await memory_mod.refresh_summary(
                        db, session, cutoff_id, summary_model
                    )
                except Exception:
                    pass

        log.info("turn done: session=%s", session.id)
        yield {"type": "done"}

    except Exception as exc:  # surface as terminal error frame
        sid = session.id if session is not None else 0
        log.exception("turn FAILED: user=%s session=%s: %s", user.id, sid, exc)
        try:
            await db.rollback()
        except Exception:
            pass
        yield {"type": "error", "detail": str(exc), "session_id": sid}
