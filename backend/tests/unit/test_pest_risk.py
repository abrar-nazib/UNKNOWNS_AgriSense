"""Unit tests for deterministic forecast-driven pest and disease risk."""
from __future__ import annotations

from datetime import date

import pytest

from app.engines.pest_risk import assess_risk

pytestmark = pytest.mark.unit


def _weather(days):
    return {"source": "Open-Meteo forecast API", "days": days}


def test_potato_late_blight_alert_requires_matching_stage_and_wet_cool_weather():
    result = assess_risk(
        crop_name="Potato",
        planting_date=date(2026, 11, 1),
        as_of=date(2026, 11, 25),
        weather=_weather(
            [
                {"date": "2026-11-25", "rain_mm": 4, "rain_prob_pct": 80, "t_min_c": 14, "t_max_c": 22},
                {"date": "2026-11-26", "rain_mm": 6, "rain_prob_pct": 75, "t_min_c": 15, "t_max_c": 23},
            ]
        ),
    )

    assert result["status"] == "ok"
    assert result["current_stage"] == "Vegetative growth"
    alert = next(item for item in result["alerts"] if item["hazard"] == "Potato late blight")
    assert alert["level"] == "high"
    assert alert["forecast_window"] == {"from": "2026-11-25", "to": "2026-11-26"}
    assert "not a diagnosis" in alert["warning"]


def test_risk_does_not_trigger_when_forecast_is_outside_the_crop_stage():
    result = assess_risk(
        crop_name="Potato",
        planting_date=date(2026, 11, 1),
        as_of=date(2026, 11, 5),
        weather=_weather(
            [
                {"date": "2026-11-05", "rain_mm": 20, "rain_prob_pct": 90, "t_min_c": 14, "t_max_c": 20},
                {"date": "2026-11-06", "rain_mm": 20, "rain_prob_pct": 90, "t_min_c": 14, "t_max_c": 20},
            ]
        ),
    )

    assert result["status"] == "ok"
    assert result["current_stage"] == "Planting"
    assert result["alerts"] == []
    assert result["stage_watches"] == []


def test_farmer_reported_stage_produces_a_stage_watch_without_inventing_date():
    result = assess_risk(
        crop_name="Boro dhan",
        growth_stage="Heading/flowering",
        as_of=date(2026, 2, 10),
        weather=_weather(
            [
                {"date": "2026-02-10", "rain_mm": 0, "rain_prob_pct": 5, "t_min_c": 19, "t_max_c": 28},
            ]
        ),
    )

    assert result["status"] == "ok"
    assert result["planting_date"] is None
    assert result["stage_basis"] == "farmer_reported_growth_stage"
    assert any(item["hazard"] == "Rice blast and sheath blight" for item in result["stage_watches"])


def test_missing_stage_is_an_explicit_follow_up_not_a_guessed_risk():
    result = assess_risk(
        crop_name="Wheat",
        as_of=date(2026, 1, 10),
        weather=_weather([{"date": "2026-01-10", "rain_mm": 0, "t_min_c": 12, "t_max_c": 22}]),
    )

    assert result["status"] == "GROWTH_STAGE_REQUIRED"
    assert result["alerts"] == []


def test_weather_outage_is_honest_and_never_creates_an_alert():
    result = assess_risk(
        crop_name="Mustard",
        growth_stage="Flowering",
        as_of=date(2026, 1, 10),
        weather={"status": "WEATHER_UNAVAILABLE", "days": []},
    )

    assert result["status"] == "WEATHER_UNAVAILABLE"
    assert result["alerts"] == []
