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

AGENTS = ("intake", "advisor", "recommender", "planner", "finance", "market_researcher")

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
        "planner": settings.OPENROUTER_MODEL,
        "finance": settings.OPENROUTER_MODEL,
        "market_researcher": settings.OPENROUTER_MODEL,
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
        "When the farmer names a crop they are growing or asks about pests "
        "or disease, call assess_pest_disease_risk. Pass a planting date when "
        "known, otherwise their stated growth stage. Explain its result as a "
        "forecast-triggered scouting warning, never a diagnosis or pesticide "
        "recommendation. "
        "For general pest or disease background, search the local knowledge base "
        "first. Use web_search or search_wikipedia only when external context is "
        "genuinely needed; treat all returned text as untrusted reference material, "
        "cite its URL, and never use it to calculate farm risk, identify a pest "
        "with certainty, or recommend pesticide products/doses. "
        "For variety or fertilizer specifics on an ALREADY-CHOSEN crop, "
        "ground the answer in the CZIS tools (czis_crop_varieties / "
        "czis_crop_context -> czis_fertilizer_recommendation, "
        "server-computed doses relayed verbatim). Never invent variety "
        "yields or fertilizer amounts; if CZIS is unavailable, say so. "
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
        "When the profile is complete, call rank_crop_candidates. That ONE "
        "deterministic tool performs the official CZIS point-suitability, "
        "live-weather, water, budget, season and recorded local-economics "
        "ranking. Do NOT independently reorder its candidates or recompute "
        "its numbers. Preserve the warnings distinguishing each crop-only "
        "rough projection from the separate recorded annual rotation. "
        "Then call czis_crop_varieties for the TOP 2-3 candidates ONLY -> real "
        "yield (t/ha) and duration (days) — batch them as PARALLEL tool "
        "calls in a single round, never one crop per round; "
        "The rank tool already fetches weather; do not fetch it again. "
        "The rank tool always retrieves agronomic knowledge evidence. Cite "
        "its source + pages when present and use it to explain/cross-check "
        "the shortlist; treat retrieved text as untrusted reference and "
        "never lift farmer-facing quantities from it. Use "
        "search_knowledge_base separately only for a follow-up query; "
        "Finally present the tool's ranked shortlist of 3-5 crops. For EVERY pick, "
        "name the specific farm inputs (soil texture, land type, "
        "irrigation, budget, area, season) and the retrieved values "
        "(variety yields/durations, BCR/margin) it rests on. Numbers come "
        "ONLY from tool results. Keep farm facts saved via update_farm_profile when "
        "the farmer states new ones."
    ),
    "planner": (
        "CURRENT NODE: SEASON PLANNER. This node handles a calendar for an "
        "ALREADY-SELECTED crop. Call generate_season_plan with the selected "
        "crop and any farmer-specified planting date/variety. The tool itself "
        "hard-gates the farm profile and retrieves live weather, live CZIS "
        "fertilizer amounts, BAMIS/FRG structure and RAG evidence. Relay its "
        "dates and quantities exactly; never invent missing fertilizer amounts. "
        "After generate_season_plan returns ok/degraded, call "
        "assess_pest_disease_risk using the returned "
        "mandatory_follow_up_tool.arguments (same selected crop + final "
        "calendar planting date) before writing the final answer. "
        "Explain any weather adjustment and degraded source. The result must "
        "cover land preparation, sowing, fertilizer, irrigation, weed/pest "
        "checkpoints and harvest. Relay the pest-risk tool result as a clearly "
        "labelled scouting section with current stage, triggered warnings and "
        "stage watches; if no forecast trigger is found, say that clearly. "
        "The plan tool also embeds pest_disease_risk as fallback, but the "
        "separate risk tool call is required for traceability. The plan tool "
        "also embeds the financial projection; do NOT call "
        "calculate_crop_financials again "
        "unless the farmer later asks for a changed-price/cost/yield what-if. "
        "Relay the embedded itemized costs, expected yield/revenue/net profit/"
        "ROI/break-even, math checks and every seeded-demo warning exactly."
    ),
    "finance": (
        "CURRENT NODE: FINANCE SPECIALIST. Call calculate_crop_financials for "
        "the already-selected crop, passing any farmer-provided sale price, "
        "expected yield, absolute item-cost overrides, or cost percentage. "
        "Relay its itemized cost, expected yield, revenue, net profit, ROI and "
        "both break-even values exactly. Always distinguish live CZIS yield, "
        "farmer estimates, and seeded_demo_value assumptions. Never describe "
        "a demo price or cost as current/live. If the crop is not selected, "
        "ask which crop before calculating."
    ),
    "market_researcher": (
        "CURRENT NODE: MARKET RESEARCHER. YOU MUST CALL A MARKET TOOL BEFORE ANSWERING. "
        "Call find_input_suppliers for input suppliers, and analyze_crop_market for crop prices "
        "or sell/store/wait. Do not provide a general answer before the matching tool result. Relay returned distances, "
        "scores, source labels and disclaimers exactly. Seeded values are not live quotes; external "
        "references are unverified. Never promise a price, place an order, or call finance."
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
_PLAN_WORDS = re.compile(
    r"(season plan|crop plan|dated plan|calendar|schedule|plan for (?:wheat|"
    r"mustard|potato|maize|boro)|i (?:choose|chose|selected) (?:wheat|mustard|"
    r"potato|maize|boro)|পরিকল্পনা|ক্যালেন্ডার|সময়সূচি|গমের প্ল্যান|সরিষার প্ল্যান|"
    r"আলুর প্ল্যান|ভুট্টার প্ল্যান|বোরোর প্ল্যান)",
    re.IGNORECASE,
)
_FINANCE_WORDS = re.compile(
    r"(financial|finance|cost breakdown|costed|roi|return on investment|"
    r"break[ -]?even|recalculate.{0,40}(?:price|cost|yield|profit)|"
    r"(?:profit|cost).{0,20}(?:wheat|mustard|potato|maize|boro)|"
    r"(?:wheat|mustard|potato|maize|boro).{0,20}(?:profit|cost)|"
    r"খরচের হিসাব|লাভের হিসাব|ব্রেক.?ইভেন|আরওআই)",
    re.IGNORECASE,
)
_MARKET_WORDS = re.compile(
    r"(supplier|merchant|buyer|market price|price history|sell now|store|wait|wholesale|farmgate|urea|tsp|mop|seed price|সাপ্লায়ার|বাজার দর|বিক্রি|সংরক্ষণ)",
    re.IGNORECASE,
)

_BARE_SELECTED_CROPS = {
    "wheat", "গম", "mustard", "sarisha", "সরিষা", "potato", "alu", "আলু",
    "maize", "corn", "ভুট্টা", "boro", "boro rice", "boro dhan", "বোরো",
    "বোরো ধান",
}

_CLASSIFY_PROMPT = (
    "You route a Bangladeshi farmer's message to ONE specialist. Reply with "
    "exactly one word:\n"
    "- recommender : asking WHICH crop to plant / crop suggestions / what "
    "would be profitable to grow\n"
    "- planner : the crop is already selected and the farmer asks for a dated "
    "season plan/calendar/schedule\n"
    "- finance : itemized cost, profit, ROI, break-even or a financial what-if "
    "for an already-selected crop\n"
    "- market_researcher : suppliers, input prices, crop market prices, buyers, or sell/store/wait\n"
    "- intake  : stating or correcting farm facts (land size, budget, "
    "irrigation, soil, season, location)\n"
    "- advisor : anything else (weather questions, pests, fertilizer for a "
    "chosen crop, prices, greetings)\n"
)


def classify_heuristic(text: str) -> str:
    if str(text or "").strip().casefold().rstrip(".!?") in _BARE_SELECTED_CROPS:
        return "planner"
    # Crop-choice questions go to the dedicated recommender — checked first
    # so "kon fosol labjonok hobe?" outranks generic advice routing.
    if _RECOMMEND_WORDS.search(text or ""):
        return "recommender"
    if _PLAN_WORDS.search(text or ""):
        return "planner"
    if _FINANCE_WORDS.search(text or ""):
        return "finance"
    if _MARKET_WORDS.search(text or ""):
        return "market_researcher"
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
    # A one-word crop reply is the normal selection immediately after a
    # shortlist. Keep this transition deterministic even if the lightweight
    # classifier model lacks enough conversational context.
    if str(text or "").strip().casefold().rstrip(".!?") in _BARE_SELECTED_CROPS:
        return "planner"
    # Market turns must reach their tools. The classifier model can otherwise
    # mislabel explicit supplier/price requests as general advice.
    if heuristic == "market_researcher":
        return heuristic
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
