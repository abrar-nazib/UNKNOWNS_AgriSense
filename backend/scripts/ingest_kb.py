"""Ingest agronomy documents (.md/.txt) into the RAG knowledge base.

Idempotent: re-running replaces all chunks of the same --source.

Usage (inside the backend container; copy the file in first if needed):

    docker cp test_frg_doc.md argi_backend:/tmp/frg.md
    docker compose exec backend python -m scripts.ingest_kb /tmp/frg.md \
        --source "FRG 2024"

    # optional facets for filtered retrieval
    python -m scripts.ingest_kb notes/mustard.md --source "DAE mustard" \
        --crop mustard --topic "fertilizer split"
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

from app.config import settings
from app.database import AsyncSessionLocal
from app.rag import search_kb, store


async def _run(args: argparse.Namespace) -> None:
    path = pathlib.Path(args.path)
    text = path.read_text(encoding="utf-8")
    source = args.source or path.stem

    print(
        f"Ingesting {path.name} as source={source!r} "
        f"(provider={settings.KB_EMBEDDINGS_PROVIDER}, "
        f"model={settings.KB_EMBED_MODEL}, "
        f"chunk={settings.KB_CHUNK_SIZE_CHARS}c/"
        f"{settings.KB_CHUNK_OVERLAP_CHARS}c overlap)"
    )

    def on_progress(done: int, total: int) -> None:
        print(f"  embedded {done}/{total} chunks", flush=True)

    async with AsyncSessionLocal() as db:
        stats = await store.ingest_document(
            db,
            text,
            source=source,
            crop=args.crop,
            topic=args.topic,
            on_progress=on_progress,
        )
        print(
            f"Done: {stats['chunks']} chunks stored "
            f"({stats['replaced']} previous replaced)."
        )

        if args.verify:
            hits = await search_kb(db, args.verify, k=3)
            print(f"\nVerify query: {args.verify!r}")
            for h in hits:
                pages = (
                    f"pp.{h['page_start']}-{h['page_end']}"
                    if h["page_start"]
                    else "no page info"
                )
                print(
                    f"  [{h['similarity']:.3f}] {h['source']} {pages}: "
                    f"{h['content'][:100]!r}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path to a .md or .txt document")
    parser.add_argument(
        "--source",
        default="",
        help="Corpus name (default: file stem). Re-ingest replaces this source.",
    )
    parser.add_argument("--crop", default="", help="Optional crop facet tag")
    parser.add_argument("--topic", default="", help="Optional topic facet tag")
    parser.add_argument(
        "--verify",
        default="",
        help="Optional English query to run after ingest as a smoke test",
    )
    args = parser.parse_args()
    if not pathlib.Path(args.path).is_file():
        sys.exit(f"error: no such file: {args.path}")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
