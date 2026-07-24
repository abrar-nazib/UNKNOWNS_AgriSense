"""Recursive markdown chunker that preserves FRG page citations.

The FRG corpus (pdftotext → markdown) marks page boundaries with
``<!-- Page N (embedded) -->`` comments. We strip those markers, build a
char-offset → page map, recursively split the clean text
(paragraph → line → sentence → word boundaries), then map each chunk's
start/end offsets back to a page range so every retrieved chunk can cite
"FRG 2024, pp. X-Y".
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

_PAGE_MARKER = re.compile(r"<!--\s*Page\s+(\d+)[^>]*-->")


@dataclass
class Chunk:
    content: str
    index: int
    page_start: Optional[int]
    page_end: Optional[int]


def _strip_markers(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Remove page markers; return (clean_text, [(clean_offset, page_no)])."""
    boundaries: list[tuple[int, int]] = []
    parts: list[str] = []
    clean_len = 0
    last_end = 0
    for m in _PAGE_MARKER.finditer(text):
        segment = text[last_end : m.start()]
        parts.append(segment)
        clean_len += len(segment)
        boundaries.append((clean_len, int(m.group(1))))
        last_end = m.end()
    parts.append(text[last_end:])
    return "".join(parts), boundaries


def _page_at(boundaries: list[tuple[int, int]], offset: int) -> Optional[int]:
    """Page containing ``offset`` (None before the first marker / no markers)."""
    if not boundaries:
        return None
    idx = bisect_right([b[0] for b in boundaries], offset) - 1
    return boundaries[idx][1] if idx >= 0 else None


def chunk_markdown(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> list[Chunk]:
    """Recursively split markdown into overlapping chunks with page ranges."""
    clean, boundaries = _strip_markers(text or "")
    if not clean.strip():
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.KB_CHUNK_SIZE_CHARS,
        chunk_overlap=(
            chunk_overlap
            if chunk_overlap is not None
            else settings.KB_CHUNK_OVERLAP_CHARS
        ),
        separators=["\n\n", "\n", ". ", " ", ""],
        add_start_index=True,
    )
    chunks: list[Chunk] = []
    for i, doc in enumerate(splitter.create_documents([clean])):
        content = doc.page_content.strip()
        if not content:
            continue
        start = doc.metadata.get("start_index", 0)
        chunks.append(
            Chunk(
                content=content,
                index=len(chunks),
                page_start=_page_at(boundaries, start),
                page_end=_page_at(boundaries, start + len(doc.page_content) - 1),
            )
        )
    return chunks
