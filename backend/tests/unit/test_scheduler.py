"""Gold-number tests for the deterministic fertilizer/irrigation scheduler."""
from __future__ import annotations

import pytest

from app.engines import scheduler


def _fert_events():
    return [
        {
            "date": "2026-11-15",
            "days_after_planting": 0,
            "title": "Fertilizer application",
            "action": "Apply basal fertilizer",
            "fertilizer_doses": [
                {"product": "Urea", "element": "N", "amount": {"value": 20, "unit": "kg"}},
                {"product": "TSP", "element": "P", "amount": {"value": 15, "unit": "kg"}},
            ],
        },
        {
            "date": "2026-12-04",
            "days_after_planting": 19,
            "title": "Fertilizer application",
            "action": "Top-dress remaining nitrogen",
            "fertilizer_doses": [
                {"product": "Urea", "element": "N", "amount": {"value": 10, "unit": "kg"}},
            ],
        },
    ]


def test_price_lookup_is_case_insensitive_and_none_for_unknown():
    assert scheduler.price_for("Urea") == 27.0
    assert scheduler.price_for("mop") == 20.0
    assert scheduler.price_for("unobtainium") is None


def test_fertilizer_schedule_costs_each_stage_and_season_total():
    sched = scheduler.build_fertilizer_schedule(fertilizer_events=_fert_events())

    # Stage 1: Urea 20*27 + TSP 15*27 = 540 + 405 = 945
    assert sched["stages"][0]["stage_cost_bdt"] == 945.0
    # Stage 2: Urea 10*27 = 270
    assert sched["stages"][1]["stage_cost_bdt"] == 270.0
    assert sched["total_chemical_cost_bdt"] == 1215.0
    assert sched["cost_complete"] is True

    totals = {t["product"]: t["kg"] for t in sched["season_product_totals"]}
    assert totals == {"Urea": 30.0, "TSP": 15.0}


def test_organic_equivalent_uses_transparent_nutrient_math():
    # Urea season total 30 kg -> 30*0.46 = 13.8 kg N.
    org = scheduler.organic_alternatives("Urea", "N", 30.0)
    assert org["status"] == "approximate"
    assert org["element"] == "N"
    assert org["nutrient_kg"] == 13.8
    by_name = {o["name"]: o["approx_kg"] for o in org["options"]}
    # 13.8 / 0.05 = 276 kg mustard oil cake; 13.8 / 0.005 = 2760 kg FYM.
    assert by_name["Mustard oil cake"] == 276.0
    assert by_name["Well-rotted cowdung (FYM)"] == 2760.0


def test_organic_equivalent_unavailable_for_unpriced_carrier():
    org = scheduler.organic_alternatives("MysteryMix", "N", 10.0)
    assert org["status"] == "unavailable"
    assert org["options"] == []


def test_sandy_soil_emits_retention_note():
    sched = scheduler.build_fertilizer_schedule(
        fertilizer_events=_fert_events(), soil_texture="sandy loam"
    )
    assert "leach" in (sched["soil_note"] or "").lower()


def test_unpriced_product_marks_cost_incomplete():
    events = [
        {
            "date": "2026-11-15",
            "days_after_planting": 0,
            "title": "Fertilizer application",
            "action": "basal",
            "fertilizer_doses": [
                {"product": "Borax", "element": "B", "amount": {"value": 1, "unit": "kg"}},
            ],
        }
    ]
    sched = scheduler.build_fertilizer_schedule(fertilizer_events=events)
    assert sched["cost_complete"] is False
    assert sched["stages"][0]["products"][0]["cost_source"] == "unavailable"


# --------------------------------------------------------------------------- #
# Irrigation water balance
# --------------------------------------------------------------------------- #
def _irrig_events():
    return [
        {"date": "2026-12-04", "days_after_planting": 19, "action": "First irrigation"},
        {"date": "2027-01-09", "days_after_planting": 55, "action": "Flowering irrigation"},
    ]


def test_wheat_water_balance_with_seeded_default_rainfall():
    result = scheduler.build_irrigation_schedule(
        crop_name="Wheat", irrigation_events=_irrig_events(), area_decimal=50.0
    )
    wb = result["water_balance"]
    assert wb["status"] == "known"
    assert wb["requirement_mm"] == 428.0
    assert wb["effective_rainfall_mm"] == 60.0
    # 428 - 60 = 368 mm -> ceil(368/50) = 8 applications; 8*20*50 = 8000
    assert wb["net_irrigation_mm"] == 368.0
    assert result["recommended_applications"] == 8
    assert result["estimated_cost_bdt"] == 8000.0
    assert result["checkpoint_count"] == 2


def test_rainfall_drop_increases_applications_and_cost():
    base = scheduler.build_irrigation_schedule(
        crop_name="Wheat",
        irrigation_events=_irrig_events(),
        area_decimal=50.0,
        effective_rainfall_mm=200.0,
    )
    # 428 - 200 = 228 -> ceil(228/50) = 5 apps -> 5*20*50 = 5000
    assert base["recommended_applications"] == 5
    assert base["estimated_cost_bdt"] == 5000.0

    drier = scheduler.build_irrigation_schedule(
        crop_name="Wheat",
        irrigation_events=_irrig_events(),
        area_decimal=50.0,
        effective_rainfall_mm=200.0,
        rainfall_change_percent=-30,
    )
    # rainfall 200*0.7 = 140; 428 - 140 = 288 -> ceil(288/50) = 6 -> 6000
    assert drier["water_balance"]["effective_rainfall_mm"] == 140.0
    assert drier["recommended_applications"] == 6
    assert drier["estimated_cost_bdt"] == 6000.0


def test_crop_without_published_water_requirement_invents_nothing():
    result = scheduler.build_irrigation_schedule(
        crop_name="Mustard", irrigation_events=_irrig_events(), area_decimal=50.0
    )
    assert result["water_balance"]["status"] == "unknown"
    assert "recommended_applications" not in result
    assert result["checkpoint_count"] == 2
