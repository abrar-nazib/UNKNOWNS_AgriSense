"""History replay must reconstruct NATIVE tool-call messages.

Regression guard for a live bug: tool traces flattened into assistant text as
"[tool X args=... -> result]" taught the model to IMITATE that format — it
pasted a fabricated tool block verbatim into the chat instead of calling the
tool. Replay must therefore produce AIMessage.tool_calls + ToolMessage pairs,
never imitable prose.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.messages import history_to_lc_messages as _history_to_lc_messages
from app.models import ChatMessage

pytestmark = pytest.mark.unit


def _msg(id_, role, content="", trace=None):
    m = ChatMessage(session_id=1, role=role, content=content, tool_trace=trace or [])
    m.id = id_
    return m


def test_plain_messages_replay_as_human_and_ai():
    out = _history_to_lc_messages(
        [_msg(1, "user", "hello"), _msg(2, "assistant", "hi there")]
    )
    assert isinstance(out[0], HumanMessage) and out[0].content == "hello"
    assert isinstance(out[1], AIMessage) and out[1].content == "hi there"
    assert not out[1].tool_calls


def test_traced_assistant_replays_as_native_tool_call_plus_toolmessage():
    trace = [
        {
            "tool": "get_weather",
            "args": {"location": "", "days": 7},
            "result": '{"summary": {"total_rain_mm": 43.7}}',
        }
    ]
    out = _history_to_lc_messages([_msg(7, "assistant", "", trace)])

    ai, tm = out
    assert isinstance(ai, AIMessage)
    assert ai.tool_calls[0]["name"] == "get_weather"
    assert ai.tool_calls[0]["args"] == {"location": "", "days": 7}
    assert ai.tool_calls[0]["id"] == "hist_7_0"
    assert isinstance(tm, ToolMessage)
    assert tm.tool_call_id == "hist_7_0"
    assert "43.7" in tm.content
    # CRITICAL: no imitable "[tool ...]" text anywhere in replayed content.
    assert "[tool" not in (ai.content or "")


def test_multi_tool_trace_produces_one_toolmessage_each():
    trace = [
        {"tool": "get_farm_profile", "args": {}, "result": "{}"},
        {"tool": "update_farm_profile", "args": {"budget_bdt": 80000}, "result": "{}"},
    ]
    out = _history_to_lc_messages([_msg(9, "assistant", "", trace)])
    ai = out[0]
    assert len(ai.tool_calls) == 2
    tool_msgs = [m for m in out[1:] if isinstance(m, ToolMessage)]
    assert [t.tool_call_id for t in tool_msgs] == ["hist_9_0", "hist_9_1"]


def test_system_messages_carry_authoritative_datetime_and_context():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.agent.messages import build_system_messages

    now = datetime(2026, 7, 24, 15, 30, tzinfo=ZoneInfo("Asia/Dhaka"))
    msgs = build_system_messages(
        "PROMPT", "old summary", ["likes mustard"], now=now
    )
    assert msgs[0].content == "PROMPT"
    assert "2026-07-24" in msgs[1].content and "authoritative" in msgs[1].content
    assert "old summary" in msgs[2].content
    assert "likes mustard" in msgs[3].content
    # No summary/memories -> only prompt + datetime.
    assert len(build_system_messages("P", None, [], now=now)) == 2


def test_farmer_identity_injected_from_db_not_conversation():
    """The farmer's name must be authoritative from the account, always
    present, regardless of whether it was ever said/saved/recalled in chat
    (regression: farmer identity used to depend entirely on the model
    choosing to save/recall it as a memory)."""
    from app.agent.messages import build_system_messages

    msgs = build_system_messages("P", None, [], farmer_name="Karim")
    identity = msgs[-1].content
    assert "Karim" in identity
    assert "never ask for it" in identity

    # No farmer_name -> no identity message added at all.
    msgs_anon = build_system_messages("P", None, [])
    assert not any("FARMER IDENTITY" in m.content for m in msgs_anon)


def test_tool_call_traces_and_fill_result_roundtrip():
    from app.agent.messages import fill_trace_result, tool_call_traces

    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_weather", "args": {"days": 3}, "id": "c1", "type": "tool_call"}
        ],
    )
    traces = tool_call_traces(ai)
    assert traces == [{"tool": "get_weather", "args": {"days": 3}, "result": ""}]

    filled = fill_trace_result(traces, 0, ToolMessage(content="rain", tool_call_id="c1"))
    assert filled[0]["result"] == "rain"
    assert traces[0]["result"] == ""  # original untouched (new list returned)
    assert fill_trace_result(traces, 5, ToolMessage(content="x", tool_call_id="c1")) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("আমি তানোরে শীতের ফসল করতে চাই", "bengali"),
        ("vai amar jomi Naogaon side e. pani ase but beshi na", "bengali"),
        ("accha, sech dile kobe dile bhalo hoy?", "bengali"),
        ("Will it rain in my area in the next 3 days?", "english"),
        ("What crop should I plant this winter season?", "english"),
        ("ki obostha", "bengali"),  # short Banglish
        ("mixed: dhan er jonno pani lagbe kobe?", "bengali"),
    ],
)
def test_detect_reply_language(text, expected):
    from app.agent.messages import detect_reply_language

    assert detect_reply_language(text) == expected


def test_reply_language_directive_wording():
    from app.agent.messages import reply_language_directive

    en = reply_language_directive("How are you?")
    bn = reply_language_directive("bhai jomi ase 3 bigha")
    assert "ENGLISH" in en.content
    assert "BENGALI" in bn.content


def test_mixed_conversation_order_preserved():
    history = [
        _msg(1, "user", "আবহাওয়া?"),
        _msg(
            2,
            "assistant",
            "",
            [{"tool": "get_weather", "args": {}, "result": "rain"}],
        ),
        _msg(3, "assistant", "বৃষ্টি হবে।"),
        _msg(4, "user", "ধন্যবাদ"),
    ]
    out = _history_to_lc_messages(history)
    kinds = [type(m).__name__ for m in out]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage", "HumanMessage"]
