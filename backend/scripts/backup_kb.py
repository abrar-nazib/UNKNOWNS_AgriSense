"""Snapshot the knowledge_chunks table to a re-seedable on-disk backup.

Writes two row-aligned files under ``app/data/kb_seed/``:

- ``kb_chunks.jsonl``    — one JSON object per chunk (source, chunk_index,
                           pages, crop, topic, content), embedding excluded
- ``kb_embeddings.npy``  — float32 matrix [n_chunks, KB_EMBEDDING_DIM];
                           row i is the embedding of jsonl line i

Together they let ``scripts.seed_rag_data`` restore the vector store with
ZERO embedding-API calls (fresh db, teammate machine, demo box). Re-run this
after any re-ingest so the committed seed stays current.

Usage (inside the backend container):

    docker compose exec backend python -m scripts.backup_kb
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import numpy as np
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import KnowledgeChunk

SEED_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "kb_seed"
CHUNKS_PATH = SEED_DIR / "kb_chunks.jsonl"
EMBEDDINGS_PATH = SEED_DIR / "kb_embeddings.npy"


async def backup(db) -> dict:
    """Dump all of ``knowledge_chunks`` in ``db`` to the seed-file pair."""
    result = await db.execute(
        select(KnowledgeChunk).order_by(
            KnowledgeChunk.source, KnowledgeChunk.chunk_index
        )
    )
    rows = result.scalars().all()

    if not rows:
        raise SystemExit("error: knowledge_chunks is empty — ingest first.")

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    vectors = np.asarray([np.asarray(r.embedding) for r in rows], dtype=np.float32)
    if vectors.shape[1] != settings.KB_EMBEDDING_DIM:
        raise SystemExit(
            f"error: stored dim {vectors.shape[1]} != configured "
            f"KB_EMBEDDING_DIM {settings.KB_EMBEDDING_DIM}"
        )

    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(
                json.dumps(
                    {
                        "source": r.source,
                        "chunk_index": r.chunk_index,
                        "page_start": r.page_start,
                        "page_end": r.page_end,
                        "crop": r.crop,
                        "topic": r.topic,
                        "content": r.content,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    np.save(EMBEDDINGS_PATH, vectors)

    sources = sorted({r.source for r in rows})
    return {
        "chunks": len(rows),
        "sources": sources,
        "vector_mb": vectors.nbytes / 1024 / 1024,
    }


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        stats = await backup(db)
    print(
        f"backed up {stats['chunks']} chunks from "
        f"{len(stats['sources'])} source(s) {stats['sources']} -> "
        f"{CHUNKS_PATH.name} + {EMBEDDINGS_PATH.name} "
        f"({stats['vector_mb']:.1f} MB of vectors)"
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
