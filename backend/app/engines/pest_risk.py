"""Deterministic crop-stage pest and disease risk alerts.

This module deliberately has no network, database, or LLM dependency.  It
evaluates only normalized forecast values against transparent, crop-stage
rules.  It is an early-warning/scouting aid, not a diagnosis or a pesticide
recommendation engine.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .season_planner import CROP_PLANS, canonical_crop_name


RISK_SOURCE = {
    "source": "AgriSense transparent forecast scouting rules",
    "stage_reference": "BAMIS Crop Weather Calendar",
    "scope": "Rajshahi focused crop calendars and stage checkpoints",
    "note": (
        "BAMIS controls crop stage eligibility; weather thresholds are "
        "reviewable AgriSense early-warning triggers. They do not diagnose a "
        "field problem or prescribe a pesticide."
    ),
}


# Each rule intentionally uses only fields the existing daily Open-Meteo
# adapter supplies.  The action is IPM-safe: scout, record, and escalate when
# symptoms are found, rather than naming a pesticide or dose.
RISK_RULES: dict[str, list[dict[str, Any]]] = {
    "wheat": [
        {
            "hazard": "Wheat blast and leaf rust",
            "stages": {"Flowering", "Grain formation"},
            "min_rainy_days": 2,
            "min_temp_c": 15,
            "max_temp_c": 30,
            "level": "high",
            "action": "Inspect leaves and heads for lesions or rust pustules; record affected patches and contact local extension support if symptoms spread.",
        },
        {
            "hazard": "Black point during ripening",
            "stages": {"Grain formation", "Maturity"},
            "min_rain_mm": 10,
            "level": "medium",
            "action": "Inspect maturing heads after wet weather and avoid harvest during rain; seek local advice if grain discoloration appears.",
        },
    ],
    "mustard": [
        {
            "hazard": "Alternaria leaf blight and stem rot",
            "stages": {"Vegetative growth", "Flowering", "Pod initiation"},
            "min_rainy_days": 2,
            "level": "medium",
            "action": "Inspect lower leaves and stems after wet spells; improve field drainage and record any spreading spots or rot.",
        },
        {
            "hazard": "Mustard aphids",
            "stages": {"Flowering", "Pod initiation"},
            "min_rain_prob_days": 2,
            "min_temp_c": 12,
            "max_temp_c": 30,
            "level": "medium",
            "action": "Check flower clusters and the underside of leaves for aphid colonies; preserve beneficial insects and consult extension staff before any treatment.",
        },
    ],
    "potato": [
        {
            "hazard": "Potato late blight",
            "stages": {"Vegetative growth", "Tuber initiation", "Tuber bulking"},
            "min_rainy_days": 2,
            "min_temp_c": 10,
            "max_temp_c": 25,
            "level": "high",
            "action": "Inspect foliage early and often for water-soaked or rapidly expanding lesions; avoid unnecessary leaf wetness and contact extension staff promptly if symptoms appear.",
        },
        {
            "hazard": "Potato wilt and leaf-roll symptoms",
            "stages": {"Tuber initiation", "Tuber bulking"},
            "min_rain_mm": 15,
            "level": "medium",
            "action": "Check plants for wilting, rolling leaves, and uneven patches; improve drainage and seek a field diagnosis before treatment.",
        },
    ],
    "maize": [
        {
            "hazard": "Fall armyworm and seed/stalk rot",
            "stages": {"Vegetative growth", "Tasseling/silking", "Cob formation"},
            "min_rain_mm": 20,
            "level": "medium",
            "action": "Inspect whorls, tassels, and stalks for feeding damage or rot; document the affected area and consult extension staff before selecting control measures.",
        },
    ],
    "boro dhan": [
        {
            "hazard": "Rice blast and sheath blight",
            "stages": {"Tillering", "Panicle initiation", "Heading/flowering"},
            "min_rainy_days": 2,
            "min_temp_c": 18,
            "max_temp_c": 32,
            "level": "high",
            "action": "Inspect leaves, sheaths, and emerging panicles after wet weather; mark affected patches and contact local extension staff if lesions are increasing.",
        },
        {
            "hazard": "Bacterial leaf blight",
            "stages": {"Tillering", "Heading/flowering"},
            "min_rain_mm": 20,
            "level": "medium",
            "action": "Inspect leaves after heavy rain or wind for water-soaked streaks; avoid moving through wet fields unnecessarily and seek local confirmation if symptoms spread.",
        },
    ],
}


def _profile(crop_name: str) -> dict[str, Any]:
    canonical = canonical_crop_name(crop_name)
    return CROP_PLANS[canonical.lower()]


def _stage_for_date(profile: dict[str, Any], planting_date: date, value: date) -> Optional[str]:
    days_after_planting = (value - planting_date).days
    if days_after_planting < 0 or days_after_planting > profile["duration"]:
        return None
    stage = profile["stages"][0][1]
    for offset, label in profile["stages"]:
        if days_after_planting >= offset:
            stage = label
        else:
            break
    return stage


def _numeric(values: list[dict], key: str) -> list[float]:
    result = []
    for value in values:
        try:
            result.append(float(value[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _matches(rule: dict[str, Any], rows: list[dict]) -> bool:
    rain = _numeric(rows, "rain_mm")
    rain_prob = _numeric(rows, "rain_prob_pct")
    mins = _numeric(rows, "t_min_c")
    maxes = _numeric(rows, "t_max_c")
    if rule.get("min_rainy_days") and sum(value >= 1 for value in rain) < rule["min_rainy_days"]:
        return False
    if rule.get("min_rain_prob_days") and sum(value >= 60 for value in rain_prob) < rule["min_rain_prob_days"]:
        return False
    if rule.get("min_rain_mm") and sum(rain) < rule["min_rain_mm"]:
        return False
    if rule.get("min_temp_c") is not None and (not mins or min(mins) < rule["min_temp_c"]):
        return False
    if rule.get("max_temp_c") is not None and (not maxes or max(maxes) > rule["max_temp_c"]):
        return False
    return True


def _weather_facts(rows: list[dict]) -> dict[str, Any]:
    rain = _numeric(rows, "rain_mm")
    mins = _numeric(rows, "t_min_c")
    maxes = _numeric(rows, "t_max_c")
    return {
        "rain_mm_total": round(sum(rain), 1),
        "rainy_day_count": sum(value >= 1 for value in rain),
        "min_temp_c": min(mins) if mins else None,
        "max_temp_c": max(maxes) if maxes else None,
    }


def assess_risk(
    *,
    crop_name: str,
    weather: dict[str, Any],
    as_of: date,
    planting_date: Optional[date] = None,
    growth_stage: str = "",
) -> dict[str, Any]:
    """Return forecast-triggered alerts plus stage-specific scouting watches.

    ``planting_date`` is preferred because it maps every forecast day to a
    crop stage.  A farmer-supplied ``growth_stage`` is supported when a
    planting date is unknown; then the forecast is evaluated against that one
    stage and the response is explicitly labelled as farmer-reported.
    """
    profile = _profile(crop_name)
    canonical = profile["display"]
    requested_stage = (growth_stage or "").strip().casefold()
    stage_names = {label.casefold(): label for _, label in profile["stages"]}
    if requested_stage and requested_stage not in stage_names:
        return {
            "status": "UNKNOWN_GROWTH_STAGE",
            "crop": canonical,
            "valid_growth_stages": list(stage_names.values()),
            "instruction": "Ask for planting date or one of the listed crop stages; do not infer the stage.",
        }

    forecast_rows = [
        row for row in weather.get("days") or []
        if row.get("date") and row.get("kind", "forecast") == "forecast"
    ]
    if not forecast_rows:
        return {
            "status": "WEATHER_UNAVAILABLE",
            "crop": canonical,
            "alerts": [],
            "stage_watches": [],
            "instruction": "Live forecast is unavailable, so no weather-triggered risk was calculated. Continue the calendar scouting checkpoints.",
        }
    if planting_date is None and not requested_stage:
        return {
            "status": "GROWTH_STAGE_REQUIRED",
            "crop": canonical,
            "alerts": [],
            "stage_watches": [],
            "valid_growth_stages": list(stage_names.values()),
            "instruction": "Ask for planting date or current growth stage before calculating a crop-stage risk.",
        }

    dated_rows: list[tuple[dict, str]] = []
    for row in forecast_rows:
        try:
            row_date = date.fromisoformat(str(row["date"]))
        except ValueError:
            continue
        stage = (
            _stage_for_date(profile, planting_date, row_date)
            if planting_date is not None
            else stage_names[requested_stage]
        )
        if stage:
            dated_rows.append((row, stage))

    if not dated_rows:
        return {
            "status": "FORECAST_OUTSIDE_CROP_WINDOW",
            "crop": canonical,
            "alerts": [],
            "stage_watches": [],
            "planting_date": planting_date.isoformat() if planting_date else None,
            "instruction": "The available forecast does not overlap this crop's growing period; recheck within 16 days of the relevant stage.",
        }

    active_stages = sorted({stage for _, stage in dated_rows})
    rows_by_stage = {
        stage: [row for row, candidate in dated_rows if candidate == stage]
        for stage in active_stages
    }
    alerts = []
    watches = []
    for rule in RISK_RULES[canonical.lower()]:
        relevant = [stage for stage in active_stages if stage in rule["stages"]]
        if not relevant:
            continue
        rows = [row for stage in relevant for row in rows_by_stage[stage]]
        watch = {
            "hazard": rule["hazard"],
            "stages": relevant,
            "action": rule["action"],
            "source": RISK_SOURCE,
        }
        watches.append(watch)
        if _matches(rule, rows):
            alerts.append(
                {
                    **watch,
                    "level": rule["level"],
                    "forecast_window": {
                        "from": min(str(row["date"]) for row in rows),
                        "to": max(str(row["date"]) for row in rows),
                    },
                    "matched_weather": _weather_facts(rows),
                    "warning": "This is a weather-triggered scouting alert, not a diagnosis.",
                }
            )

    current_stage = (
        _stage_for_date(profile, planting_date, as_of)
        if planting_date is not None
        else stage_names[requested_stage]
    )
    return {
        "status": "ok",
        "crop": canonical,
        "planting_date": planting_date.isoformat() if planting_date else None,
        "stage_basis": "calendar_from_planting_date" if planting_date else "farmer_reported_growth_stage",
        "current_stage": current_stage,
        "forecast_stages": active_stages,
        "alerts": alerts,
        "stage_watches": watches,
        "safety_note": "Do not select a pesticide or dose from this alert. Inspect the field and use verified local extension guidance for any treatment decision.",
    }
