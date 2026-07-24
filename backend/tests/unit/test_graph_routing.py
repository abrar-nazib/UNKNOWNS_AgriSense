"""Unit tests for multi-node graph routing helpers."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import (
    AGENTS,
    _current_turn_tool_rounds,
    classify_heuristic,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text,expected",
    [
        # Weather is a TOOL on the advisor, not a node — weather questions
        # route to the advisor for grounded get_weather answers.
        ("আবহাওয়া কেমন?", "advisor"),
        ("Will it rain tomorrow?", "advisor"),
        ("agami 3 dine bristi hobe?", "advisor"),
        ("amar 3 bigha jomi ase", "intake"),
        ("budget 80k, sech ase", "intake"),
        ("আমার জমির মাটি বেলে", "intake"),
        ("How do I grow rice?", "advisor"),
        ("hello", "advisor"),
        ("dhonnobad", "advisor"),
        # Crop-choice questions route to the dedicated recommender node.
        ("Which crop should I plant this rabi season?", "recommender"),
        ("What should I grow to make profit?", "recommender"),
        ("Recommend a crop for my farm", "recommender"),
        ("kon fosol lagabo ebar?", "recommender"),
        ("ki chash korle labjonok hobe?", "recommender"),
        ("এই মৌসুমে কোন ফসল চাষ করব?", "recommender"),
        ("কোন ফসল লাভজনক হবে?", "recommender"),
        ("I chose wheat. Make a season plan", "planner"),
        ("Create a calendar for potato", "planner"),
        ("সরিষার প্ল্যান বানাও", "planner"),
        ("Wheat", "planner"),
        ("গম", "planner"),
        ("সরিষা", "planner"),
        ("Calculate ROI and break-even for wheat", "finance"),
        ("Show me a cost breakdown for mustard", "finance"),
        ("If wheat sells at 42 taka, recalculate the profit", "finance"),
        ("Find suppliers for 100 kg urea near my farm", "market_researcher"),
        ("What is the current potato market price?", "market_researcher"),
        ("Should I sell my wheat now or store it?", "market_researcher"),
    ],
)
def test_classify_heuristic(text, expected):
    assert classify_heuristic(text) == expected


def test_weather_beats_intake_when_both_present():
    # "brishti" (weather) + "jomi" (intake) -> the advisor grounds the
    # weather answer instead of slot-filling.
    assert classify_heuristic("amar jomi te bristi hobe ki?") == "advisor"


def test_recommend_beats_intake_and_weather():
    # A crop-choice ask wins even when farm facts / weather words appear.
    assert (
        classify_heuristic("amar 3 bigha jomi te kon fosol lagabo?")
        == "recommender"
    )
    assert (
        classify_heuristic("bristi hobe naki? ki chash korbo ebar?")
        == "recommender"
    )


def test_agents_registry():
    assert set(AGENTS) == {"intake", "advisor", "recommender", "planner", "finance", "market_researcher"}


def test_crop_choice_beats_plan_when_crop_is_not_selected_yet():
    assert (
        classify_heuristic("Recommend a crop and then make a season plan")
        == "recommender"
    )


def test_crop_choice_beats_finance_when_farmer_has_not_selected_a_crop():
    assert classify_heuristic("What should I grow to make profit?") == "recommender"


def test_hypothetical_crop_choice_is_not_misrouted_as_finance_scenario():
    assert classify_heuristic("What if I plant wheat this rabi season?") == "recommender"


@pytest.mark.asyncio
async def test_explicit_market_intent_does_not_allow_llm_to_downgrade_to_advisor(monkeypatch):
    async def advisor_reply(*_args, **_kwargs):
        class Reply:
            content = "advisor"
        return Reply()

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return await advisor_reply()

    monkeypatch.setattr("app.agent.graph.build_chat_model", lambda _model: Model())
    from app.agent.graph import _classify

    assert await _classify("Find suppliers for 100 kg urea near my farm") == "market_researcher"


def test_full_plan_beats_finance_for_a_selected_crop():
    assert classify_heuristic("Make a costed season plan for wheat") == "planner"


def test_tool_rounds_exclude_replayed_history():
    messages = [
        HumanMessage(content="hi"),
        # Replayed from history (synthetic hist_ ids) — must NOT count.
        AIMessage(
            content="",
            tool_calls=[
                {"name": "x", "args": {}, "id": "hist_5_0", "type": "tool_call"}
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "y", "args": {}, "id": "hist_6_0", "type": "tool_call"}
            ],
        ),
        # Live this turn — counts.
        AIMessage(
            content="",
            tool_calls=[
                {"name": "z", "args": {}, "id": "call_live_1", "type": "tool_call"}
            ],
        ),
    ]
    assert _current_turn_tool_rounds(messages) == 1


def test_tool_rounds_zero_for_plain_conversation():
    assert (
        _current_turn_tool_rounds(
            [HumanMessage(content="q"), AIMessage(content="a")]
        )
        == 0
    )


# --------------------------------------------------------------------------- #
# Reply-language STATE (state.reply_language -> per-node directive)
# --------------------------------------------------------------------------- #
def test_language_directive_from_state_value():
    from app.agent.messages import language_directive

    bn = language_directive("bengali")
    en = language_directive("english")
    assert "BENGALI" in bn.content and "বাংলা" in bn.content
    assert "ENGLISH" in en.content
    # Unknown/empty state falls back to english, never crashes.
    assert "ENGLISH" in language_directive("").content
    assert "ENGLISH" in language_directive("klingon").content


@pytest.mark.parametrize(
    "text,lang",
    [
        ("আবহাওয়া কেমন?", "bengali"),
        ("bhai amar jomi ase", "bengali"),
        ("What should I plant?", "english"),
    ],
)
def test_state_language_detection_matches_last_message(text, lang):
    # classify_node stores detect_reply_language(last message) into
    # state.reply_language — this pins the detector the state relies on.
    from app.agent.messages import detect_reply_language

    assert detect_reply_language(text) == lang
