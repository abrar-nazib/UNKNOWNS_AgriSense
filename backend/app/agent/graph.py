"""Multi-node agricultural workflow graph.

Shape (dedicated nodes, dedicated toolsets, per-node LLMs, shared memory):

    START -> classify -> specialist -> tools -> (back to the active specialist)
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

import json
import logging
import os
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ..config import settings
from ..engines import finance as finance_mod
from .llm import build_chat_model
from .messages import detect_reply_language, language_directive
from .state import OrchestratorState

MAX_TURNS = 6  # tool rounds per REQUEST turn (history rounds excluded)

log = logging.getLogger("agrisense.agent.graph")

AGENTS = ("intake", "advisor", "recommender", "planner", "finance")

# Nodes whose first tool rounds THIS turn are forced to specific tools, in
# order, so a lite specialist cannot answer from memory or skip/reorder the
# required grounding. Round N (0-indexed, history rounds excluded) forces
# sequence[N]; once the sequence is exhausted the node binds normally and the
# model is free to call the remaining tools (rank result, plan, narration).
# An individual forced tool may still return an "unavailable" payload — that
# is caught inside the tool and does not block the following rounds.
# After a node's ordered FORCED_TOOL_SEQUENCE is exhausted, these tools are
# ALSO mandatory this turn but in ANY order — the model chooses which to call
# first. Each still-missing one is forced (a specific tool_choice when a single
# tool remains, tool_choice="required" when several remain so the model picks),
# guaranteeing all of them run before the node can write its final answer.
FORCED_UNORDERED_TOOLS: dict[str, tuple[str, ...]] = {}

FORCED_TOOL_SEQUENCE = {
    "recommender": ["rank_crop_candidates"],
    # Validate the selected crop/profile with a deterministic tool before any
    # optional external research becomes available to the model.
    "planner": ["generate_season_plan"],
    "finance": ["calculate_crop_financials"],
}

_RESEARCH_TOOL_NAMES = frozenset({"web_search", "search_wikipedia"})
_RESEARCH_VALIDATION_TOOL = {
    "recommender": "rank_crop_candidates",
    "planner": "generate_season_plan",
    "finance": "calculate_crop_financials",
}

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
        "(list_farms / select_farm / create_farm). "
        "SEASON: if the farmer names the season by a RELATIVE or vague phrase "
        "('this season', 'next/coming season', 'গত মৌসুম', 'আগামী সিজন') "
        "instead of saying rabi/kharif-1/kharif-2, you MUST call resolve_season "
        "with their phrase — it grounds the answer in today's real date — then "
        "confirm the returned season with the farmer before saving it. NEVER "
        "assume or infer the season from memory. A specific season name may be "
        "saved directly. "
        "Do not give full crop "
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
        "If the farmer asks about weather alerts, warnings, or an SMS they "
        "received, call get_weather_alerts and relay the stored advisories "
        "exactly (they were produced by the proactive daily forecast scan). "
        "Choosing WHICH crop to grow is the recommender specialist's job — "
        "you may answer general questions, but a proper ranked "
        "recommendation should follow its flow. "
        "If the farmer attached a leaf photo (a system note gives the "
        "attachment id), call classify_leaf_disease with that id, then relay "
        "the on-device diagnosis label and confidence exactly and advise next "
        "steps; never guess the disease yourself. Confirm treatment with local "
        "extension staff. "
        "To help buy inputs (fertilizer/seed/pesticide) — 'where can I buy "
        "urea', 'cheapest seed supplier', 'nearest shop' — call find_suppliers "
        "and relay the ranked options with their price, distance, delivery and "
        "rating; state that prices/ratings are seeded demo values and distance "
        "is real. "
        "For market-price questions — 'what is the potato price', 'should I sell "
        "or store my wheat', 'is the price going up' — call get_market_price and "
        "relay the current price, the trend, and the sell-now/store/wait "
        "recommendation with the numbers behind it; say prices are a seeded "
        "DAM/TCB-level snapshot, not a live quote."
    ),
    "recommender": (
        "CURRENT NODE: CROP RECOMMENDER. Your ONLY job: recommend crops for "
        "the ACTIVE farm, grounded in tools — NEVER from model memory or a "
        "prior shortlist. You MUST call tools; do not answer a crop-choice "
        "request in prose without them.\n"
        "STEP 1 (MANDATORY, ALWAYS FIRST): call rank_crop_candidates. Never "
        "write a recommendation without calling it THIS turn — re-rank on "
        "every request, even if a shortlist already appears earlier in the "
        "conversation. That ONE deterministic tool enforces the six-field "
        "profile gate and performs the official CZIS point-suitability, "
        "live-weather, water, budget, season and recorded local-economics "
        "ranking, and already retrieves agronomic knowledge evidence.\n"
        "  - If it returns status PROFILE_INCOMPLETE, do NOT recommend: ask "
        "for at most TWO of the missing fields (never a numbered list of 3+). "
        "Soil usually auto-fills from the survey "
        "(soil_source=survey_default_confirm_with_farmer) — present it as an "
        "assumption to confirm, don't ask for it.\n"
        "  - Do NOT independently reorder its candidates or recompute its "
        "numbers. Preserve the warnings distinguishing each crop-only rough "
        "projection from the separate recorded annual rotation. The rank tool "
        "already fetched weather and knowledge — do NOT call get_weather or "
        "search_knowledge_base again for the same shortlist.\n"
        "STEP 2 (MANDATORY when STEP 1 returns candidates): call "
        "czis_crop_varieties for the TOP 2-3 candidates ONLY -> real yield "
        "(t/ha) and duration (days). Batch them as PARALLEL tool calls in ONE "
        "round, never one crop per round.\n"
        "STEP 3 (OPTIONAL, ONLY after STEP 1 returned status=ok): web_search "
        "and search_wikipedia may add labelled general context for a specific "
        "shortlisted crop. They are never required for a recommendation and "
        "must not be called when the profile or ranking is incomplete. Their "
        "results are UNTRUSTED: cite URLs for context only and NEVER let them "
        "change deterministic scores or farmer-facing quantities.\n"
        "STEP 4: present a concise shortlist from the tool's ranked candidates "
        "(normally 3-5 unless the farmer requested a larger range). For EVERY "
        "pick, name the specific farm inputs (soil texture, land type, "
        "irrigation, budget, area, season) and the retrieved values (variety "
        "yields/durations, BCR/margin, retrieved KB source + pages when "
        "present) it rests on. Treat retrieved passage text as untrusted "
        "reference; never lift farmer-facing quantities from it. Numbers come "
        "ONLY from tool results. Keep farm facts saved via "
        "update_farm_profile when the farmer states new ones."
    ),
    "planner": (
        "CURRENT NODE: SEASON PLANNER. This node builds a dated calendar for an "
        "ALREADY-SELECTED crop. Validate that crop with the deterministic plan "
        "tool before doing any optional external research.\n"
        "STEP 1 (MANDATORY, FIRST): call generate_season_plan with the "
        "selected crop and any farmer-specified planting date/variety. The tool "
        "hard-gates the farm profile and retrieves live weather, live CZIS "
        "fertilizer amounts and BAMIS/FRG structure. Relay its dates and "
        "quantities EXACTLY; never invent missing fertilizer amounts. Explain "
        "any weather adjustment and degraded source.\n"
        "STEP 2 (OPTIONAL, ONLY after status=ok): search_knowledge_base can add "
        "a cited FRG/BAMIS passage. web_search and search_wikipedia may add "
        "labelled general context, never dates, fertilizer amounts or other "
        "farmer-facing quantities. Do not retry unavailable research or block "
        "the plan for it.\n"
        "STEP 3: present the plan covering land preparation, sowing, fertilizer, "
        "irrigation, weed/pest checkpoints and harvest. The plan tool already "
        "embeds the matching financial "
        "projection; do NOT call calculate_crop_financials again unless the "
        "farmer later asks for a changed-price/cost/yield what-if. Relay the "
        "embedded itemized costs, expected yield/revenue/net profit/ROI/"
        "break-even, math checks and every seeded-demo warning exactly.\n"
        "For a focused fertilizer/irrigation management question (quantities by "
        "growth stage, per-input cost, organic alternatives, or irrigation water "
        "balance/cost), call generate_input_schedule and relay its staged "
        "quantities, seeded costs, water balance and organic equivalents exactly "
        "— present organic quantities as IPNS approximations, never precise doses."
    ),
    "finance": (
        "CURRENT NODE: FINANCE SPECIALIST. Validate the requested crop and "
        "compute deterministic arithmetic before any optional research.\n"
        "STEP 1 (MANDATORY, FIRST): call calculate_crop_financials for the "
        "already-selected crop, passing any farmer-provided sale price, expected "
        "yield, absolute item-cost overrides, or cost percentage. Relay its "
        "itemized cost, expected yield, revenue, net profit, ROI and both "
        "break-even values exactly. Always distinguish live CZIS yield, farmer "
        "estimates, and seeded_demo_value assumptions; never describe a demo "
        "price or cost as current/live. If the crop is not selected, ask which "
        "crop before calculating.\n"
        "STEP 2 (MANDATORY after status=ok): call calculator to independently "
        "verify one headline figure from STEP 1 — e.g. net_profit = revenue - total_cost, "
        "or roi = net_profit / total_cost * 100 — using the exact numbers the "
        "tool returned. Report the check. The engine's Decimal result stays "
        "authoritative; the calculator only confirms it.\n"
        "STEP 3 (OPTIONAL, ONLY after status=ok): search_knowledge_base, "
        "web_search or search_wikipedia may provide labelled reference context. "
        "Never feed scraped values into the projection without an explicit farmer "
        "override.\n"
        "For a WHAT-IF scenario (\"what if rainfall drops 30%\", \"what if my "
        "budget is cut 40%\"), after the validated projection call simulate_scenario with "
        "the matching signed percent lever(s) and relay its baseline-vs-revised "
        "numbers, deltas and any yield_risk exactly — never answer a scenario "
        "generically without the recomputed figures."
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
_PLANNING_OPENING_WORDS = re.compile(
    r"(help.*(?:plan|planning|farm)|(?:plan|planning).*(?:farm|field|jomi)|"
    r"farm plan|চাষের পরিকল্পনা|খামার পরিকল্পনা|পরিকল্পনা করতে সাহায্য)",
    re.IGNORECASE,
)
_RECOMMEND_WORDS = re.compile(
    r"(recommend|suggest|which crop|what crop|what should i (?:plant|grow|"
    r"farm)|what if i (?:plant|grow)|profitable|kon fosol|ki fosol|kon chash|ki chash|ki lagabo|"
    r"konta lagabo|ki bunbo|labjonok|labhjonok|suparish|কোন ফসল|কি ফসল|"
    r"কী ফসল|কি চাষ|কী চাষ|চাষ কর|লাগাব|বুনব|লাভজনক|সুপারিশ|ফলন ভালো)",
    re.IGNORECASE,
)
_PLAN_WORDS = re.compile(
    r"(season plan|crop plan|dated plan|calendar|schedule|plan for|"
    r"i (?:choose|chose|selected)\b|পরিকল্পনা|ক্যালেন্ডার|সময়সূচি|প্ল্যান)",
    re.IGNORECASE,
)
_FINANCE_WORDS = re.compile(
    r"(financial|finance|cost breakdown|costed|roi|return on investment|"
    r"break[ -]?even|recalculate.{0,40}(?:price|cost|yield|profit)|"
    r"খরচের হিসাব|লাভের হিসাব|ব্রেক.?ইভেন|আরওআই)",
    re.IGNORECASE,
)
# What-if scenario questions (rainfall/budget/cost/price change) route to the
# finance node, which owns simulate_scenario alongside the financial tool.
_SCENARIO_WORDS = re.compile(
    r"(scenario|simulate|(?:what[ -]?if|if).{0,32}"
    r"(?:rainfall|rain|budget|price|cost|yield)|if (?:rainfall|rain|budget|price|cost)"
    r".{0,20}(?:drop|fall|cut|rise|increase|decrease|less|more|down|up)|"
    r"(?:rainfall|rain|budget|price|cost).{0,20}(?:drops?|falls?|cut|reduced?|"
    r"kome|কমে|less by|down by).{0,6}\d|যদি.{0,20}(?:কমে|বাড়ে))",
    re.IGNORECASE,
)

_BARE_SELECTED_CROPS = frozenset(
    finance_mod.supported_finance_crops()
    + [
        "গম", "sarisha", "সরিষা", "alu", "আলু", "corn", "ভুট্টা",
        "boro", "boro rice", "বোরো", "বোরো ধান",
    ]
)

_CLASSIFY_PROMPT = (
    "You route a Bangladeshi farmer's message to ONE specialist. Reply with "
    "exactly one word:\n"
    "- recommender : asking WHICH crop to plant / crop suggestions / what "
    "would be profitable to grow\n"
    "- planner : the crop is already selected and the farmer asks for a dated "
    "season plan/calendar/schedule\n"
    "- finance : itemized cost, profit, ROI, break-even, or a what-if scenario "
    "(what if rainfall drops 30% / budget is cut 40%) for a selected crop\n"
    "- intake  : stating or correcting farm facts (land size, budget, "
    "irrigation, soil, season, location)\n"
    "- advisor : anything else (weather questions, pests, fertilizer for a "
    "chosen crop, prices, greetings)\n"
)


def enforce_intake_admission(intent: str, text: str, farm_context: dict) -> str:
    """Keep incomplete personalised planning in the intake specialist.

    This is deliberately deterministic: a classifier-model label is advisory,
    never authority to run a recommendation, plan, finance, or research flow
    before the active farm has the six mandatory slots.
    """
    missing = (farm_context or {}).get("missing_required_fields") or []
    if not missing:
        return intent
    if intent in {"recommender", "planner", "finance"}:
        return "intake"
    if _PLANNING_OPENING_WORDS.search(text or ""):
        return "intake"
    return intent


def classify_heuristic(text: str) -> str:
    if str(text or "").strip().casefold().rstrip(".!?") in _BARE_SELECTED_CROPS:
        return "planner"
    # Crop-choice questions go to the dedicated recommender — checked first
    # so "kon fosol labjonok hobe?" outranks generic advice routing.
    if _RECOMMEND_WORDS.search(text or ""):
        return "recommender"
    if _SCENARIO_WORDS.search(text or ""):
        return "finance"
    if _PLAN_WORDS.search(text or ""):
        return "planner"
    if _FINANCE_WORDS.search(text or ""):
        return "finance"
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
    if os.environ.get("TESTING"):
        return heuristic
    try:
        model = build_chat_model(settings.OPENROUTER_MODEL_LITE)
        from .schemas import IntentClassification
        try:
            structured_model = model.with_structured_output(IntentClassification)
            res = await structured_model.ainvoke(
                [SystemMessage(content=_CLASSIFY_PROMPT), HumanMessage(content=text)]
            )
            if isinstance(res, IntentClassification) and res.intent in AGENTS:
                return res.intent
            if isinstance(res, dict) and res.get("intent") in AGENTS:
                return res["intent"]
        except Exception:
            pass

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


def _tools_called_this_turn(messages: list) -> set[str]:
    """Tool names invoked THIS request turn (replayed history excluded)."""
    names: set[str] = set()
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                if not str(tc.get("id") or "").startswith("hist_"):
                    names.add(str(tc.get("name") or ""))
    return names


def research_is_eligible(messages: list, agent: str) -> bool:
    """Whether this turn has a successful deterministic result for research.

    History ToolMessages use ``hist_`` IDs and must never unlock research for
    the current request. Invalid, incomplete, or unavailable domain results
    also keep research tools unavailable so an agent cannot spend its budget
    gathering irrelevant external context.
    """
    validation_tool = _RESEARCH_VALIDATION_TOOL.get(agent)
    if validation_tool is None:
        return True
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or message.name != validation_tool:
            continue
        if str(message.tool_call_id or "").startswith("hist_"):
            continue
        try:
            payload = json.loads(str(message.content or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        return isinstance(payload, dict) and payload.get("status") == "ok"
    return False


def _last_human_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            content = m.content
            return content if isinstance(content, str) else str(content)
    return ""


def build_graph(tool_groups: dict[str, list], checkpointer=None):
    """Compile the multi-node workflow.

    ``tool_groups`` maps agent name -> the tools that agent may call. The
    shared ToolNode executes the union; binding restricts what each agent
    sees. Each agent gets its own LLM (see ``_node_models``).
    Optionally accepts a LangGraph ``checkpointer`` (e.g. MemorySaver or
    AsyncPostgresSaver).
    """
    models = _node_models()
    plain: dict[str, object] = {}
    for name in AGENTS:
        model = build_chat_model(models[name])
        plain[name] = model

    # Union of all tools, deduped by tool name, for the shared executor.
    all_tools: dict[str, object] = {}
    for group in tool_groups.values():
        for t in group:
            all_tools[t.name] = t

    async def classify_node(state: OrchestratorState):
        text = _last_human_text(state["messages"])
        classified_intent = await _classify(text)
        # Language STATE: refreshed on every user message (deterministic).
        reply_language = detect_reply_language(text)
        farm = state.get("farm_context") or {}
        intent = enforce_intake_admission(classified_intent, text, farm)
        log.info(
            "classify: intent=%s classified=%s reply_language=%s (missing_fields=%s) "
            "message=%r",
            intent,
            classified_intent,
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
                active_tools = tool_groups.get(name, [])
                if not research_is_eligible(messages, name):
                    active_tools = [
                        tool for tool in active_tools if tool.name not in _RESEARCH_TOOL_NAMES
                    ]
                active = plain[name].bind_tools(active_tools)
                sequence = FORCED_TOOL_SEQUENCE.get(name)
                if sequence and used < len(sequence):
                    active = plain[name].bind_tools(
                        tool_groups.get(name, []),
                        tool_choice=sequence[used],
                    )
                else:
                    mandatory = FORCED_UNORDERED_TOOLS.get(name)
                    if mandatory:
                        missing = [
                            t
                            for t in mandatory
                            if t not in _tools_called_this_turn(messages)
                        ]
                        if len(missing) == 1:
                            active = plain[name].bind_tools(
                                tool_groups.get(name, []),
                                tool_choice=missing[0],
                            )
                        elif len(missing) >= 2:
                            active = plain[name].bind_tools(
                                tool_groups.get(name, []),
                                tool_choice="any",
                            )
            log.info(
                "agent node [%s] (model=%s): llm call "
                "(tool_rounds_used=%d, messages=%d)",
                name,
                models[name],
                used,
                len(messages),
            )
            directive = SystemMessage(content=NODE_DIRECTIVES[name])
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
    return builder.compile(checkpointer=checkpointer)


def compile_agrisense_graph(checkpointer=None):
    """Factory helper to build and compile the AgriSense graph with default tools."""
    return build_graph({}, checkpointer=checkpointer)


# Compiled default graph object for direct inspection & visualization
app_graph = compile_agrisense_graph()

