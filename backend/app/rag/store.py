"""pgvector-backed knowledge store: idempotent ingest + top-k retrieval."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import build_kb_embeddings
from ..config import settings
from ..models import KnowledgeChunk
from .chunker import chunk_markdown

_embeddings = None

_EMBED_BATCH = 64


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = build_kb_embeddings()
    return _embeddings


async def delete_source(db: AsyncSession, source: str) -> int:
    """Remove all chunks of ``source``; returns the number deleted."""
    result = await db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.source == source)
    )
    await db.commit()
    return result.rowcount or 0


async def ingest_document(
    db: AsyncSession,
    text: str,
    source: str,
    crop: str = "",
    topic: str = "",
    on_progress=None,
) -> dict:
    """Chunk, embed and store one document under ``source``.

    Idempotent: existing chunks for the same ``source`` are replaced, so the
    ingest script can be re-run safely after corpus edits.
    """
    source = source.strip()
    if not source:
        raise ValueError("source must be non-empty")

    chunks = chunk_markdown(text)
    replaced = await delete_source(db, source)
    if not chunks:
        return {"source": source, "chunks": 0, "replaced": replaced}

    embedder = _get_embeddings()
    for batch_start in range(0, len(chunks), _EMBED_BATCH):
        batch = chunks[batch_start : batch_start + _EMBED_BATCH]
        vectors = await embedder.aembed_documents([c.content for c in batch])
        for chunk, vector in zip(batch, vectors):
            db.add(
                KnowledgeChunk(
                    source=source,
                    chunk_index=chunk.index,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    crop=(crop or "").strip().lower()[:60],
                    topic=(topic or "").strip()[:120],
                    content=chunk.content,
                    embedding=vector,
                )
            )
        if on_progress:
            on_progress(min(batch_start + _EMBED_BATCH, len(chunks)), len(chunks))
    await db.commit()
    return {"source": source, "chunks": len(chunks), "replaced": replaced}


async def search_kb(
    db: AsyncSession,
    query: str,
    k: Optional[int] = None,
    crop: str = "",
) -> list[dict]:
    """Top-k chunks nearest to ``query`` by cosine distance.

    Returns dicts with content, source, pages and similarity (1 - distance).
    ``crop`` filters to chunks tagged with that crop OR untagged (general)
    chunks, so a crop filter never hides the general agronomy corpus.
    """
    query = (query or "").strip()
    if not query:
        return []
    vector = await _get_embeddings().aembed_query(query)

    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    stmt = select(KnowledgeChunk, distance.label("distance"))
    crop = (crop or "").strip().lower()
    if crop:
        stmt = stmt.where(
            (KnowledgeChunk.crop == crop) | (KnowledgeChunk.crop == "")
        )
    stmt = stmt.order_by(distance).limit(k or settings.KB_TOP_K)

    result = await db.execute(stmt)
    hits = []
    for row, dist in result.all():
        hits.append(
            {
                "source": row.source,
                "chunk_index": row.chunk_index,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "crop": row.crop,
                "topic": row.topic,
                "content": row.content,
                "similarity": round(1.0 - float(dist), 4),
            }
        )
    return hits
