"""RAG knowledge base: chunking, ingestion and pgvector retrieval.

Modular by design — new corpora (DAE/IPM notes, extension manuals) plug in by
calling ``ingest_document`` with a new ``source`` name; retrieval is shared.
"""
from .chunker import Chunk, chunk_markdown
from .store import delete_source, ingest_document, search_kb

__all__ = [
    "Chunk",
    "chunk_markdown",
    "delete_source",
    "ingest_document",
    "search_kb",
]
