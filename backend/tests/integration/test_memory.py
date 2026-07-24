"""Integration tests for user-scoped long-term (pgvector) memory.

Uses the offline deterministic ``fake`` embeddings (the app default), so no
network calls happen.
"""
from __future__ import annotations

import pytest

from app.agent import memory as memory_mod
from tests.fakes import register_user

pytestmark = pytest.mark.integration


async def _make_user(client, phone: str) -> int:
    resp = await register_user(client, phone)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_saved_memory_is_recalled_for_same_user(client, db_session):
    user_id = await _make_user(client, "01712345678")

    fact = "The farmer grows Boro rice in Tanore upazila."
    await memory_mod.save_memory(db_session, user_id, fact)

    recalled = await memory_mod.recall_memory(
        db_session, user_id, "what crop does the farmer cultivate", k=5
    )
    assert fact in recalled


async def test_memory_is_user_scoped(client, db_session):
    user_a = await _make_user(client, "01712345678")
    user_b = await _make_user(client, "01812345678")

    fact = "User A prefers organic fertilizer for tomatoes."
    await memory_mod.save_memory(db_session, user_a, fact)

    # User B must NOT recall User A's memory.
    recalled_b = await memory_mod.recall_memory(
        db_session, user_b, "fertilizer preference", k=5
    )
    assert fact not in recalled_b
    assert recalled_b == []  # User B has no memories at all.

    # User A still recalls it.
    recalled_a = await memory_mod.recall_memory(
        db_session, user_a, "fertilizer preference", k=5
    )
    assert fact in recalled_a


async def test_blank_content_is_ignored(client, db_session):
    user_id = await _make_user(client, "01712345678")
    await memory_mod.save_memory(db_session, user_id, "   ")
    recalled = await memory_mod.recall_memory(db_session, user_id, "anything", k=5)
    assert recalled == []


# --------------------------------------------------------------------------- #
# Automatic extraction — no save_memory tool call required (the primary model
# never has to decide to "remember" something; a background pass does it).
# --------------------------------------------------------------------------- #
class _StubModel:
    """Minimal stand-in for a chat model: returns one scripted JSON reply."""

    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, messages):
        class _Resp:
            def __init__(self, content):
                self.content = content

        return _Resp(self._content)


async def test_auto_extract_saves_new_durable_fact(client, db_session):
    user_id = await _make_user(client, "01712345678")
    model = _StubModel('["The farmer\'s name is Karim."]')

    saved = await memory_mod.auto_extract_memories(
        db_session,
        user_id,
        model,
        user_text="My name is Karim, nice to meet you.",
        assistant_text="Nice to meet you too, Karim!",
        known=[],
    )
    assert saved == ["The farmer's name is Karim."]

    recalled = await memory_mod.recall_memory(
        db_session, user_id, "farmer's name", k=5
    )
    assert "The farmer's name is Karim." in recalled


async def test_auto_extract_skips_near_duplicate_of_existing_memory(
    client, db_session
):
    user_id = await _make_user(client, "01712345678")
    fact = "The farmer's name is Karim."
    await memory_mod.save_memory(db_session, user_id, fact)

    model = _StubModel(f'["{fact}"]')
    saved = await memory_mod.auto_extract_memories(
        db_session, user_id, model, "hi again", "hello", known=[fact]
    )
    assert saved == []  # already known — not re-saved


async def test_auto_extract_empty_array_saves_nothing(client, db_session):
    user_id = await _make_user(client, "01712345678")
    model = _StubModel("[]")
    saved = await memory_mod.auto_extract_memories(
        db_session, user_id, model, "what's the weather", "It's sunny.", known=[]
    )
    assert saved == []


async def test_auto_extract_never_raises_on_malformed_model_output(
    client, db_session
):
    user_id = await _make_user(client, "01712345678")
    model = _StubModel("not json at all")
    saved = await memory_mod.auto_extract_memories(
        db_session, user_id, model, "hello", "hi", known=[]
    )
    assert saved == []


def test_parse_fact_list_handles_markdown_fence():
    raw = '```json\n["fact one", "fact two"]\n```'
    assert memory_mod._parse_fact_list(raw) == ["fact one", "fact two"]


def test_parse_fact_list_handles_plain_array():
    assert memory_mod._parse_fact_list('["a"]') == ["a"]


def test_parse_fact_list_invalid_json_returns_empty():
    assert memory_mod._parse_fact_list("nonsense") == []


def test_parse_fact_list_non_list_json_returns_empty():
    assert memory_mod._parse_fact_list('{"a": 1}') == []
