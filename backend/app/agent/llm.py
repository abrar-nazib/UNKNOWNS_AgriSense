"""Chat-model and embeddings factories."""
from __future__ import annotations

import hashlib
from typing import List

import numpy as np
from langchain_core.embeddings import Embeddings

from ..config import settings


def build_chat_model(model: str | None = None):
    """Build an OpenRouter chat model.

    ``model`` overrides the default — each graph node can run its own LLM
    (e.g. flash-lite for classification/extraction, flash for advice).
    Raises a clear error when the API key is missing.
    """
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. The chat model requires an "
            "OpenRouter API key to run. Set OPENROUTER_API_KEY in the "
            "environment (see .env.example)."
        )

    from langchain_openrouter import ChatOpenRouter

    return ChatOpenRouter(
        model=model or settings.OPENROUTER_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        temperature=0,
    )


class FakeEmbeddings(Embeddings):
    """Deterministic, offline embeddings.

    Hashes text into a reproducible float vector of length ``EMBEDDING_DIM``
    and L2-normalizes it so cosine distance behaves sensibly. Requires zero
    external calls, letting the whole stack run offline.
    """

    def __init__(self, dim: int):
        self.dim = dim

    def _embed(self, text: str) -> List[float]:
        # Seed a deterministic RNG from a stable hash of the text.
        digest = hashlib.sha256((text or "").encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self.dim).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> List[float]:
        return self.embed_query(text)


def _build_embeddings_provider(provider: str, dim: int) -> Embeddings:
    """Shared provider switch — each table picks its own provider + dim."""
    provider = (provider or "").lower()
    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. OpenRouter embeddings require "
                "the same key as the chat models (see .env.example) — or "
                "switch the provider to 'fake'."
            )
        from langchain_openai import OpenAIEmbeddings

        # OpenRouter's /embeddings is OpenAI-compatible but takes raw strings
        # (no client-side tiktoken token arrays) and vendor-prefixed slugs.
        # Native dim of text-embedding-3-small is 1536 — don't pass
        # `dimensions`; not all routed providers honor it.
        return OpenAIEmbeddings(
            model=settings.KB_EMBED_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            check_embedding_ctx_length=False,
        )
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. OpenAI embeddings require an API "
                "key (see .env.example) — or switch the provider to 'fake'."
            )
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.OPENAI_EMBED_MODEL,
            api_key=settings.OPENAI_API_KEY,
            dimensions=dim,
        )
    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.OLLAMA_EMBED_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
        )
    return FakeEmbeddings(dim=dim)


def build_embeddings() -> Embeddings:
    """Embeddings for the long-term memory table (768-dim by default)."""
    return _build_embeddings_provider(
        settings.EMBEDDINGS_PROVIDER, settings.EMBEDDING_DIM
    )


def build_kb_embeddings() -> Embeddings:
    """Embeddings for the knowledge-base table.

    Default: OpenRouter-routed ``openai/text-embedding-3-small`` (1536-dim) —
    same API key as the chat models.

    Kept separate from memory embeddings: the two pgvector tables have
    different dimensions and may use different providers (PLAN.md D3).
    """
    return _build_embeddings_provider(
        settings.KB_EMBEDDINGS_PROVIDER, settings.KB_EMBEDDING_DIM
    )
