"""Deterministic crop ranking for the PDF Tier-0 recommendation contract.

The engine contains no network or LLM calls.  It combines already-retrieved
official suitability, live weather, farm constraints and recorded local
rotation economics into inspectable scores.  The LLM may explain this output;
it must not replace the arithmetic.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .finance import (
    seeded_crop_cost,
    seeded_crop_rough_projection,
    supported_finance_crops,
)
from .season_planner import CROP_PLANS, next_sowing_date, supports_dated_calendar


def _bamis_source(url: str) -> dict[str, str]:
    return {"source": "BAMIS Crop Weather Calendar", "region": "Rajshahi", "url": url}


# Qualitative water demand and conservative weather limits for the focused
# Bangladesh Rabi path.  These are agronomic profile metadata, not irrigation
# quantities.  Farmer-facing quantities are produced only by later scheduler
# tools.  Source references are carried into every candidate.
CROP_TRAITS: dict[str, dict[str, Any]] = {
    "boro dhan": {
        "water": "high",
        "max_temp_c": 35,
        "heavy_rain_mm": 50,
        "profile": "boro dhan",
    },
    "wheat": {
        "water": "medium",
        "max_temp_c": 30,
        "heavy_rain_mm": 50,
        "profile": "wheat",
    },
    "maize": {
        "water": "high",
        "max_temp_c": 35,
        "heavy_rain_mm": 50,
        "profile": "maize",
    },
    "mustard": {
        "water": "low",
        "max_temp_c": 30,
        "heavy_rain_mm": 50,
        "profile": "mustard",
    },
    "potato": {
        "water": "medium",
        "max_temp_c": 30,
        "heavy_rain_mm": 25,
        "profile": "potato",
    },
    "lentil": {
        "water": "low",
        "max_temp_c": 32,
        "heavy_rain_mm": 35,
        "source": _bamis_source(
            "https://www.bamis.gov.bd/res/public/calendars/2019/11/14/8725.pdf"
        ),
    },
    "tomato": {
        "water": "medium",
        "max_temp_c": 32,
        "heavy_rain_mm": 35,
        "source": _bamis_source(
            "https://www.bamis.gov.bd/res/public/calendars/2023/03/16/26464.pdf"
        ),
    },
    "onion": {
        "water": "medium",
        "max_temp_c": 32,
        "heavy_rain_mm": 35,
        "source": _bamis_source(
            "https://www.bamis.gov.bd/res/public/calendars/2023/03/16/26482.pdf"
        ),
    },
    "garlic": {
        "water": "medium",
        "max_temp_c": 32,
        "heavy_rain_mm": 35,
        "source": _bamis_source(
            "https://www.bamis.gov.bd/res/public/calendars/2023/03/17/26526.pdf"
        ),
    },
    "brinjal": {
        "water": "medium",
        "max_temp_c": 35,
        "heavy_rain_mm": 40,
        "source": _bamis_source(
            "https://www.bamis.gov.bd/res/public/calendars/2023/04/17/27419.pdf"
        ),
    },
}

for _trait in CROP_TRAITS.values():
    if profile_key := _trait.get("profile"):
        _trait["source"] = CROP_PLANS[profile_key]["bamis"]
        _trait["water_requirement"] = CROP_PLANS[profile_key]["water_requirement"]

TRAITS_SOURCE = {
    "source": "BARC Fertilizer Recommendation Guide 2024 + BAMIS crop calendars",
    "usage": "qualitative water-demand and weather-risk classification",
    "note": "No irrigation quantity is inferred from these qualitative classes.",
}

_SUITABILITY_POINTS = {
    "VS": 100.0,
    "S": 80.0,
    "MS": 60.0,
    "MNS": 35.0,
    "NS": 0.0,
    "N": 0.0,
    "UNKNOWN": 40.0,
}

_SEASON_FIELD = {"rabi": "rabi", "kharif-1": "kharif1", "kharif-2": "kharif2"}


def recommendation_capability(crop_name: str, season: str) -> Optional[str]:
    """Return the safe action depth for a crop-season pair.

    Kharif crops can be short-listed from their own CZIS catalog/suitability,
    local rotation context and disclosed finance assumptions.  They must not
    inherit a Rabi calendar, water requirement or forecast threshold until an
    exact crop-season source has been added.
    """
    if supports_dated_calendar(crop_name, season):
        return "dated_plan"
    key = str(crop_name or "").strip().casefold()
    if season in {"kharif-1", "kharif-2"} and key in set(supported_finance_crops()):
        return "shortlist_only"
    return None


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_tk(value: float) -> int:
    return int(round(value))


def estimate_rotation_economics(
    *,
    gm_tk_per_decimal: float,
    bcr_vc: float,
    bcr_tc: float,
    area_decimal: float,
) -> dict[str, int]:
    """Reconstruct inspectable rotation economics from CZIS reference fields.

    CZIS defines gross margin = gross revenue - variable cost, BCR(VC) = gross
    revenue / variable cost, and BCR(TC) = gross revenue / total cost.  Those
    identities uniquely determine all five returned values when BCR(VC) > 1.
    """
    gm = float(gm_tk_per_decimal)
    vc_ratio = float(bcr_vc)
    tc_ratio = float(bcr_tc)
    area = float(area_decimal)
    if gm < 0 or area <= 0 or vc_ratio <= 1.0 or tc_ratio <= 0:
        raise ValueError("invalid CZIS economics inputs")
    revenue_per_decimal = gm * vc_ratio / (vc_ratio - 1.0)
    variable_cost_per_decimal = revenue_per_decimal / vc_ratio
    total_cost_per_decimal = revenue_per_decimal / tc_ratio
    gross_revenue = _round_tk(revenue_per_decimal * area)
    total_cost = _round_tk(total_cost_per_decimal * area)
    return {
        "gross_revenue_tk": gross_revenue,
        "variable_cost_tk": _round_tk(variable_cost_per_decimal * area),
        "total_cost_tk": total_cost,
        # Derive displayed net from displayed rounded operands so the identity
        # is exactly reproducible down to one Taka.
        "net_return_tk": gross_revenue - total_cost,
        "gross_margin_tk": _round_tk(gm * area),
    }


def _best_pattern_by_crop(patterns: list[dict], season: str) -> dict[str, dict]:
    field = _SEASON_FIELD.get(season, "rabi")
    out: dict[str, dict] = {}
    for row in patterns:
        crop = str(row.get(field) or "").strip()
        if not crop or crop.lower() == "fallow":
            continue
        key = crop.lower()
        gm = _number(row.get("gm_tk_per_decimal"))
        previous = _number(out.get(key, {}).get("gm_tk_per_decimal"))
        if gm is not None and (previous is None or gm > previous):
            out[key] = row
    return out


def _weather_component(
    traits: dict,
    weather: dict,
    *,
    crop_name: str,
    today: Optional[date],
) -> tuple[float, list[str]]:
    if today is not None and traits.get("profile"):
        forecast_dates = []
        for row in weather.get("days") or []:
            try:
                forecast_dates.append(date.fromisoformat(str(row.get("date"))))
            except (TypeError, ValueError):
                continue
        if forecast_dates:
            sowing = next_sowing_date(crop_name, today)
            forecast_start, forecast_end = min(forecast_dates), max(forecast_dates)
            if not forecast_start <= sowing <= forecast_end:
                return 5.0, [
                    f"live forecast through {forecast_end.isoformat()} does not "
                    f"cover the next sowing window from {sowing.isoformat()}; "
                    "recheck weather closer to planting"
                ]
    summary = weather.get("summary") or {}
    warnings: list[str] = []
    max_temp = _number(summary.get("max_temp_c"))
    daily_rain = [
        value
        for row in weather.get("days") or []
        if (value := _number(row.get("rain_mm"))) is not None
    ]
    max_daily_rain = (
        max(daily_rain) if daily_rain else _number(summary.get("max_daily_rain_mm"))
    )
    if max_temp is None and max_daily_rain is None:
        # Unknown is neither safe nor catastrophic: keep a neutral half-score
        # and make the uncertainty visible in the candidate risk reasons.
        return 5.0, ["live forecast values unavailable"]
    score = 10.0
    if max_temp is not None and max_temp > traits["max_temp_c"]:
        warnings.append(
            f"forecast maximum {max_temp:g}°C exceeds {traits['max_temp_c']}°C risk threshold"
        )
        score -= 5.0
    if max_daily_rain is not None and max_daily_rain > traits["heavy_rain_mm"]:
        warnings.append(
            f"forecast daily rain {max_daily_rain:g} mm exceeds "
            f"{traits['heavy_rain_mm']} mm/day risk threshold"
        )
        score -= 5.0
    return max(score, 0.0), warnings


def rank_candidates(
    *,
    profile: dict,
    catalog: list[dict],
    suitability: list[dict],
    patterns: list[dict],
    weather: dict,
    limit: int = 5,
    today: Optional[date] = None,
) -> list[dict]:
    """Rank eligible crops and return the PDF-required candidate fields."""
    season = str(profile.get("season") or "").strip().lower()
    area = _number(profile.get("area_decimal")) or 0.0
    budget = _number(profile.get("budget_bdt")) or 0.0
    irrigation = profile.get("irrigation_available") is True
    excluded = {str(c).strip().lower() for c in profile.get("excluded_crops") or []}
    preferred = {str(c).strip().lower() for c in profile.get("preferred_crops") or []}

    suite_by_id = {int(row["crop_id"]): row for row in suitability}
    pattern_by_crop = _best_pattern_by_crop(patterns, season)
    ranked: list[dict] = []

    ordered_catalog = sorted(
        catalog,
        key=lambda item: (
            str(item.get("variety_group") or "").lower() != "favourable environment",
            int(item.get("crop_id") or 0),
        ),
    )
    seen_names: set[str] = set()
    for item in ordered_catalog:
        name = str(item.get("name") or "").strip()
        key = name.lower()
        if not name or key in excluded:
            continue
        if str(item.get("season") or "").strip().lower() != season:
            continue
        plan_capability = recommendation_capability(name, season)
        if plan_capability is None:
            continue
        pattern = pattern_by_crop.get(key)
        if not pattern or key in seen_names:
            continue  # no defensible local profit number for this candidate
        seen_names.add(key)
        try:
            economics = estimate_rotation_economics(
                gm_tk_per_decimal=float(pattern["gm_tk_per_decimal"]),
                bcr_vc=float(pattern["bcr_vc"]),
                bcr_tc=float(pattern["bcr_tc"]),
                area_decimal=area,
            )
        except (KeyError, TypeError, ValueError):
            continue

        suite = suite_by_id.get(int(item["crop_id"]), {})
        suite_code = str(suite.get("suite_code") or "UNKNOWN").upper()
        suitability_score = _SUITABILITY_POINTS.get(suite_code, 40.0)
        suitability_component = round(suitability_score * 0.5, 2)

        traits = CROP_TRAITS.get(key)
        water_level = (
            traits.get("water") if traits and plan_capability == "dated_plan" else None
        )
        if water_level is None:
            water_component = 0.0
            weather_component = 0.0
            weather_warnings = [
                "crop-season water need and forecast risk are not assessed; "
                "confirm Kharif extension guidance before planting"
            ]
        else:
            water_raw = (
                {"low": 100.0, "medium": 90.0, "high": 75.0}[water_level]
                if irrigation
                else {"low": 100.0, "medium": 50.0, "high": 0.0}[water_level]
            )
            water_component = round(water_raw * 0.2, 2)
            weather_component, weather_warnings = _weather_component(
                traits, weather, crop_name=name, today=today
            )

        crop_cost = seeded_crop_cost(name, area)
        crop_projection = seeded_crop_rough_projection(name, area)
        required = int(round(crop_cost["total_cost_bdt"]))
        fit_ratio = min(1.0, budget / required) if required > 0 else 0.0
        budget_component = round(fit_ratio * 20.0, 2)

        reasons: list[str] = []
        high_risk = False
        medium_risk = False
        if suite_code in {"NS", "N"}:
            reasons.append("CZIS marks the field not suitable")
            high_risk = True
        elif suite_code in {"MS", "MNS", "UNKNOWN"}:
            reasons.append(f"CZIS suitability is {suite.get('suite') or 'unknown'}")
            medium_risk = True
        if water_level == "high" and not irrigation:
            reasons.append("high water need but irrigation is unavailable")
            high_risk = True
        elif water_level == "medium" and not irrigation:
            reasons.append("medium water need with no assured irrigation")
            medium_risk = True
        if required > budget:
            reasons.append(
                f"seeded demo crop cost {required} Tk exceeds budget {int(budget)} Tk"
            )
            high_risk = high_risk or fit_ratio < 0.5
            medium_risk = True
        if economics["net_return_tk"] < 0:
            reasons.append(
                "recorded rotation has a negative net return over total cost"
            )
            high_risk = True
        if weather_warnings:
            reasons.extend(weather_warnings)
            medium_risk = True
        if not reasons:
            reasons.append(
                "no major constraint conflict detected from retrieved inputs"
            )

        risk_level = "high" if high_risk else "medium" if medium_risk else "low"
        components = {
            "land_suitability": suitability_component,
            "water": water_component,
            "budget": budget_component,
            "weather": round(weather_component, 2),
        }
        score = round(sum(components.values()), 2)
        ranked.append(
            {
                "crop_id": int(item["crop_id"]),
                "crop_name": name,
                "score": score,
                "score_components": components,
                "suitability": {
                    "class": suite.get("suite") or "Unknown",
                    "code": suite_code,
                    "score_0_100": suitability_score,
                    "source": "BARC CZIS GeoServer point layer",
                },
                "water_need": {
                    "level": water_level,
                    "status": "ASSESSED" if water_level else "NOT_ASSESSED",
                    "irrigation_available": irrigation,
                    "published_requirement": (
                        traits.get("water_requirement")
                        if traits and water_level
                        else None
                    ),
                    "source": (
                        traits.get("source", TRAITS_SOURCE)
                        if traits and water_level
                        else None
                    ),
                },
                "forecast_risk": {
                    "status": "ASSESSED" if water_level else "NOT_ASSESSED",
                    "reason": (
                        None
                        if water_level
                        else "No exact crop-season calendar or weather threshold is bundled."
                    ),
                },
                "plan_capability": plan_capability,
                "risk": {"level": risk_level, "reasons": reasons},
                "budget_fit": {
                    "farmer_budget_tk": int(budget),
                    "estimated_crop_cost_tk": required,
                    "within_budget": required <= budget,
                    "basis": "seeded_demo_crop_cost",
                    "source_type": crop_cost["source_type"],
                    "catalog_version": crop_cost["catalog_version"],
                    "warning": crop_cost["warning"],
                },
                "rough_profit": {
                    "estimate_tk": int(
                        round(crop_projection["expected"]["net_profit_bdt"])
                    ),
                    "basis": "candidate_crop_projection",
                    "warning": (
                        "Yield, price and costs are seeded demo values—not live "
                        "quotes or a guaranteed return. Confirm them locally."
                        if crop_projection["yield_assumption"]["source"].get(
                            "source_type"
                        )
                        == "seeded_demo_value"
                        else "Yield is an official reference goal, but price and costs are seeded demo values—not live quotes or a guaranteed return. Confirm them locally."
                    ),
                    "expected_yield_kg": crop_projection["expected"]["yield_kg"],
                    "gross_revenue_tk": crop_projection["expected"]["revenue_bdt"],
                    "total_cost_tk": crop_projection["total_cost_bdt"],
                    "yield_assumption": crop_projection["yield_assumption"],
                    "price_assumption": crop_projection["price_assumption"],
                    "catalog_version": crop_projection["assumptions"][
                        "catalog_version"
                    ],
                },
                "local_rotation_reference": {
                    "warning": (
                        "CZIS records economics for this full annual rotation, "
                        "not for the candidate crop alone."
                    ),
                    "rotation": pattern.get("pattern"),
                    "net_return_tk": economics["net_return_tk"],
                    "gross_margin_tk": economics["gross_margin_tk"],
                    "gross_revenue_tk": economics["gross_revenue_tk"],
                    "total_cost_tk": economics["total_cost_tk"],
                    "bcr_vc": float(pattern["bcr_vc"]),
                    "bcr_tc": float(pattern["bcr_tc"]),
                },
                "preferred_by_farmer": key in preferred,
            }
        )

    ranked.sort(
        key=lambda crop: (
            crop["score"],
            crop["preferred_by_farmer"],
            crop["rough_profit"]["estimate_tk"],
        ),
        reverse=True,
    )
    for index, crop in enumerate(ranked[: max(3, min(int(limit), 5))], 1):
        crop["rank"] = index
    return ranked[: max(3, min(int(limit), 5))]
