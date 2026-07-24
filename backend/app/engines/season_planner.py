"""Deterministic, source-cited crop calendar generation.

This module intentionally contains no HTTP, database, or LLM calls.  Its five
focused Rabi profiles are structured from the Rajshahi-region BAMIS crop-weather
calendars and the BARC Fertilizer Recommendation Guide 2024.  External adapters
provide weather and farm-scaled fertilizer products before calling this engine.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional


def _bamis(url: str) -> dict:
    return {
        "source": "BAMIS Crop Weather Calendar",
        "region": "Rajshahi",
        "url": url,
    }


def _frg(pages: str) -> dict:
    return {
        "source": "BARC Fertilizer Recommendation Guide 2024",
        "pages": pages,
    }


# Offsets are days after planting/transplanting. Sowing-window dates are a
# deterministic interpretation of the first BAMIS standard weeks, and are
# explicitly labelled that way in output rather than presented as a live notice.
CROP_PLANS: dict[str, dict[str, Any]] = {
    "wheat": {
        "display": "Wheat",
        "aliases": {"wheat"},
        "duration": 119,
        "window": ((11, 15), (12, 15)),
        "bamis": _bamis(
            "https://www.bamis.gov.bd/res/public/calendars/2019/08/23/5116.pdf"
        ),
        "frg": _frg("90-91"),
        "water_requirement": {"phase_mm": [47, 128, 77, 137, 39], "total_mm": 428},
        "weather_warning": {"rain_mm_day": 50, "max_temp_c": 30, "min_temp_c": 15},
        "stages": [
            (0, "Sowing"),
            (7, "Germination"),
            (21, "Vegetative growth"),
            (55, "Flowering"),
            (75, "Grain formation"),
            (105, "Maturity"),
        ],
        "fertilizer": [
            (
                0,
                "Apply basal fertilizer during final land preparation",
                {"urea": 2 / 3},
            ),
            (
                19,
                "Apply remaining nitrogen after first irrigation (FRG window: 17-21 DAS)",
                {"urea": 1 / 3},
            ),
        ],
        "irrigation": [
            (19, "First irrigation at crown-root/early vegetative stage"),
            (55, "Irrigate at flowering if soil moisture is low"),
            (78, "Irrigate during grain formation if needed"),
        ],
        "weeds": [
            (20, "Inspect and control weeds after crop establishment"),
            (40, "Second weed inspection before flowering"),
        ],
        "pests": [
            (52, "Scout for blast, leaf rust and loose smut around flowering"),
            (88, "Check black point risk; rain during ripening raises risk"),
        ],
    },
    "mustard": {
        "display": "Mustard",
        "aliases": {"mustard", "sarisha", "সরিষা"},
        "duration": 90,
        "window": ((11, 15), (11, 30)),
        "bamis": _bamis(
            "https://www.bamis.gov.bd/res/public/calendars/2019/12/30/10986.pdf"
        ),
        "frg": _frg("101-102"),
        "water_requirement": {
            "phase_mm": None,
            "total_mm": None,
            "note": "BAMIS calendar does not publish a phase-wise total for mustard.",
        },
        "weather_warning": {"rain_mm_day": 50, "max_temp_c": 30, "min_temp_c": 10},
        "stages": [
            (0, "Sowing"),
            (7, "Germination"),
            (18, "Vegetative growth"),
            (30, "Flowering"),
            (50, "Pod initiation"),
            (78, "Maturity"),
        ],
        "fertilizer": [
            (
                0,
                "Apply half nitrogen and all other prescribed fertilizers as basal",
                {"urea": 0.5},
            ),
            (25, "Topdress remaining nitrogen at flower initiation", {"urea": 0.5}),
        ],
        "rainfed_fertilizer": [
            (
                0,
                "Under the FRG rainfed rule, apply all prescribed fertilizers as basal during final land preparation",
                {},
            )
        ],
        "irrigation": [
            (1, "Light irrigation only if seedbed moisture is inadequate"),
            (25, "Irrigate at flower initiation when soil is dry"),
            (50, "Check moisture at pod initiation; avoid waterlogging"),
        ],
        "weeds": [
            (18, "Inspect and control weeds before flower initiation"),
            (35, "Second weed inspection after flowering starts"),
        ],
        "pests": [
            (28, "Scout for Alternaria leaf blight and stem rot"),
            (42, "Scout for aphids, especially in cloudy weather"),
        ],
    },
    "potato": {
        "display": "Potato",
        "aliases": {"potato", "alu", "আলু"},
        "duration": 105,
        "window": ((10, 20), (11, 20)),
        "bamis": _bamis(
            "https://www.bamis.gov.bd/res/public/calendars/2019/11/14/8864.pdf"
        ),
        "frg": _frg("106-107"),
        "water_requirement": {"seasonal_range_mm": [400, 600]},
        "weather_warning": {"rain_mm_day": 25, "max_temp_c": 30, "min_temp_c": 10},
        "stages": [
            (0, "Planting"),
            (10, "Sprouting/seedling"),
            (24, "Vegetative growth"),
            (38, "Tuber initiation"),
            (62, "Tuber bulking"),
            (92, "Maturity"),
        ],
        "fertilizer": [
            (
                0,
                "Apply basal fertilizers during final land preparation",
                {"urea": 0.5, "mop": 0.5},
            ),
            (
                33,
                "Side-dress remaining nitrogen and potassium during earthing-up (FRG window: 30-35 DAP)",
                {"urea": 0.5, "mop": 0.5},
            ),
        ],
        "irrigation": [
            (12, "Light irrigation for crop establishment if soil is dry"),
            (35, "Irrigate at tuber initiation; do not waterlog"),
            (62, "Maintain moisture during tuber bulking"),
        ],
        "weeds": [
            (20, "First weed control before canopy closes"),
            (33, "Weed and earth up with the side-dressing operation"),
        ],
        "pests": [
            (32, "Scout for late blight; cold, humid, foggy weather increases risk"),
            (58, "Scout for bacterial/fusarium wilt and potato leaf-roll symptoms"),
        ],
    },
    "maize": {
        "display": "Maize",
        "aliases": {"maize", "corn", "ভুট্টা"},
        "duration": 112,
        "window": ((11, 10), (11, 30)),
        "bamis": _bamis(
            "https://www.bamis.gov.bd/res/public/calendars/2019/08/23/5125.pdf"
        ),
        "frg": _frg("91"),
        "water_requirement": {"phase_mm": [76, 120, 190, 145, 100], "total_mm": 631},
        "weather_warning": {"rain_mm_day": 50, "min_temp_c": 10},
        "stages": [
            (0, "Sowing"),
            (7, "Germination"),
            (20, "Vegetative growth"),
            (55, "Tasseling/silking"),
            (72, "Cob formation"),
            (100, "Maturity"),
        ],
        "fertilizer": [
            (
                0,
                "Apply one-third nitrogen and all other prescribed fertilizers in sowing furrows",
                {"urea": 1 / 3},
            ),
            (
                52,
                "Side-dress one-third nitrogen (FRG window: 50-55 DAS)",
                {"urea": 1 / 3},
            ),
            (
                82,
                "Side-dress final one-third nitrogen at tasseling (FRG window: 80-85 DAS)",
                {"urea": 1 / 3},
            ),
        ],
        "irrigation": [
            (20, "Irrigate during vegetative growth if rainfall is inadequate"),
            (55, "Irrigate at tasseling/silking; this is a critical stage"),
            (75, "Maintain moisture during cob formation"),
        ],
        "weeds": [
            (18, "First weed control around early vegetative growth"),
            (38, "Second weed inspection before tasseling"),
        ],
        "pests": [
            (18, "Scout whorls for fall armyworm damage"),
            (48, "Repeat fall-armyworm and seed/stalk-rot scouting before tasseling"),
        ],
    },
    "boro dhan": {
        "display": "Boro dhan",
        "aliases": {"boro", "boro rice", "rice boro", "boro dhan", "বোরো", "বোরো ধান"},
        "duration": 153,
        "window": ((12, 1), (1, 15)),
        "bamis": _bamis(
            "https://www.bamis.gov.bd/res/public/calendars/2019/08/23/5105.pdf"
        ),
        "frg": _frg("87-88"),
        "water_requirement": {"phase_mm": [76, 120, 190, 145, 100], "total_mm": 631},
        "weather_warning": {"rain_mm_day": 50, "min_temp_c": 10},
        "stages": [
            (0, "Seedbed/transplanting"),
            (15, "Seedling establishment"),
            (30, "Tillering"),
            (55, "Panicle initiation"),
            (80, "Heading/flowering"),
            (105, "Grain filling"),
            (140, "Maturity"),
        ],
        "fertilizer": [
            (
                0,
                "Apply first nitrogen split and basal P, K, S and Zn at final land preparation/establishment",
                {"urea": 1 / 3},
            ),
            (30, "Apply second nitrogen split at early tillering", {"urea": 1 / 3}),
            (
                49,
                "Apply final nitrogen split 5-7 days before panicle initiation",
                {"urea": 1 / 3},
            ),
        ],
        "irrigation": [
            (5, "Maintain shallow water for establishment"),
            (
                30,
                "Manage water at tillering; avoid unnecessary continuous deep flooding",
            ),
            (55, "Ensure water at panicle initiation"),
            (82, "Ensure water through flowering"),
            (125, "Reduce irrigation as crop approaches maturity"),
        ],
        "weeds": [
            (20, "First weed inspection before active tillering"),
            (42, "Second weed inspection before panicle initiation"),
        ],
        "pests": [
            (48, "Scout for bacterial leaf blight, sheath blight and blast"),
            (78, "Repeat blast and sheath-blight scouting around heading"),
        ],
    },
}


def _profile(crop_name: str) -> dict[str, Any]:
    key = (crop_name or "").strip().lower()
    for profile_key, profile in CROP_PLANS.items():
        if key == profile_key or key in profile["aliases"]:
            return profile
    raise ValueError(
        "supported crop required: Wheat, Mustard, Potato, Maize or Boro dhan"
    )


def canonical_crop_name(crop_name: str) -> str:
    """Return the canonical supported crop name or raise ``ValueError``."""
    return str(_profile(crop_name)["display"])


def supports_dated_calendar(crop_name: str, season: str) -> bool:
    """Whether this exact crop-season has a sourced deterministic calendar.

    The profiles in this module are Rajshahi Rabi calendars.  A crop name can
    occur in another CZIS season (for example Kharif-1 maize), but that does
    not make the Rabi dates safe to reuse there.
    """
    if str(season or "").strip().casefold() != "rabi":
        return False
    try:
        _profile(crop_name)
    except ValueError:
        return False
    return True


def next_sowing_date(crop_name: str, today: date) -> date:
    """Next date inside the BAMIS-derived sowing window."""
    profile = _profile(crop_name)
    (start_month, start_day), (end_month, end_day) = profile["window"]
    windows = []
    for year in (today.year - 1, today.year, today.year + 1, today.year + 2):
        start = date(year, start_month, start_day)
        end_year = year + 1 if end_month < start_month else year
        end = date(end_year, end_month, end_day)
        windows.append((start, end))
        if start <= today <= end:
            return today
    future_starts = [start for start, _end in windows if start > today]
    if future_starts:
        return min(future_starts)
    raise RuntimeError("could not determine next sowing window")


def _inside_window(profile: dict, value: date) -> bool:
    (sm, sd), (em, ed) = profile["window"]
    for start_year in (value.year - 1, value.year):
        start = date(start_year, sm, sd)
        end = date(start_year + (1 if em < sm else 0), em, ed)
        if start <= value <= end:
            return True
    return False


def _weather_adjusted_date(
    requested: date, weather: dict, rain_threshold_mm: float
) -> tuple[date, list[dict], list[str]]:
    rows = {
        str(row.get("date")): row
        for row in weather.get("days") or []
        if row.get("date")
    }
    current = rows.get(requested.isoformat())
    if current is None:
        if rows:
            coverage = f"{min(rows)} through {max(rows)}"
        else:
            coverage = "no daily dates"
        return (
            requested,
            [],
            [
                f"The live forecast ({coverage}) does not cover planting date "
                f"{requested.isoformat()}; no weather date adjustment was made. "
                "Recheck within 16 days of planting."
            ],
        )
    rain = current.get("rain_mm") if current else None
    if rain is None or float(rain) < float(rain_threshold_mm):
        return requested, [], []
    candidates = sorted(
        (
            date.fromisoformat(day),
            row,
        )
        for day, row in rows.items()
        if day > requested.isoformat()
    )
    for candidate, row in candidates:
        candidate_rain = row.get("rain_mm")
        if candidate_rain is not None and float(candidate_rain) < float(
            rain_threshold_mm
        ):
            return (
                candidate,
                [
                    {
                        "type": "planting_delay",
                        "from": requested.isoformat(),
                        "to": candidate.isoformat(),
                        "reason": f"{float(rain):.1f} mm rain forecast on requested planting date",
                        "source": weather.get("source") or "live weather result",
                    }
                ],
                [],
            )
    return (
        requested,
        [],
        [
            "Heavy rain is forecast on the planting date and no dry day appears in "
            "the available forecast; confirm a new date when the forecast updates."
        ],
    )


def _split_fertilizers(
    events: list[tuple], products: list[dict]
) -> dict[int, list[dict]]:
    doses: dict[int, list[dict]] = {offset: [] for offset, _, _ in events}
    for product in products:
        if product.get("is_alternative"):
            continue
        amount = product.get("amount") or {}
        try:
            total = float(amount["value"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(product.get("product") or "").strip()
        normalized = name.lower().replace(" ", "")
        matching: list[tuple[int, float]] = []
        for offset, _action, shares in events:
            for split_name, share in shares.items():
                if split_name.replace(" ", "") == normalized:
                    matching.append((offset, float(share)))
                    break
        if not matching:
            matching = [(events[0][0], 1.0)]
        allocated = 0.0
        for index, (offset, share) in enumerate(matching):
            value = (
                round(total - allocated, 3)
                if index == len(matching) - 1
                else round(total * share, 3)
            )
            allocated = round(allocated + value, 3)
            doses[offset].append(
                {
                    "product": name,
                    "element": product.get("element"),
                    "amount": {
                        "value": value,
                        "unit": amount.get("unit"),
                    },
                    "source": "CZIS farm-scaled fertilizer recommendation",
                }
            )
    return doses


def build_season_calendar(
    *,
    crop_name: str,
    today: date,
    fertilizer_products: list[dict],
    weather: dict,
    planting_date: Optional[date] = None,
    irrigation_available: Optional[bool] = None,
    soil_texture: str = "",
    land_type: str = "",
) -> dict:
    """Build the complete dated Tier-0 calendar for one supported crop."""
    profile = _profile(crop_name)
    requested = planting_date or next_sowing_date(profile["display"], today)
    actual, weather_adjustments, weather_warnings = _weather_adjusted_date(
        requested, weather, profile["weather_warning"]["rain_mm_day"]
    )
    warnings = list(weather_warnings)
    if not _inside_window(profile, actual):
        warnings.append(
            f"Selected planting date {actual.isoformat()} is outside the "
            "BAMIS-calendar-derived sowing window; confirm with local extension staff."
        )

    fertilizer_events = (
        profile.get("rainfed_fertilizer", profile["fertilizer"])
        if irrigation_available is False
        else profile["fertilizer"]
    )
    fertilizer_doses = _split_fertilizers(fertilizer_events, fertilizer_products)
    events: list[dict] = []

    def add(offset: int, category: str, title: str, action: str, source: dict, **extra):
        events.append(
            {
                "date": (actual + timedelta(days=offset)).isoformat(),
                "days_after_planting": offset,
                "category": category,
                "title": title,
                "action": action,
                "source": source,
                **extra,
            }
        )

    add(
        -10,
        "land_preparation",
        "Land preparation",
        "Prepare the field and drainage; incorporate prescribed organic and basal inputs as directed.",
        profile["frg"],
    )
    add(
        0,
        "sowing",
        profile["stages"][0][1],
        f"Plant {profile['display']} in the prepared field.",
        profile["bamis"],
    )
    for offset, stage in profile["stages"][1:]:
        add(
            offset,
            "crop_stage",
            stage,
            f"Confirm the crop has reached {stage.lower()} and update the plan if development differs.",
            profile["bamis"],
        )
    for offset, action, _shares in fertilizer_events:
        add(
            offset,
            "fertilizer",
            "Fertilizer application",
            action,
            profile["frg"],
            fertilizer_doses=fertilizer_doses.get(offset, []),
        )
    for offset, action in profile["irrigation"]:
        if irrigation_available is False:
            add(
                offset,
                "moisture_monitoring",
                "Rainfed moisture checkpoint",
                "No assured irrigation: monitor soil moisture and rainfall; "
                "this plan does not assume water can be applied at this stage.",
                profile["bamis"],
                original_irrigated_guidance=action,
            )
        else:
            add(offset, "irrigation", "Irrigation checkpoint", action, profile["bamis"])
    for offset, action in profile["weeds"]:
        add(offset, "weed", "Weed checkpoint", action, profile["bamis"])
    for offset, action in profile["pests"]:
        add(offset, "pest", "Pest and disease checkpoint", action, profile["bamis"])
    add(
        profile["duration"],
        "harvest",
        "Harvest",
        "Harvest when crop-specific maturity indicators are confirmed; avoid harvesting during rain.",
        profile["bamis"],
    )

    events.sort(key=lambda event: (event["date"], event["category"], event["title"]))
    return {
        "crop_name": profile["display"],
        "planting_date": actual.isoformat(),
        "requested_planting_date": requested.isoformat(),
        "harvest_date": (actual + timedelta(days=profile["duration"])).isoformat(),
        "duration_days": profile["duration"],
        "sowing_window_basis": "derived from first/last standard weeks in the Rajshahi BAMIS calendar",
        "weather_adjustments": weather_adjustments,
        "warnings": warnings,
        "events": events,
        "sources": {
            "crop_calendar": profile["bamis"],
            "fertilizer_timing": profile["frg"],
        },
        "agronomic_reference": {
            "water_requirement": profile["water_requirement"],
            "weather_warning_thresholds": profile["weather_warning"],
            "source": profile["bamis"],
        },
        "farm_context": {
            "irrigation_available": irrigation_available,
            "soil_texture": soil_texture or None,
            "land_type": land_type or None,
            "usage": (
                "Irrigation availability controls whether the calendar emits "
                "irrigation instructions or rainfed moisture checks. Soil and "
                "land type are retained for extension review; this Rajshahi "
                "calendar does not invent uncited timing adjustments from them."
            ),
        },
    }
