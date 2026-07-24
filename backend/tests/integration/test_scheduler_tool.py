"""Integration tests for the fertilizer/irrigation scheduler tool."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agent import tools as tools_mod
from app.agent.tools import _get_or_create_active_farm, build_scheduler_tool
from app.models import User


async def _complete_farm(db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    farm = await _get_or_create_active_farm(db_session, user)
    farm.area_decimal = 50.0
    farm.irrigation_available = True
    farm.water_source = "shallow tubewell"
    farm.budget_bdt = 150_000
    farm.season = "rabi"
    farm.phase = "ready_for_planning"
    await db_session.commit()
    return user, farm


def _weather(days=None):
    return {
        "source": "Open-Meteo forecast API",
        "summary": {"forecast_days": 16},
        "days": days or [{"date": "2026-11-15", "rain_mm": 0}],
    }


def _context(crop_id=3):
    return {
        "crop_id": crop_id,
        "crop_name": "Wheat",
        "varieties": [{"variety_id": 1001, "name": "BARI Gom 33"}],
        "evidence": {"source": "CZIS crop context"},
    }


def _fertilizer():
    return {
        "crop_id": 3,
        "variety_id": 1001,
        "area_decimal": 50.0,
        "products": [
            {"product": "Urea", "element": "N", "amount": {"value": 30, "unit": "kg", "raw": "30 kg"}, "is_alternative": False},
            {"product": "TSP", "element": "P", "amount": {"value": 12, "unit": "kg", "raw": "12 kg"}, "is_alternative": False},
        ],
        "notes": [],
        "evidence": {"source": "CZIS server", "computed_by": "CZIS server"},
    }


def _patch(monkeypatch, weather=None):
    async def fake_weather(lat, lon, days, **kwargs):
        return weather or _weather()

    async def fake_context(crop_id, lat, lon, **kwargs):
        return _context(crop_id)

    async def fake_fertilizer(crop_id, lat, lon, variety_id, area, **kwargs):
        return _fertilizer()

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", fake_weather)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", fake_context)
    monkeypatch.setattr(tools_mod.czis_mod, "get_fertilizer_recommendation", fake_fertilizer)


@pytest.mark.asyncio
async def test_schedule_costs_fertilizer_and_computes_water_balance(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    _patch(monkeypatch)

    payload = json.loads(
        await build_scheduler_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )
    assert payload["status"] == "ok"
    fert = payload["fertilizer_schedule"]
    # Wheat splits urea 2/3 + 1/3 (=30kg) at 27 Tk/kg and applies all 12kg TSP
    # basal at 27 Tk/kg -> 30*27 + 12*27 = 810 + 324 = 1134.
    assert fert["total_chemical_cost_bdt"] == 1134.0
    assert fert["cost_complete"] is True
    totals = {t["product"]: t["kg"] for t in fert["season_product_totals"]}
    assert totals["Urea"] == 30.0
    assert totals["TSP"] == 12.0
    # Organic equivalent for urea is present and flagged approximate.
    urea_org = next(o for o in fert["organic_alternatives"] if o["product"] == "Urea")
    assert urea_org["organic_equivalent"]["status"] == "approximate"

    irr = payload["irrigation_schedule"]
    assert irr["water_balance"]["status"] == "known"
    assert irr["water_balance"]["requirement_mm"] == 428.0
    # 428 - 60 seeded rainfall = 368 -> ceil(368/50) = 8 apps -> 8*20*50 = 8000
    assert irr["recommended_applications"] == 8
    assert irr["estimated_cost_bdt"] == 8000.0


@pytest.mark.asyncio
async def test_rainfall_whatif_changes_irrigation_numbers(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    _patch(monkeypatch)

    drier = json.loads(
        await build_scheduler_tool(user).ainvoke(
            {
                "crop_name": "Wheat",
                "planting_date": "2026-11-15",
                "effective_rainfall_mm": 200,
                "rainfall_change_percent": -30,
            }
        )
    )
    irr = drier["irrigation_schedule"]["water_balance"]
    # 200 * 0.7 = 140 effective; 428 - 140 = 288 -> ceil(288/50) = 6 -> 6000
    assert irr["effective_rainfall_mm"] == 140.0
    assert drier["irrigation_schedule"]["recommended_applications"] == 6
    assert drier["irrigation_schedule"]["estimated_cost_bdt"] == 6000.0


@pytest.mark.asyncio
async def test_scheduler_hard_gates_incomplete_farm(auth_client, db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    payload = json.loads(
        await build_scheduler_tool(user).ainvoke({"crop_name": "Wheat"})
    )
    assert payload["status"] == "PROFILE_INCOMPLETE"
    assert "farm_size" in payload["missing_required_fields"]
