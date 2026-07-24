"""Integration tests: KB backup -> seed_rag_data restore round-trip.

Uses fake embeddings (forced in conftest). The seed path must reproduce the
vector store byte-for-byte-equivalently WITHOUT any embedding calls.
"""
from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import delete, select

from app.models import KnowledgeChunk
from app.rag import ingest_document, search_kb
from scripts import backup_kb, seed_rag_data

DOC = (
    "<!-- Page 87 (embedded) -->\n\n"
    "Mustard fertilizer dose: urea applied in two equal splits at sowing "
    "and flowering stage."
)


def _point_at(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_kb, "SEED_DIR", tmp_path)
    monkeypatch.setattr(backup_kb, "CHUNKS_PATH", tmp_path / "kb_chunks.jsonl")
    monkeypatch.setattr(
        backup_kb, "EMBEDDINGS_PATH", tmp_path / "kb_embeddings.npy"
    )


@pytest.mark.asyncio
async def test_backup_then_seed_restores_identical_store(
    db_session, tmp_path, monkeypatch
):
    _point_at(tmp_path, monkeypatch)
    await ingest_document(db_session, DOC, source="FRG 2024")
    original = (await db_session.execute(select(KnowledgeChunk))).scalar_one()
    original_vec = np.asarray(original.embedding, dtype=np.float32)

    stats = await backup_kb.backup(db_session)
    assert stats["chunks"] == 1 and stats["sources"] == ["FRG 2024"]

    # Wipe the table, restore purely from the backup files.
    await db_session.execute(delete(KnowledgeChunk))
    await db_session.commit()

    seeded = await seed_rag_data.seed(db_session)
    assert seeded["chunks"] == 1 and seeded["replaced"] == 0

    row = (await db_session.execute(select(KnowledgeChunk))).scalar_one()
    assert row.source == "FRG 2024"
    assert row.page_start == 87 and row.page_end == 87
    assert row.content == original.content
    np.testing.assert_allclose(
        np.asarray(row.embedding, dtype=np.float32), original_vec, atol=1e-6
    )

    # Retrieval works from the seeded store (no embedding of documents).
    hits = await search_kb(db_session, DOC.split("\n\n", 1)[1])
    assert hits and hits[0]["source"] == "FRG 2024"


@pytest.mark.asyncio
async def test_seed_is_idempotent_replaces_not_duplicates(
    db_session, tmp_path, monkeypatch
):
    _point_at(tmp_path, monkeypatch)
    await ingest_document(db_session, DOC, source="FRG 2024")
    await backup_kb.backup(db_session)

    first = await seed_rag_data.seed(db_session)
    second = await seed_rag_data.seed(db_session)
    assert first["replaced"] == 1  # replaced the ingested original
    assert second["replaced"] == 1  # replaced the first seed, no duplicates
    rows = (await db_session.execute(select(KnowledgeChunk))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_seed_rejects_dim_mismatch(db_session, tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch)
    await ingest_document(db_session, DOC, source="FRG 2024")
    await backup_kb.backup(db_session)
    # Corrupt: wrong-dimension matrix.
    np.save(tmp_path / "kb_embeddings.npy", np.zeros((1, 8), dtype=np.float32))
    with pytest.raises(SystemExit, match="dim"):
        seed_rag_data.load_seed()
