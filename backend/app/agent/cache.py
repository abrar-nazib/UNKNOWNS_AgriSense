"""Semantic query cache for accelerating repeated agricultural questions."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger("agrisense.agent.cache")


class SemanticQueryCache:
    """In-memory cosine similarity cache for quick advisory responses."""

    def __init__(self, similarity_threshold: float = 0.92):
        self.similarity_threshold = similarity_threshold
        # query_text -> (vector, response_text, intent)
        self._cache: List[Tuple[str, List[float], str, str]] = []

    def get(self, query: str, query_vector: List[float]) -> Optional[Tuple[str, str]]:
        """Return (response_text, intent) if a cached query matches with high similarity."""
        if not query_vector or not self._cache:
            return None

        q_vec = np.array(query_vector, dtype=np.float32)
        norm_q = np.linalg.norm(q_vec)
        if norm_q == 0:
            return None

        best_score = -1.0
        best_match: Optional[Tuple[str, str]] = None

        for cached_text, cached_vec, cached_resp, cached_intent in self._cache:
            c_vec = np.array(cached_vec, dtype=np.float32)
            norm_c = np.linalg.norm(c_vec)
            if norm_c == 0:
                continue
            sim = float(np.dot(q_vec, c_vec) / (norm_q * norm_c))
            if sim > best_score:
                best_score = sim
                best_match = (cached_resp, cached_intent)

        if best_score >= self.similarity_threshold and best_match:
            log.info("Semantic cache HIT (similarity=%.4f) for query: %r", best_score, query[:60])
            return best_match

        return None

    def set(self, query: str, query_vector: List[float], response: str, intent: str) -> None:
        """Cache a verified response for a query vector."""
        if not query_vector or not response:
            return
        if len(self._cache) > 200:
            self._cache.pop(0)  # simple FIFO eviction
        self._cache.append((query, query_vector, response, intent))
        log.info("Semantic cache SET for query: %r (intent=%s)", query[:60], intent)


# Global singleton instance
semantic_cache = SemanticQueryCache()
