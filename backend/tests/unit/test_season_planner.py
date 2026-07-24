"""Gold-date and quantity invariants for deterministic season calendars."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.engines.season_planner import (
    build_season_calendar,
    next_sowing_date,
    supports_dated_calendar,
)


def test_next_sowing_date_uses_next_official_window_not_stale_model_year():
    assert next_sowing_date("Wheat", date(2026, 7, 24)) == date(2026, 11, 15)
    assert next_sowing_date("Wheat", date(2026, 11, 20)) == date(2026, 11, 20)
    assert next_sowing_date("Wheat", date(2026, 12, 20)) == date(2027, 11, 15)


def test_next_sowing_date_handles_boro_window_across_new_year():
    assert next_sowing_date("Boro dhan", date(2026, 1, 10)) == date(2026, 1, 10)
    assert next_sowing_date("Boro dhan", date(2026, 2, 1)) == date(2026, 12, 1)


@pytest.mark.parametrize(
    "crop,expected_duration",
    [
        ("Wheat", 119),
        ("Mustard", 90),
        ("Potato", 105),
        ("Maize", 112),
        ("Boro dhan", 153),
    ],
)
def test_calendar_covers_every_pdf_required_stage(crop, expected_duration):
    plan = build_season_calendar(
        crop_name=crop,
        today=date(2026, 7, 24),
        fertilizer_products=[],
        weather={"days": []},
    )

    categories = {event["category"] for event in plan["events"]}
    assert {
        "land_preparation",
        "sowing",
        "fertilizer",
        "irrigation",
        "weed",
        "pest",
        "harvest",
    } <= categories
    assert plan["duration_days"] == expected_duration
    assert (
        plan["harvest_date"]
        == (
            date.fromisoformat(plan["planting_date"])
            + timedelta(days=expected_duration)
        ).isoformat()
    )
    assert [e["date"] for e in plan["events"]] == sorted(
        e["date"] for e in plan["events"]
    )
    assert all(event["source"] for event in plan["events"])


def test_wheat_calendar_exposes_bamis_phase_water_values_and_source():
    plan = build_season_calendar(
        crop_name="Wheat",
        today=date(2026, 7, 24),
        fertilizer_products=[],
        weather={"days": []},
    )
    water = plan["agronomic_reference"]["water_requirement"]
    assert water["phase_mm"] == [47, 128, 77, 137, 39]
    assert water["total_mm"] == 428
    assert plan["sources"]["crop_calendar"]["url"].endswith("/5116.pdf")


def test_fertilizer_splits_preserve_exact_czis_total_amounts():
    plan = build_season_calendar(
        crop_name="Wheat",
        today=date(2026, 7, 24),
        planting_date=date(2026, 11, 20),
        fertilizer_products=[
            {
                "product": "Urea",
                "element": "N",
                "amount": {"value": 30.0, "unit": "kg", "raw": "30 kg"},
                "is_alternative": False,
            },
            {
                "product": "TSP",
                "element": "P",
                "amount": {"value": 12.5, "unit": "kg", "raw": "12.5 kg"},
                "is_alternative": False,
            },
        ],
        weather={"days": []},
    )

    applications = [
        dose
        for event in plan["events"]
        if event["category"] == "fertilizer"
        for dose in event.get("fertilizer_doses", [])
    ]
    urea = [d for d in applications if d["product"] == "Urea"]
    tsp = [d for d in applications if d["product"] == "TSP"]
    assert sum(d["amount"]["value"] for d in urea) == pytest.approx(30.0)
    assert sorted(d["amount"]["value"] for d in urea) == [10.0, 20.0]
    assert sum(d["amount"]["value"] for d in tsp) == pytest.approx(12.5)
    assert len(tsp) == 1  # non-N fertilizer is basal for wheat


def test_heavy_rain_delays_near_term_planting_to_first_dry_forecast_day():
    weather = {
        "source": "Open-Meteo forecast API",
        "days": [
            {"date": "2026-11-15", "rain_mm": 60.0},
            {"date": "2026-11-16", "rain_mm": 55.0},
            {"date": "2026-11-17", "rain_mm": 2.0},
        ],
    }
    plan = build_season_calendar(
        crop_name="Wheat",
        today=date(2026, 11, 15),
        planting_date=date(2026, 11, 15),
        fertilizer_products=[],
        weather=weather,
    )

    assert plan["planting_date"] == "2026-11-17"
    assert plan["weather_adjustments"] == [
        {
            "type": "planting_delay",
            "from": "2026-11-15",
            "to": "2026-11-17",
            "reason": "60.0 mm rain forecast on requested planting date",
            "source": "Open-Meteo forecast API",
        }
    ]


def test_rain_delay_uses_crop_specific_published_bamis_threshold():
    weather = {
        "source": "Open-Meteo forecast API",
        "days": [
            {"date": "2026-11-15", "rain_mm": 30.0},
            {"date": "2026-11-16", "rain_mm": 1.0},
        ],
    }
    wheat = build_season_calendar(
        crop_name="Wheat",
        today=date(2026, 11, 15),
        planting_date=date(2026, 11, 15),
        fertilizer_products=[],
        weather=weather,
    )
    potato = build_season_calendar(
        crop_name="Potato",
        today=date(2026, 11, 15),
        planting_date=date(2026, 11, 15),
        fertilizer_products=[],
        weather=weather,
    )
    assert wheat["planting_date"] == "2026-11-15"  # BAMIS warning is 50 mm/day
    assert potato["planting_date"] == "2026-11-16"  # BAMIS warning is 25 mm/day


def test_plan_warns_when_planting_date_is_outside_live_forecast_horizon():
    plan = build_season_calendar(
        crop_name="Wheat",
        today=date(2026, 7, 24),
        planting_date=date(2026, 11, 15),
        fertilizer_products=[],
        weather={
            "source": "Open-Meteo forecast API",
            "days": [{"date": "2026-07-24", "rain_mm": 1.0}],
        },
    )
    assert any("does not cover" in warning.lower() for warning in plan["warnings"])
    assert any("16 days" in warning for warning in plan["warnings"])


def test_outside_sowing_window_is_visible_when_farmer_forces_date():
    plan = build_season_calendar(
        crop_name="Mustard",
        today=date(2026, 7, 24),
        planting_date=date(2026, 8, 1),
        fertilizer_products=[],
        weather={"days": []},
    )
    assert plan["warnings"]
    assert any("outside" in warning.lower() for warning in plan["warnings"])


def test_rainfed_mustard_uses_frg_all_basal_rule_and_no_irrigation_schedule():
    plan = build_season_calendar(
        crop_name="Mustard",
        today=date(2026, 11, 15),
        planting_date=date(2026, 11, 15),
        fertilizer_products=[
            {
                "product": "Urea",
                "element": "N",
                "amount": {"value": 20.0, "unit": "kg"},
                "is_alternative": False,
            }
        ],
        weather={"days": []},
        irrigation_available=False,
        soil_texture="Clay Loam",
        land_type="medium highland",
    )

    fertilizer_events = [
        event for event in plan["events"] if event["category"] == "fertilizer"
    ]
    assert len(fertilizer_events) == 1
    assert "rainfed" in fertilizer_events[0]["action"].lower()
    assert fertilizer_events[0]["fertilizer_doses"][0]["amount"]["value"] == 20
    assert not any(event["category"] == "irrigation" for event in plan["events"])
    assert any(event["category"] == "moisture_monitoring" for event in plan["events"])
    assert plan["farm_context"]["irrigation_available"] is False


def test_unsupported_crop_is_rejected_instead_of_inventing_calendar():
    with pytest.raises(ValueError, match="supported crop"):
        build_season_calendar(
            crop_name="Dragon fruit",
            today=date(2026, 7, 24),
            fertilizer_products=[],
            weather={"days": []},
        )


def test_dated_calendar_support_is_explicitly_crop_and_season_bound():
    assert supports_dated_calendar("Maize", "rabi") is True
    assert supports_dated_calendar("Maize", "kharif-1") is False
    assert supports_dated_calendar("Brinjal", "kharif-2") is False
