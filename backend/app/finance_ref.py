"""Seeded per-crop cost/price reference data (Tier 0 #5, PLAN.md Task 7).

Data bundle: ``app/data/finance_reference.json`` — HAND-AUTHORED placeholder
figures (``seeded_demo_value``), not a live feed: no working Bangladesh
market-price API exists yet (DAM's AJAX endpoint 500s even with auth — see
docs/PLAN.md D4). Keyed by the crop's EXACT CZIS catalog name (case-insensitive)
so ``calculate_financials`` can look a crop straight up after ``czis_list_crops``.
Every number here is meant to be replaced by a real feed later; farmer-stated
figures always override these in the finance tool (labeled ``farmer_estimate``).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DATA_PATH = Path(__file__).parent / "data" / "finance_reference.json"


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def crop_reference(name: str) -> Optional[dict]:
    """Seeded cost/yield/price reference for one crop, by exact CZIS name
    (case-insensitive). None if this crop has no seeded reference yet (e.g.
    perennial/orchard crops — Mango, Banana, Litchi — are out of scope for a
    per-season decimal-cost model)."""
    return _bundle()["crops"].get((name or "").strip().lower())


def fertilizer_prices() -> dict:
    return _bundle()["fertilizer_prices_tk_per_kg"]


def source() -> str:
    return _bundle().get("_source", "")


def covered_crops() -> list[str]:
    return sorted(_bundle()["crops"].keys())
