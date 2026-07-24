"""Bundled DAE BAMIS crop-weather calendar accessors (Tier 0 #4 / Task 6).

Thin read-only loader over ``data/bd_crop_calendar.json`` — the same pattern as
``soil.py`` and ``patterns.py``. All dates/quantities are a labelled BAMIS + FRG
reference snapshot; the deterministic engine (``engines/season_plan.py``) turns
one entry into a dated plan. This module never fetches anything.
"""
from __future__ import annotations

import functools
import json
import pathlib
from typing import Optional

_PATH = pathlib.Path(__file__).parent / "data" / "bd_crop_calendar.json"

# Farmer-facing crop names (Bangla/Banglish/English) -> canonical calendar key.
_ALIASES = {
    "sarisha": "mustard", "sorisha": "mustard", "shorisha": "mustard",
    "rai": "mustard", "mustard": "mustard",
    "gom": "wheat", "wheat": "wheat",
    "alu": "potato", "aloo": "potato", "potato": "potato",
    "bhutta": "maize", "bhutto": "maize", "corn": "maize", "maize": "maize",
    "boro": "boro_rice", "boro_rice": "boro_rice", "boro dhan": "boro_rice",
    "boro rice": "boro_rice", "dhan": "boro_rice", "rice": "boro_rice",
}


@functools.lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def source() -> str:
    return _load().get("source", "")


def list_crops() -> list[str]:
    """Canonical keys of the calendars we support."""
    return sorted(_load().get("crops", {}).keys())


def resolve_key(name: str) -> Optional[str]:
    """Map a free-text crop name to a supported calendar key (None if unknown)."""
    n = (name or "").strip().lower()
    if not n:
        return None
    crops = _load().get("crops", {})
    if n in crops:
        return n
    if n in _ALIASES and _ALIASES[n] in crops:
        return _ALIASES[n]
    # substring match: "amar jomite boro dhan" -> boro_rice
    for alias, key in _ALIASES.items():
        if alias in n and key in crops:
            return key
    return None


def get(key: str) -> Optional[dict]:
    """Return a copy of the calendar entry with its key attached (None if absent)."""
    entry = _load().get("crops", {}).get(key)
    if entry is None:
        return None
    out = dict(entry)
    out["_key"] = key
    return out
