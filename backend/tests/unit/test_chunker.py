"""Unit tests for the recursive KB chunker (page tracking + splitting)."""
from __future__ import annotations

from app.rag.chunker import chunk_markdown

PAGED_DOC = (
    "<!-- Page 10 (embedded) -->\n\n"
    "Mustard is an important oilseed crop of Bangladesh.\n\n"
    + ("Urea should be applied in two equal splits. " * 60)
    + "\n\n<!-- Page 11 (embedded) -->\n\n"
    + ("Phosphorus is applied entirely at final land preparation. " * 60)
    + "\n\n<!-- Page 12 (embedded) -->\n\n"
    "Boron deficiency causes flower drop in mustard.\n"
)


def test_empty_input_yields_no_chunks():
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n  ") == []
    # A document that is only page markers has no content either.
    assert chunk_markdown("<!-- Page 1 (embedded) -->\n<!-- Page 2 -->") == []


def test_markers_are_stripped_and_pages_tracked():
    chunks = chunk_markdown(PAGED_DOC, chunk_size=800, chunk_overlap=100)
    assert len(chunks) > 2
    for c in chunks:
        assert "<!--" not in c.content
        assert c.page_start is not None and c.page_end is not None
        assert 10 <= c.page_start <= c.page_end <= 12
    # First chunk starts on page 10, last chunk ends on page 12.
    assert chunks[0].page_start == 10
    assert chunks[-1].page_end == 12
    # Sequential indexes.
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_size_respected():
    chunks = chunk_markdown(PAGED_DOC, chunk_size=800, chunk_overlap=100)
    assert all(len(c.content) <= 800 for c in chunks)


def test_overlap_between_consecutive_chunks():
    # One long paragraph forces sentence-level splits with overlap carried.
    text = "The quick brown fox jumps over the lazy dog. " * 100
    chunks = chunk_markdown(text, chunk_size=500, chunk_overlap=120)
    assert len(chunks) >= 2
    # The tail of chunk N reappears at the head of chunk N+1.
    tail = chunks[0].content[-60:]
    assert tail in chunks[1].content


def test_plain_text_without_markers_has_no_pages():
    chunks = chunk_markdown("Just a small agronomy note about liming acidic soils.")
    assert len(chunks) == 1
    assert chunks[0].page_start is None
    assert chunks[0].page_end is None
