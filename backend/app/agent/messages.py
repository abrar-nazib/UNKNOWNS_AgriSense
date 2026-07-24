"""Message construction, replay and persistence mapping — separated by type.

One module, one responsibility per message kind (the runner only orchestrates):

- **SystemMessage**  — ``build_system_messages()``: prompt + authoritative
  Dhaka date-time + rolling summary + recalled memories.
- **HumanMessage**   — ``history_to_lc_messages()``: user rows replay 1:1.
- **AIMessage**      — assistant rows; when a row carries a ``tool_trace``,
  replay reconstructs NATIVE ``tool_calls`` (synthetic ``hist_<id>_<idx>``
  ids). Never flatten traces into prose: models imitate that text (observed
  live: a fabricated "[tool get_weather ... -> {...}]" block pasted verbatim
  into the chat instead of a real call).
- **ToolMessage**    — tool responses; replayed paired to their synthetic
  call ids, and on the write path ``tool_call_traces()`` /
  ``fill_trace_result()`` map live tool activity back into the persisted
  ``ChatMessage.tool_trace``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from ..models import ChatMessage

DHAKA_TZ = ZoneInfo("Asia/Dhaka")


# --------------------------------------------------------------------------- #
# Content helpers
# --------------------------------------------------------------------------- #
def text_of(content: Any) -> str:
    """Flatten LangChain message content (str or list-of-parts) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text" and "text" in part:
                    parts.append(part["text"])
        return "".join(parts)
    return str(content)


# --------------------------------------------------------------------------- #
# SystemMessage construction
# --------------------------------------------------------------------------- #
def build_system_messages(
    system_prompt: str,
    summary: str | None,
    recalled: list[str],
    now: datetime | None = None,
    farmer_name: str | None = None,
) -> list[SystemMessage]:
    """Assemble the per-turn system context in one place."""
    now = now or datetime.now(DHAKA_TZ)
    messages = [
        SystemMessage(content=system_prompt),
        SystemMessage(
            content=(
                "CURRENT DATE & TIME (Asia/Dhaka): "
                f"{now.strftime('%A, %d %B %Y, %H:%M')} "
                f"({now.date().isoformat()}). This is authoritative — use it "
                "for every 'today'/season/date computation."
            )
        ),
    ]
    if summary:
        messages.append(
            SystemMessage(content=f"Conversation summary so far:\n{summary}")
        )
    if recalled:
        joined = "\n".join(f"- {r}" for r in recalled)
        messages.append(
            SystemMessage(
                content=f"Relevant long-term memories about this user:\n{joined}"
            )
        )
    if farmer_name:
        # DB-sourced, not conversation-recalled — always present, every
        # session, regardless of what has (or hasn't) been said or saved to
        # long-term memory. Fixes the class of bug where identity depended on
        # the model choosing to remember/recall a name.
        messages.append(
            SystemMessage(
                content=(
                    f"FARMER IDENTITY: you are speaking with {farmer_name}, "
                    "the logged-in farmer (from their account, available "
                    "every session). Use their name naturally when it reads "
                    "well; never claim not to know it and never ask for it."
                )
            )
        )
    return messages


# --------------------------------------------------------------------------- #
# Reply-language detection (deterministic; prompt rules alone proved too weak
# — Gemini drifted to Bengali for English questions)
# --------------------------------------------------------------------------- #
_BENGALI_RE = re.compile(r"[ঀ-৿]")

# Common romanized-Bengali (Banglish) function words / farm terms.
_BANGLISH_WORDS = {
    "ami", "amar", "amra", "apni", "apnar", "tumi", "tomar", "bhai", "vai",
    "ache", "ase", "ase", "nai", "nei", "ki", "keno", "kemon", "kobe",
    "kothay", "kivabe", "hobe", "hoy", "hoye", "kore", "korbo", "korchi",
    "korte", "korsi", "korsilam", "jomi", "chash", "taka", "bigha", "shotok",
    "dhan", "pani", "sech", "dile", "dibo", "den", "bolen", "bhalo", "valo",
    "moto", "ekhon", "aj", "kal", "jodi", "tahole", "theke", "jonno",
    "accha", "lagbe", "chai", "korle", "bujhtesi", "bujhi", "dekhen",
}


def detect_reply_language(text: str) -> str:
    """Decide the reply language from ONE user message.

    Bengali script -> "bengali". Banglish (romanized Bengali) -> "bengali".
    Otherwise -> "english".
    """
    if _BENGALI_RE.search(text or ""):
        return "bengali"
    words = re.findall(r"[a-z']+", (text or "").lower())
    hits = sum(1 for w in words if w in _BANGLISH_WORDS)
    if hits >= 2 or (hits >= 1 and len(words) <= 4):
        return "bengali"
    return "english"


def language_directive(lang: str) -> SystemMessage:
    """Language instruction from the conversation's language STATE.

    ``lang`` is ``OrchestratorState.reply_language`` ("bengali" | "english"),
    set deterministically by the classify node from the farmer's last message.
    Every specialist node injects this directive so the reply follows the
    state, not model whim.
    """
    if lang == "bengali":
        detail = "Reply in BENGALI SCRIPT (বাংলা)."
    else:
        lang = "english"
        detail = "Reply in ENGLISH."
    return SystemMessage(
        content=(
            "REPLY LANGUAGE FOR THIS TURN (language state, set from the "
            f"farmer's last message): {lang.upper()}. {detail}"
        )
    )


def reply_language_directive(user_message: str) -> SystemMessage:
    """Detect + build in one step (kept for direct/legacy call sites)."""
    return language_directive(detect_reply_language(user_message))


# --------------------------------------------------------------------------- #
# Replay: persisted rows -> native LangChain messages
# --------------------------------------------------------------------------- #
def history_to_lc_messages(history: list[ChatMessage]) -> list:
    """Replay persisted history as NATIVE LangChain messages (see module doc)."""
    lc: list = []
    for m in history:
        if m.role == "user":
            lc.append(HumanMessage(content=m.content))
            continue
        trace = m.tool_trace or []
        if not trace:
            lc.append(AIMessage(content=m.content or ""))
            continue
        tool_calls = []
        tool_msgs = []
        for idx, entry in enumerate(trace):
            call_id = f"hist_{m.id}_{idx}"
            tool_calls.append(
                {
                    "name": entry.get("tool", ""),
                    "args": entry.get("args", {}) or {},
                    "id": call_id,
                    "type": "tool_call",
                }
            )
            tool_msgs.append(
                ToolMessage(
                    content=entry.get("result", "") or "",
                    tool_call_id=call_id,
                )
            )
        lc.append(AIMessage(content=m.content or "", tool_calls=tool_calls))
        lc.extend(tool_msgs)
    return lc


# --------------------------------------------------------------------------- #
# Persistence mapping: live messages -> tool_trace rows
# --------------------------------------------------------------------------- #
def tool_call_traces(msg: AIMessage) -> list[dict]:
    """Trace entries (result pending) for a live AIMessage's tool_calls."""
    return [
        {
            "tool": tc.get("name", ""),
            "args": tc.get("args", {}) or {},
            "result": "",
        }
        for tc in msg.tool_calls or []
    ]


def fill_trace_result(trace: list, idx: int, tool_msg: ToolMessage) -> list | None:
    """Return a new trace list with entry ``idx`` filled from a ToolMessage.

    Returns None when idx is out of range (caller skips the update).
    """
    if not (0 <= idx < len(trace)):
        return None
    updated_entry = dict(trace[idx])
    updated_entry["result"] = text_of(tool_msg.content)
    new_trace = list(trace)
    new_trace[idx] = updated_entry
    return new_trace
