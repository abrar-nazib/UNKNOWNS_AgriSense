"""Gold-number tests for deterministic crop ranking."""

from __future__ import annotations

from datetime import date

import pytest

from app.engines.crop_ranker import estimate_rotation_economics, rank_candidates


def test_rotation_economics_is_internally_consistent_and_area_sensitive():
    one = estimate_rotation_economics(
        gm_tk_per_decimal=500, bcr_vc=2.0, bcr_tc=1.25, area_decimal=10
    )
    two = estimate_rotation_economics(
        gm_tk_per_decimal=500, bcr_vc=2.0, bcr_tc=1.25, area_decimal=20
    )

    assert one == {
        "gross_revenue_tk": 10000,
        "variable_cost_tk": 5000,
        "total_cost_tk": 8000,
        "net_return_tk": 2000,
        "gross_margin_tk": 5000,
    }
    assert two["total_cost_tk"] == 16000
    assert two["net_return_tk"] == 4000
    assert two["gross_revenue_tk"] - two["total_cost_tk"] == two["net_return_tk"]


def _inputs(*, irrigation=True, budget=100_000):
    return {
        "profile": {
            "area_decimal": 50,
            "budget_bdt": budget,
            "irrigation_available": irrigation,
            "season": "rabi",
            "soil_texture": "Clay Loam",
            "excluded_crops": [],
            "preferred_crops": [],
        },
        "catalog": [
            {"crop_id": 3, "name": "Wheat", "season": "Rabi"},
            {"crop_id": 12, "name": "Potato", "season": "Rabi"},
            {"crop_id": 22, "name": "Mustard", "season": "Rabi"},
            {"crop_id": 1, "name": "Boro dhan", "season": "Rabi"},
        ],
        "suitability": [
            {"crop_id": 3, "suite": "Very Suitable", "suite_code": "VS"},
            {"crop_id": 12, "suite": "Very Suitable", "suite_code": "VS"},
            {"crop_id": 22, "suite": "Suitable", "suite_code": "S"},
            {"crop_id": 1, "suite": "Moderately Suitable", "suite_code": "MS"},
        ],
        "patterns": [
            {
                "pattern": "Potato-Mungbean-T. Aman dhan",
                "rabi": "Potato",
                "bcr_vc": "1.5",
                "bcr_tc": "1.2",
                "gm_tk_per_decimal": "500",
            },
            {
                "pattern": "Wheat-Fallow-T. Aman dhan",
                "rabi": "Wheat",
                "bcr_vc": "1.4",
                "bcr_tc": "1.15",
                "gm_tk_per_decimal": "350",
            },
            {
                "pattern": "Mustard-Fallow-T. Aman dhan",
                "rabi": "Mustard",
                "bcr_vc": "1.6",
                "bcr_tc": "1.3",
                "gm_tk_per_decimal": "300",
            },
            {
                "pattern": "Boro dhan-Fallow-Fallow",
                "rabi": "Boro dhan",
                "bcr_vc": "1.3",
                "bcr_tc": "1.1",
                "gm_tk_per_decimal": "150",
            },
        ],
        "weather": {
            "summary": {"total_rain_mm": 8.0, "max_temp_c": 31.0, "min_temp_c": 17.0}
        },
    }


def test_ranker_returns_pdf_required_fields_and_three_candidates():
    ranked = rank_candidates(**_inputs())

    assert len(ranked) >= 3
    assert [c["rank"] for c in ranked] == list(range(1, len(ranked) + 1))
    for crop in ranked:
        assert crop["suitability"]["class"]
        assert crop["water_need"]["level"] in {"low", "medium", "high"}
        assert crop["risk"]["level"] in {"low", "medium", "high"}
        assert isinstance(crop["rough_profit"]["estimate_tk"], int)
        assert crop["rough_profit"]["basis"] == "candidate_crop_projection"
        assert crop["rough_profit"]["estimate_tk"] == round(
            crop["rough_profit"]["gross_revenue_tk"]
            - crop["rough_profit"]["total_cost_tk"]
        )
        assert (
            crop["rough_profit"]["yield_assumption"]["source"]["source_type"]
            == "official_reference_yield_goal"
        )
        assert crop["local_rotation_reference"]["rotation"]
        assert crop["score"] == pytest.approx(sum(crop["score_components"].values()))
        assert crop["water_need"]["source"]["url"].startswith(
            "https://www.bamis.gov.bd/"
        )
        assert crop["budget_fit"]["basis"] == "seeded_demo_crop_cost"
        assert crop["budget_fit"]["warning"].startswith("Not a live quote")

    potato = next(crop for crop in ranked if crop["crop_name"] == "Potato")
    assert potato["budget_fit"]["estimated_crop_cost_tk"] == 77_500
    assert potato["rough_profit"]["total_cost_tk"] == 77_500


def test_ranker_penalizes_high_water_crop_without_irrigation_and_honors_exclusion():
    inputs = _inputs(irrigation=False)
    inputs["profile"]["excluded_crops"] = ["potato"]
    ranked = rank_candidates(**inputs)

    assert "Potato" not in {c["crop_name"] for c in ranked}
    boro = next(c for c in ranked if c["crop_name"] == "Boro dhan")
    mustard = next(c for c in ranked if c["crop_name"] == "Mustard")
    assert boro["risk"]["level"] == "high"
    assert boro["score_components"]["water"] < mustard["score_components"]["water"]


def test_ranker_marks_over_budget_candidate_and_changes_when_budget_changes():
    roomy = rank_candidates(**_inputs(budget=100_000))
    tight = rank_candidates(**_inputs(budget=10_000))

    roomy_potato = next(c for c in roomy if c["crop_name"] == "Potato")
    tight_potato = next(c for c in tight if c["crop_name"] == "Potato")
    assert tight_potato["score"] < roomy_potato["score"]
    assert tight_potato["budget_fit"]["within_budget"] is False
    assert "budget" in " ".join(tight_potato["risk"]["reasons"]).lower()


def test_ranker_treats_missing_weather_as_visible_uncertainty_not_safe_weather():
    inputs = _inputs()
    inputs["weather"] = {"status": "WEATHER_UNAVAILABLE", "summary": {}}
    ranked = rank_candidates(**inputs)

    assert ranked
    assert all(c["score_components"]["weather"] == 5.0 for c in ranked)
    assert all(c["risk"]["level"] != "low" for c in ranked)
    assert all("forecast" in " ".join(c["risk"]["reasons"]).lower() for c in ranked)


def test_ranker_does_not_apply_july_weather_to_future_rabi_sowing_window():
    inputs = _inputs()
    inputs["weather"] = {
        "summary": {"total_rain_mm": 80, "max_temp_c": 42},
        "days": [
            {"date": "2026-07-24", "rain_mm": 40},
            {"date": "2026-07-30", "rain_mm": 40},
        ],
    }
    ranked = rank_candidates(**inputs, today=date(2026, 7, 24))

    assert ranked
    assert all(c["score_components"]["weather"] == 5.0 for c in ranked)
    assert all(
        "does not cover" in " ".join(c["risk"]["reasons"]).lower() for c in ranked
    )
    assert all("42" not in " ".join(c["risk"]["reasons"]) for c in ranked)


def test_ranker_compares_bamis_daily_rain_threshold_to_max_daily_not_weekly_total():
    inputs = _inputs()
    inputs["weather"] = {
        "summary": {"total_rain_mm": 70, "max_temp_c": 25},
        "days": [
            {"date": f"2026-11-{day:02d}", "rain_mm": 10} for day in range(15, 22)
        ],
    }
    ranked = rank_candidates(**inputs, today=date(2026, 11, 15))
    wheat = next(candidate for candidate in ranked if candidate["crop_name"] == "Wheat")
    assert "forecast daily rain" not in " ".join(wheat["risk"]["reasons"]).lower()
    assert wheat["score_components"]["weather"] == 10.0


def test_ranker_never_recommends_crop_that_focused_planner_cannot_plan():
    inputs = _inputs()
    inputs["catalog"].append({"crop_id": 16, "name": "Lentil", "season": "Rabi"})
    inputs["suitability"].append(
        {"crop_id": 16, "suite": "Very Suitable", "suite_code": "VS"}
    )
    inputs["patterns"].append(
        {
            "pattern": "Lentil-Fallow-T. Aman dhan",
            "rabi": "Lentil",
            "bcr_vc": "2.0",
            "bcr_tc": "1.8",
            "gm_tk_per_decimal": "5000",
        }
    )

    ranked = rank_candidates(**inputs)
    assert "Lentil" not in {candidate["crop_name"] for candidate in ranked}


def test_ranker_returns_kharif_finance_backed_crops_as_shortlist_only():
    inputs = _inputs()
    inputs["profile"].update({"season": "kharif-2", "irrigation_available": True})
    inputs["catalog"] = [
        {"crop_id": 91, "name": "Black Gram", "season": "Kharif-2"},
        {"crop_id": 94, "name": "Bottle Gourd", "season": "Kharif-2"},
        {"crop_id": 118, "name": "Brinjal", "season": "Kharif-2"},
    ]
    inputs["suitability"] = [
        {"crop_id": 91, "suite": "Very Suitable", "suite_code": "VS"},
        {"crop_id": 94, "suite": "Suitable", "suite_code": "S"},
        {"crop_id": 118, "suite": "Suitable", "suite_code": "S"},
    ]
    inputs["patterns"] = [
        {
            "pattern": "Black Gram-Boro dhan-T. Aman dhan",
            "kharif2": "Black Gram",
            "bcr_vc": "1.5",
            "bcr_tc": "1.2",
            "gm_tk_per_decimal": "500",
        },
        {
            "pattern": "Bottle Gourd-Boro dhan-T. Aman dhan",
            "kharif2": "Bottle Gourd",
            "bcr_vc": "1.4",
            "bcr_tc": "1.1",
            "gm_tk_per_decimal": "450",
        },
        {
            "pattern": "Brinjal-Boro dhan-T. Aman dhan",
            "kharif2": "Brinjal",
            "bcr_vc": "1.6",
            "bcr_tc": "1.3",
            "gm_tk_per_decimal": "400",
        },
    ]

    ranked = rank_candidates(**inputs)

    assert len(ranked) == 3
    assert all(candidate["plan_capability"] == "shortlist_only" for candidate in ranked)
    assert all(
        candidate["water_need"]["status"] == "NOT_ASSESSED" for candidate in ranked
    )
    assert all(
        candidate["forecast_risk"]["status"] == "NOT_ASSESSED" for candidate in ranked
    )
    assert all(candidate["score_components"]["water"] == 0 for candidate in ranked)
    assert all(candidate["score_components"]["weather"] == 0 for candidate in ranked)


def test_ranker_does_not_apply_rabi_maize_calendar_to_kharif_one_maize():
    inputs = _inputs()
    inputs["profile"]["season"] = "kharif-1"
    inputs["catalog"] = [
        {"crop_id": 62, "name": "Maize", "season": "Kharif-1"},
        {"crop_id": 68, "name": "Brinjal", "season": "Kharif-1"},
        {"crop_id": 74, "name": "Bitter Gourd", "season": "Kharif-1"},
    ]
    inputs["suitability"] = [
        {"crop_id": 62, "suite": "Very Suitable", "suite_code": "VS"},
        {"crop_id": 68, "suite": "Suitable", "suite_code": "S"},
        {"crop_id": 74, "suite": "Suitable", "suite_code": "S"},
    ]
    inputs["patterns"] = [
        {
            "pattern": "Maize-Fallow-T. Aman dhan",
            "kharif1": "Maize",
            "bcr_vc": "1.5",
            "bcr_tc": "1.2",
            "gm_tk_per_decimal": "500",
        },
        {
            "pattern": "Brinjal-Fallow-T. Aman dhan",
            "kharif1": "Brinjal",
            "bcr_vc": "1.4",
            "bcr_tc": "1.1",
            "gm_tk_per_decimal": "450",
        },
        {
            "pattern": "Bitter Gourd-Fallow-T. Aman dhan",
            "kharif1": "Bitter Gourd",
            "bcr_vc": "1.6",
            "bcr_tc": "1.3",
            "gm_tk_per_decimal": "400",
        },
    ]

    maize = next(
        candidate
        for candidate in rank_candidates(**inputs)
        if candidate["crop_name"] == "Maize"
    )

    assert maize["plan_capability"] == "shortlist_only"
    assert maize["water_need"]["status"] == "NOT_ASSESSED"
