"""Multi-node agricultural workflow graph.

Shape (dedicated nodes, dedicated toolsets, per-node LLMs, shared memory):

    START -> classify -> {intake | advisor} -> tools -> (back to the
                                                         active agent)
                                   \\-> END when no tool calls remain

- **classify** — routes the turn from the farmer's LAST message (+ farm
  context). Uses the cheap OPENROUTER_MODEL_LITE with a deterministic
  keyword fallback (the fallback is also the only path under TESTING so the
  suite stays offline/deterministic).
- **intake**  — slot-filling specialist (farm-profile tools).
- **advisor** — general agronomic advisor (full toolset, default model).
  Weather is NOT a node: ``get_weather`` is a plain tool bound to the
  advisor — a specialist whose whole job is one tool call is just routing
  overhead, so weather questions route to the advisor.
- **tools**   — ONE shared ToolNode executing whichever tool the active
  agent called; control returns to that agent (``state.active_agent``).

Planned Tier-0 nodes plug in the same way (see docs/PLAN.md): planner /
ranker / finance specialists with their deterministic-engine tools.

Every specialist emits normal ``AIMessage.tool_calls`` -> the runner's
trace chips and the frozen SSE contract keep working unchanged.
"""
from __future__ import annotations

import logging
import os
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ..config import settings
from .llm import build_chat_model
from .messages import detect_reply_language, language_directive
from .state import OrchestratorState

MAX_TURNS = 12  # tool rounds per REQUEST turn (history rounds excluded)

log = logging.getLogger("agrisense.agent.graph")

AGENTS = ("intake", "advisor", "recommender")

# Which OpenRouter model powers each node (single place to retune).
# NOTE: intake initially ran on MODEL_LITE — live test showed flash-lite
# ignoring the Bengali language directive AND skipping update_farm_profile
# saves. Extraction quality matters; only classification stays on lite.
def _node_models() -> dict[str, str]:
    return {
        "classify": settings.OPENROUTER_MODEL_LITE,
        "intake": settings.OPENROUTER_MODEL,
        "advisor": settings.OPENROUTER_MODEL,
        "recommender": settings.OPENROUTER_MODEL,
    }


NODE_DIRECTIVES = {
    "intake": (
        "CURRENT NODE: INTAKE SPECIALIST. Focus: collect and save farm "
        "profile facts (get_farm_profile / update_farm_profile). Save every "
        "explicitly stated fact immediately, relay warnings, then ask ONE "
        "or two targeted questions for the most important missing field. "
        "Soil usually auto-fills from the upazila survey (soil_source="
        "survey_default_confirm_with_farmer) — present it as an assumption "
        "to confirm; only when soil_type is missing ask the farmer for it "
        "(get_soil_context gives the survey breakdown). If the farmer is "
        "talking about a different/new field, resolve WHICH farm first "
        "(list_farms / select_farm / create_farm). Do not give full crop "
        "advice here — once all six mandatory fields are present, "
        "summarize and confirm the profile."
    ),
    "advisor": (
        "CURRENT NODE: GENERAL ADVISOR. Give practical agronomic advice "
        "using any tool that helps; keep farm profile facts saved via "
        "update_farm_profile when the farmer states new ones. For anything "
        "weather-related, fetch the real forecast with get_weather and "
        "answer grounded in the returned values only, relating it to the "
        "farmer's crops/plans when profile context is available. "
        "For variety or fertilizer specifics on an ALREADY-CHOSEN crop, "
        "ground the answer in the CZIS tools (czis_crop_varieties / "
        "czis_crop_context -> czis_fertilizer_recommendation, "
        "server-computed doses relayed verbatim). Never invent variety "
        "yields or fertilizer amounts; if CZIS is unavailable, say so. "
        "For cost/profit/ROI/break-even questions on a crop the farmer has "
        "already chosen, call calculate_financials — pass crop_id+variety_id "
        "when known so real CZIS fertilizer cost is included; never compute "
        "these numbers yourself, and state plainly which figures are real "
        "vs seeded placeholders. "
        "Choosing WHICH crop to grow is the recommender specialist's job — "
        "you may answer general questions, but a proper ranked "
        "recommendation should follow its flow."
    ),
    "recommender": (
        "CURRENT NODE: CROP RECOMMENDER. Your ONLY job: recommend crops "
        "for the ACTIVE farm, grounded in tools — never model memory. "
        "HARD GATE: call get_farm_profile FIRST — while ANY of the six "
        "mandatory fields (location, farm_size, soil_type, "
        "water_availability, budget, season) is missing, do NOT recommend; "
        "ask for at most TWO missing fields (never a numbered list of 3+ "
        "questions). Soil usually auto-fills from the survey "
        "(soil_source=survey_default_confirm_with_farmer) — present it as "
        "an assumption to confirm, don't ask for it.\n"
        "When the profile is complete, follow this flow: "
        "(1) czis_list_crops filtered by the farm's season -> candidate "
        "pool (the CZIS catalog itself only knows season; matching soil, "
        "water, budget and area against candidates is YOUR reasoning job "
        "using the profile + survey data); "
        "(2) get_soil_context for the full soil breakdown (texture, land "
        "type, drainage, pH) and match candidates against it; "
        "(3) get_cropping_patterns for the RECORDED rotation economics of "
        "this upazila (BCR + gross margin Tk/decimal, most profitable "
        "first) — profitability claims MUST come from these values "
        "(gm_tk_per_decimal x area_decimal via the calculator tool), never "
        "from memory; "
        "(4) czis_crop_varieties for the TOP 2-3 candidates ONLY -> real "
        "yield (t/ha) and duration (days) — batch them as PARALLEL tool "
        "calls in a single round, never one crop per round; "
        "(5) get_weather when near-term conditions matter for "
        "sowing/water; "
        "(6) present a ranked shortlist of 3-5 crops. For EVERY pick, "
        "name the specific farm inputs (soil texture, land type, "
        "irrigation, budget, area, season) and the retrieved values "
        "(variety yields/durations, BCR/margin) it rests on. Numbers come "
        "ONLY from tool results. Once the farmer settles on ONE crop from "
        "the shortlist, call calculate_financials for a full itemized cost/"
        "revenue/profit/ROI/break-even projection (the gm_tk_per_decimal "
        "cross-check above is only a rough ranking signal, not a substitute). "
        "Keep farm facts saved via update_farm_profile when "
        "the farmer states new ones."
    ),
}

# --------------------------------------------------------------------------- #
# Intent classification: deterministic keywords (+ lite-LLM in production)
# --------------------------------------------------------------------------- #
_WEATHER_WORDS = re.compile(
    r"(weather|forecast|rain|storm|temperature|humidity|আবহাওয়া|বৃষ্টি|"
    r"তাপমাত্রা|ঝড়|কুয়াশা|পূর্বাভাস|brishti|bristi|jhor|tapmatra|abohawa)",
    re.IGNORECASE,
)
_INTAKE_WORDS = re.compile(
    r"(জমি|বিঘা|শতক|কাঠা|কানি|বাজেট|টাকা|সেচ|মাটি|jomi|bigha|shotok|katha|"
    r"kani|budget|taka|sech|mati|soil|acre|hectare|lakh|হাজার|লাখ)",
    re.IGNORECASE,
)
_RECOMMEND_WORDS = re.compile(
    r"(recommend|suggest|which crop|what crop|what should i (?:plant|grow|"
    r"farm)|profitable|kon fosol|ki fosol|kon chash|ki chash|ki lagabo|"
    r"konta lagabo|ki bunbo|labjonok|labhjonok|suparish|কোন ফসল|কি ফসল|"
    r"কী ফসল|কি চাষ|কী চাষ|চাষ কর|লাগাব|বুনব|লাভজনক|সুপারিশ|ফলন ভালো)",
    re.IGNORECASE,
)

_CLASSIFY_PROMPT = (
    "You route a Bangladeshi farmer's message to ONE specialist. Reply with "
    "exactly one word:\n"
    "- recommender : asking WHICH crop to plant / crop suggestions / what "
    "would be profitable to grow\n"
    "- intake  : stating or correcting farm facts (land size, budget, "
    "irrigation, soil, season, location)\n"
    "- advisor : anything else (weather questions, pests, fertilizer for a "
    "chosen crop, prices, greetings)\n"
)


def classify_heuristic(text: str) -> str:
    # Crop-choice questions go to the dedicated recommender — checked first
    # so "kon fosol labjonok hobe?" outranks generic advice routing.
    if _RECOMMEND_WORDS.search(text or ""):
        return "recommender"
    # Weather questions go to the advisor (it owns the get_weather tool) —
    # checked before intake so "brishti + jomi" turns get grounded weather
    # answers instead of slot-filling.
    if _WEATHER_WORDS.search(text or ""):
        return "advisor"
    if _INTAKE_WORDS.search(text or ""):
        return "intake"
    return "advisor"


async def _classify(text: str) -> str:
    heuristic = classify_heuristic(text)
    if os.environ.get("TESTING"):
        return heuristic
    try:
        model = build_chat_model(settings.OPENROUTER_MODEL_LITE)
        resp = await model.ainvoke(
            [SystemMessage(content=_CLASSIFY_PROMPT), HumanMessage(content=text)]
        )
        word = str(resp.content or "").strip().lower().split()[0].strip(".,:")
        if word in AGENTS:
            return word
        log.warning("classifier returned %r — using heuristic %r", word, heuristic)
    except Exception as exc:
        log.warning("classifier LLM failed (%s) — using heuristic %r", exc, heuristic)
    return heuristic


def _current_turn_tool_rounds(messages: list) -> int:
    """Tool rounds spent THIS request turn.

    Replayed history reconstructs past tool calls with ids prefixed
    ``hist_`` — those must not eat the MAX_TURNS budget (long sessions would
    permanently lose tool access).
    """
    rounds = 0
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            if any(
                not str(tc.get("id") or "").startswith("hist_")
                for tc in m.tool_calls
            ):
                rounds += 1
    return rounds


def _last_human_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            content = m.content
            return content if isinstance(content, str) else str(content)
    return ""


def build_graph(tool_groups: dict[str, list]):
    """Compile the multi-node workflow.

    ``tool_groups`` maps agent name -> the tools that agent may call. The
    shared ToolNode executes the union; binding restricts what each agent
    sees. Each agent gets its own LLM (see ``_node_models``).
    """
    models = _node_models()
    bound: dict[str, object] = {}
    plain: dict[str, object] = {}
    for name in AGENTS:
        model = build_chat_model(models[name])
        plain[name] = model
        bound[name] = model.bind_tools(tool_groups.get(name, []))

    # Union of all tools, deduped by tool name, for the shared executor.
    all_tools: dict[str, object] = {}
    for group in tool_groups.values():
        for t in group:
            all_tools[t.name] = t

    async def classify_node(state: OrchestratorState):
        text = _last_human_text(state["messages"])
        intent = await _classify(text)
        # Language STATE: refreshed on every user message (deterministic).
        reply_language = detect_reply_language(text)
        farm = state.get("farm_context") or {}
        log.info(
            "classify: intent=%s reply_language=%s (missing_fields=%s) "
            "message=%r",
            intent,
            reply_language,
            farm.get("missing_required_fields"),
            text[:120],
        )
        return {"intent": intent, "reply_language": reply_language}

    def make_agent_node(name: str):
        async def agent_node(state: OrchestratorState):
            messages = state["messages"]
            used = _current_turn_tool_rounds(messages)
            forced_final: list = []
            if used >= MAX_TURNS:
                log.warning(
                    "[%s] MAX_TURNS (%d) reached — forcing final answer",
                    name,
                    MAX_TURNS,
                )
                active = plain[name]
                # Without an explicit instruction the tool-less model can
                # return empty content — tell it plainly what to do.
                forced_final = [
                    SystemMessage(
                        content=(
                            "TOOL BUDGET EXHAUSTED: no more tool calls are "
                            "possible this turn. Write your FINAL answer NOW "
                            "using only the tool results already above. If "
                            "some data is missing, say so honestly instead "
                            "of inventing it."
                        )
                    )
                ]
            else:
                active = bound[name]
            log.info(
                "agent node [%s] (model=%s): llm call "
                "(tool_rounds_used=%d, messages=%d)",
                name,
                models[name],
                used,
                len(messages),
            )
            directive = SystemMessage(content=NODE_DIRECTIVES[name])
            # Reply language comes from graph STATE (set by classify each
            # user message); fall back to detecting from the last human
            # message when the graph is driven without a classify pass.
            # Placed LAST so recency keeps it authoritative even in long
            # conversations.
            lang = state.get("reply_language") or detect_reply_language(
                _last_human_text(messages)
            )
            lang_directive = language_directive(lang)
            response = await active.ainvoke(
                [directive] + list(messages) + [lang_directive] + forced_final
            )
            return {"messages": [response], "active_agent": name}

        agent_node.__name__ = f"{name}_node"
        return agent_node

    def route_after_classify(state: OrchestratorState) -> str:
        intent = state.get("intent") or "advisor"
        return intent if intent in AGENTS else "advisor"

    def should_continue(state: OrchestratorState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    def route_back_to_agent(state: OrchestratorState) -> str:
        agent = state.get("active_agent") or "advisor"
        return agent if agent in AGENTS else "advisor"

    builder = StateGraph(OrchestratorState)
    builder.add_node("classify", classify_node)
    for name in AGENTS:
        builder.add_node(name, make_agent_node(name))
    builder.add_node("tools", ToolNode(list(all_tools.values())))

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify", route_after_classify, {name: name for name in AGENTS}
    )
    for name in AGENTS:
        builder.add_conditional_edges(
            name, should_continue, {"tools": "tools", END: END}
        )
    builder.add_conditional_edges(
        "tools", route_back_to_agent, {name: name for name in AGENTS}
    )
    return builder.compile()
