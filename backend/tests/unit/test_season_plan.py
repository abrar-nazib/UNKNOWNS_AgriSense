"""Gold-number tests for the deterministic season-plan engine (Task 6).

Pure/offline: no DB, no network — the engine turns a bundled BAMIS/FRG calendar
entry + an establishment date into a fixed dated schedule.
"""
from __future__ import annotations

from datetime import date

import pytest

from app import crop_calendar
from app.engines import season_plan

pytestmark = pytest.mark.unit


def _task(plan: dict, key: str) -> dict:
    return next(t for t in plan["tasks"] if t["key"] == key)


# --------------------------------------------------------------------------- #
# Calendar loader
# --------------------------------------------------------------------------- #
def test_supported_crops_and_aliases():
    assert crop_calendar.list_crops() == [
        "boro_rice",
        "maize",
        "mustard",
        "potato",
        "wheat",
    ]
    assert crop_calendar.resolve_key("Sarisha") == "mustard"
    assert crop_calendar.resolve_key("gom") == "wheat"
    assert crop_calendar.resolve_key("amar jomite boro dhan") == "boro_rice"
    assert crop_calendar.resolve_key("dragonfruit") is None
    assert crop_calendar.get("wheat")["_key"] == "wheat"


# --------------------------------------------------------------------------- #
# Establishment date selection
# --------------------------------------------------------------------------- #
def test_establishment_assumed_before_window():
    plan = season_plan.build_plan(crop_calendar.get("wheat"), today=date(2026, 7, 24))
    assert plan["establishment"]["date"] == "2026-11-15"  # window start this year
    assert plan["establishment"]["source"] == "assumed_earliest_in_window"


def test_establishment_assumed_inside_open_window():
    plan = season_plan.build_plan(crop_calendar.get("wheat"), today=date(2026, 11, 20))
    assert plan["establishment"]["date"] == "2026-11-20"  # today (window open)
    assert plan["establishment"]["source"] == "assumed_earliest_in_window"


def test_establishment_assumed_after_window_rolls_to_next_year():
    plan = season_plan.build_plan(crop_calendar.get("wheat"), today=date(2026, 12, 20))
    assert plan["establishment"]["date"] == "2027-11-15"  # next season's window


def test_establishment_farmer_date_wins():
    plan = season_plan.build_plan(
        crop_calendar.get("mustard"),
        today=date(2026, 7, 24),
        sowing_date=date(2026, 10, 20),
    )
    assert plan["establishment"]["date"] == "2026-10-20"
    assert plan["establishment"]["source"] == "farmer_provided"


# --------------------------------------------------------------------------- #
# Stage-date arithmetic (offsets + "duration" resolution)
# --------------------------------------------------------------------------- #
def test_harvest_is_establishment_plus_duration():
    est = date(2026, 10, 20)
    plan = season_plan.build_plan(
        crop_calendar.get("mustard"), today=date(2026, 7, 24), sowing_date=est
    )
    assert plan["duration_days"] == 90
    assert _task(plan, "harvest")["date"] == "2027-01-18"  # 2026-10-20 + 90d


def test_negative_and_relative_offsets():
    est = date(2027, 1, 10)
    plan = season_plan.build_plan(
        crop_calendar.get("boro_rice"), today=date(2026, 7, 24), sowing_date=est
    )
    assert _task(plan, "seedbed_sowing")["date"] == "2026-12-06"  # est - 35d
    assert _task(plan, "drain_field")["date"] == "2027-05-30"  # est + (150-10)
    assert _task(plan, "harvest")["date"] == "2027-06-09"  # est + 150d
    # tasks are chronologically sorted
    dates = [t["date"] for t in plan["tasks"]]
    assert dates == sorted(dates)


def test_potato_pre_harvest_offset():
    est = date(2026, 11, 5)
    plan = season_plan.build_plan(
        crop_calendar.get("potato"), today=date(2026, 7, 24), sowing_date=est
    )
    assert plan["duration_days"] == 100
    assert _task(plan, "haulm_cut")["date"] == "2027-02-01"  # est + (100-12) = +88d
    assert _task(plan, "harvest")["date"] == "2027-02-13"  # est + 100d


def test_duration_override_from_czis():
    est = date(2026, 11, 5)
    plan = season_plan.build_plan(
        crop_calendar.get("potato"),
        today=date(2026, 7, 24),
        sowing_date=est,
        duration_override=110,
    )
    assert plan["duration_days"] == 110
    assert plan["duration_source"] == "czis_variety"
    assert _task(plan, "harvest")["date"] == "2027-02-23"  # est + 110d


# --------------------------------------------------------------------------- #
# Weather overlay (only near-term weather-sensitive tasks)
# --------------------------------------------------------------------------- #
def test_fertilizer_shifts_to_next_dry_day():
    rain = {"2026-10-03": 25.0, "2026-10-04": 20.0, "2026-10-05": 2.0}
    plan = season_plan.build_plan(
        crop_calendar.get("mustard"),
        today=date(2026, 10, 1),
        sowing_date=date(2026, 10, 3),
        rain_by_date=rain,
    )
    basal = _task(plan, "fertilizer_basal")
    assert basal["date"] == "2026-10-05"
    assert basal["original_date"] == "2026-10-03"
    assert basal["weather_adjusted"] is True


def test_irrigation_deferred_in_place_on_heavy_rain():
    rain = {"2026-10-15": 30.0}
    plan = season_plan.build_plan(
        crop_calendar.get("mustard"),
        today=date(2026, 10, 1),
        sowing_date=date(2026, 9, 20),  # irrigation_1 at +25 = 2026-10-15
        rain_by_date=rain,
    )
    irr = _task(plan, "irrigation_1")
    assert irr["date"] == "2026-10-15"  # not moved — rain does the watering
    assert irr["original_date"] is None
    assert irr["weather_adjusted"] is True
    assert "skip" in irr["adjustment_reason"].lower()


def test_task_beyond_forecast_horizon_not_adjusted():
    rain = {"2026-10-26": 50.0}  # irrigation_1 falls at est+25, > today+16
    plan = season_plan.build_plan(
        crop_calendar.get("mustard"),
        today=date(2026, 10, 1),
        sowing_date=date(2026, 10, 1),
        rain_by_date=rain,
    )
    assert _task(plan, "irrigation_1")["weather_adjusted"] is False


# --------------------------------------------------------------------------- #
# Determinism + provenance
# --------------------------------------------------------------------------- #
def test_plan_is_deterministic():
    kwargs = dict(today=date(2026, 7, 24), sowing_date=date(2026, 11, 15))
    a = season_plan.build_plan(crop_calendar.get("wheat"), **kwargs)
    b = season_plan.build_plan(crop_calendar.get("wheat"), **kwargs)
    assert a == b


def test_plan_carries_sources_and_disclaimer():
    plan = season_plan.build_plan(crop_calendar.get("wheat"), today=date(2026, 7, 24))
    assert plan["duration_source"] == "bundled_calendar"
    assert plan["disclaimer"]
    assert plan["assumptions"]
