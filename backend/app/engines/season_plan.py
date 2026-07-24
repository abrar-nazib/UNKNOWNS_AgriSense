"""Deterministic dated season-plan engine (Tier 0 #4 / Task 6).

Given a bundled BAMIS/FRG crop-calendar entry and an establishment date, produce
a fully dated task schedule. No network, no randomness — the same inputs always
yield the same plan, so it is unit-testable and its output is safe to show in the
Agent Trace and calendar UI.

Live enrichment is layered on by the CALLER and passed in as plain arguments:
- ``sowing_date``       farmer-provided establishment date (overrides the assumption)
- ``duration_override`` CZIS variety duration (overrides the bundled default)
- ``rain_by_date``      {ISO date -> rain_mm} from a real forecast (weather overlay)

Core rule (docs/INSIGHTS.md): the LLM never computes these numbers — this module does.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

HEAVY_RAIN_MM = 10.0   # a stage day at/above this is "too wet" to act on
DRY_RAIN_MM = 5.0      # a candidate replacement day must be below this
SHIFT_SEARCH_DAYS = 5  # how far forward we look for a dry day


def _md(spec: str, year: int) -> date:
    """Parse an ``MM-DD`` window spec into a concrete date for ``year``."""
    month, day = spec.split("-")
    return date(year, int(month), int(day))


def _resolve_offset(offset, duration: int) -> int:
    """Resolve a stage offset. Ints are literal day offsets from establishment.
    ``"duration"`` / ``"duration-N"`` / ``"duration+N"`` resolve against the crop
    duration (harvest, pre-harvest drain, etc.)."""
    if isinstance(offset, (int, float)):
        return int(offset)
    s = str(offset).strip()
    if s == "duration":
        return duration
    if s.startswith("duration"):
        return duration + int(s[len("duration"):])
    return int(s)


def choose_establishment(entry: dict, today: date, *, sowing_date: Optional[date] = None):
    """Return ``(date, source, note)`` for the establishment event.

    Farmer-provided date always wins. Otherwise pick the earliest feasible day
    inside the current or next official window and label it an assumption — the
    plan never silently invents a start date.
    """
    if sowing_date is not None:
        return sowing_date, "farmer_provided", "Using the sowing/transplant date you gave."
    win = entry["window"]
    start = _md(win["start"], today.year)
    end = _md(win["end"], today.year)
    if today <= start:
        return start, "assumed_earliest_in_window", (
            "Assumed the earliest day of this season's official window "
            f"({win['start']}..{win['end']}) — tell me your real date to refine it."
        )
    if start < today <= end:
        return today, "assumed_earliest_in_window", (
            "Assumed today (the official window is already open) — "
            "tell me your real date to refine it."
        )
    nxt = _md(win["start"], today.year + 1)
    return nxt, "assumed_earliest_in_window", (
        "This season's window has closed; assumed the earliest day of NEXT "
        f"season's window ({win['start']}). Tell me your real date to refine it."
    )


def _apply_weather(task: dict, base: date, key: str, rain_by_date: dict) -> None:
    """Mutate ``task`` if heavy rain is forecast on its scheduled day.

    Irrigation is deferred/reduced in place (rain does the watering); fertilizer,
    sowing and planting shift to the next dry day within the search window. The
    original date and reason are always recorded for the trace.
    """
    rain = rain_by_date.get(base.isoformat())
    if rain is None or rain < HEAVY_RAIN_MM:
        return
    if "irrigation" in key or "water" in key:
        task["weather_adjusted"] = True
        task["adjustment_reason"] = (
            f"~{rain:.0f} mm rain forecast that day — skip or reduce irrigation"
        )
        return
    for delta in range(1, SHIFT_SEARCH_DAYS + 1):
        cand = base + timedelta(days=delta)
        cand_rain = rain_by_date.get(cand.isoformat())
        if cand_rain is not None and cand_rain < DRY_RAIN_MM:
            task["original_date"] = base.isoformat()
            task["date"] = cand.isoformat()
            task["weather_adjusted"] = True
            task["adjustment_reason"] = (
                f"moved +{delta}d: ~{rain:.0f} mm rain on the original date"
            )
            return
    task["weather_adjusted"] = True
    task["adjustment_reason"] = (
        f"~{rain:.0f} mm rain forecast — apply on the next dry day"
    )


def build_plan(
    entry: dict,
    *,
    today: date,
    sowing_date: Optional[date] = None,
    duration_override: Optional[int] = None,
    rain_by_date: Optional[dict] = None,
) -> dict:
    """Build the full dated plan for one crop-calendar ``entry``."""
    est, est_source, est_note = choose_establishment(
        entry, today, sowing_date=sowing_date
    )
    duration = int(duration_override or entry.get("default_duration_days") or 0)
    rain_by_date = rain_by_date or {}
    horizon_end = today + timedelta(days=16)

    tasks = []
    for stage in entry["stages"]:
        offset = _resolve_offset(stage["offset_days"], duration)
        base = est + timedelta(days=offset)
        task = {
            "key": stage["key"],
            "label": stage["label"],
            "date": base.isoformat(),
            "original_date": None,
            "weather_sensitive": bool(stage.get("weather_sensitive")),
            "weather_adjusted": False,
            "adjustment_reason": None,
            "note": stage.get("note"),
        }
        if task["weather_sensitive"] and today <= base <= horizon_end:
            _apply_weather(task, base, stage["key"], rain_by_date)
        tasks.append(task)
    tasks.sort(key=lambda t: t["date"])

    win = entry["window"]
    assumptions = [est_note]
    assumptions.append(
        "Weather overlay applied to near-term weather-sensitive tasks."
        if rain_by_date
        else "No live forecast overlay — calendar dates used as-is."
    )
    return {
        "crop": entry.get("display_name"),
        "crop_key": entry.get("_key"),
        "season": entry.get("season"),
        "establishment": {
            "event": entry.get("establishment", "sowing"),
            "date": est.isoformat(),
            "source": est_source,
            "official_window": f"{win['start']}..{win['end']} (MM-DD)",
            "note": est_note,
        },
        "duration_days": duration,
        "duration_source": "czis_variety" if duration_override else "bundled_calendar",
        "tasks": tasks,
        "assumptions": assumptions,
        "disclaimer": (
            "Dates are regional guides from official DAE BAMIS crop-weather "
            "calendars + BARC FRG 2024, anchored to your sowing/transplant date. "
            "Confirm locally; do not treat as exact."
        ),
    }
