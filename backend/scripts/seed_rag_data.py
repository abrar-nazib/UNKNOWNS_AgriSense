"""Seed the RAG vector store from the committed backup — no embedding calls.

Restores ``knowledge_chunks`` from the row-aligned pair written by
``scripts.backup_kb`` (``app/data/kb_seed/kb_chunks.jsonl`` +
``kb_embeddings.npy``). Idempotent per source: every source present in the
backup has its existing chunks replaced, other sources are untouched. Use
this instead of ``scripts.ingest_kb`` whenever the corpus itself hasn't
changed (fresh database, new machine, demo setup) — it needs no API key and
runs in seconds.

Usage (inside the backend container):

    docker compose exec backend python -m scripts.seed_rag_data
"""
from __future__ import annotations

import asyncio
import json

import numpy as np

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import KnowledgeChunk
from app.rag.store import delete_source

from . import backup_kb

_INSERT_BATCH = 500


def load_seed() -> tuple[list[dict], np.ndarray]:
    """Load + validate the backup pair; raises SystemExit on mismatch."""
    chunks_path = backup_kb.CHUNKS_PATH
    embeddings_path = backup_kb.EMBEDDINGS_PATH
    if not chunks_path.is_file() or not embeddings_path.is_file():
        raise SystemExit(
            f"error: seed backup not found under {chunks_path.parent} — "
            "run scripts.ingest_kb then scripts.backup_kb first."
        )
    with open(chunks_path, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    vectors = np.load(embeddings_path)
    if len(chunks) != vectors.shape[0]:
        raise SystemExit(
            f"error: {len(chunks)} chunk rows but {vectors.shape[0]} "
            "embedding rows — backup files are out of sync."
        )
    if vectors.shape[1] != settings.KB_EMBEDDING_DIM:
        raise SystemExit(
            f"error: backup dim {vectors.shape[1]} != configured "
            f"KB_EMBEDDING_DIM {settings.KB_EMBEDDING_DIM} — re-ingest with "
            "the current embedding model instead of seeding."
        )
    return chunks, vectors


async def seed(db) -> dict:
    """Replace every backed-up source's chunks in ``db`` from the seed files."""
    chunks, vectors = load_seed()
    replaced = 0
    for source in sorted({c["source"] for c in chunks}):
        replaced += await delete_source(db, source)
    for start in range(0, len(chunks), _INSERT_BATCH):
        for c, vec in zip(
            chunks[start : start + _INSERT_BATCH],
            vectors[start : start + _INSERT_BATCH],
        ):
            db.add(
                KnowledgeChunk(
                    source=c["source"],
                    chunk_index=c["chunk_index"],
                    page_start=c.get("page_start"),
                    page_end=c.get("page_end"),
                    crop=c.get("crop", ""),
                    topic=c.get("topic", ""),
                    content=c["content"],
                    embedding=vec.tolist(),
                )
            )
        await db.commit()
    return {
        "chunks": len(chunks),
        "replaced": replaced,
        "sources": sorted({c["source"] for c in chunks}),
    }


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        stats = await seed(db)
    print(
        f"seeded {stats['chunks']} chunks from backup "
        f"({stats['replaced']} previous replaced) — sources: {stats['sources']}"
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
