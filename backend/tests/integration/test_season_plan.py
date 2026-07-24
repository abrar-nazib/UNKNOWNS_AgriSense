"""Integration tests for the selected-crop dated season-plan tool."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agent import tools as tools_mod
from app.agent.tools import _get_or_create_active_farm, build_season_plan_tool
from app.models import User
from app.rag import ingest_document


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
        "fetched_at": "2026-07-24T12:00:00+00:00",
        "summary": {"forecast_days": 16, "total_rain_mm": 5, "max_temp_c": 30},
        "days": days or [],
    }


def _context(crop_id=3):
    return {
        "crop_id": crop_id,
        "crop_name": "Wheat",
        "latitude": 24.62968,
        "longitude": 88.44103,
        "varieties": [
            {"variety_id": 1001, "name": "BARI Gom 33"},
            {"variety_id": 1002, "name": "BARI Gom 32"},
        ],
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


def _varieties(crop_id=3):
    return {
        "crop_id": crop_id,
        "varieties": [
            {
                "name": "BARI Gom 33",
                "yield_t_ha": "4.0-5.0",
                "duration_days": "115-120",
                "characteristics": "reference",
            }
        ],
        "evidence": {"source": "CZIS", "endpoint": f"/varieties/{crop_id}"},
    }


@pytest.mark.asyncio
async def test_season_plan_hard_gates_incomplete_farm(auth_client, db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )
    assert payload["status"] == "PROFILE_INCOMPLETE"
    assert "farm_size" in payload["missing_required_fields"]


@pytest.mark.asyncio
async def test_season_plan_combines_bamis_frg_czis_weather_and_rag(
    auth_client, db_session, monkeypatch
):
    user, farm = await _complete_farm(db_session)
    await ingest_document(
        db_session,
        "<!-- Page 90 (embedded) -->\n\nWheat nitrogen is split between basal application and 17-21 days after sowing.",
        source="FRG 2024",
        crop="wheat",
    )

    async def fake_weather(lat, lon, days, **kwargs):
        assert (lat, lon, days) == (farm.latitude, farm.longitude, 16)
        return _weather([{"date": "2026-11-15", "rain_mm": 0}])

    async def fake_context(crop_id, lat, lon, **kwargs):
        return _context(crop_id)

    async def fake_fertilizer(crop_id, lat, lon, variety_id, area, **kwargs):
        assert (crop_id, variety_id, area) == (3, 1001, 50.0)
        return _fertilizer()

    async def fake_varieties(crop_id, **kwargs):
        return _varieties(crop_id)

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", fake_weather)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", fake_context)
    monkeypatch.setattr(
        tools_mod.czis_mod, "get_fertilizer_recommendation", fake_fertilizer
    )
    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", fake_varieties)

    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )

    assert payload["status"] == "ok"
    assert payload["selected_crop"] == {"crop_id": 3, "name": "Wheat"}
    assert payload["selected_variety"]["variety_id"] == 1001
    assert payload["calendar"]["planting_date"] == "2026-11-15"
    assert payload["calendar"]["harvest_date"] == "2027-03-14"
    assert payload["pest_disease_risk"]["status"] == "ok"
    assert "Sowing" in payload["pest_disease_risk"]["forecast_stages"]
    assert payload["mandatory_follow_up_tool"] == {
        "name": "assess_pest_disease_risk",
        "arguments": {
            "crop_name": "Wheat",
            "planting_date": "2026-11-15",
            "growth_stage": "",
        },
        "reason": (
            "Season plans must run the dedicated pest/disease risk tool for "
            "traceable forecast scouting warnings."
        ),
    }
    categories = {event["category"] for event in payload["calendar"]["events"]}
    assert {"sowing", "fertilizer", "irrigation", "weed", "pest", "harvest"} <= categories
    assert payload["knowledge_evidence"][0]["source"] == "FRG 2024"
    assert payload["knowledge_claims"]["fertilizer_timing"]["status"] == "supported"
    assert payload["fertilizer_recommendation"]["evidence"]["computed_by"] == "CZIS server"
    doses = [
        dose
        for event in payload["calendar"]["events"]
        for dose in event.get("fertilizer_doses", [])
        if dose["product"] == "Urea"
    ]
    assert sum(d["amount"]["value"] for d in doses) == 30
    finance = payload["financial_projection"]
    assert payload["financial_status"] == {"status": "ok"}
    assert finance["expected"]["yield_t_ha"] == 4.5
    assert finance["expected"]["revenue_bdt"] - finance["total_cost_bdt"] == pytest.approx(
        finance["expected"]["net_profit_bdt"], abs=0.01
    )


@pytest.mark.asyncio
async def test_season_plan_weather_delay_changes_all_dependent_dates(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    await ingest_document(db_session, "Wheat season plan reference", source="FRG")

    async def rainy(*args, **kwargs):
        return _weather(
            [
                {"date": "2026-11-15", "rain_mm": 60},
                {"date": "2026-11-16", "rain_mm": 55},
                {"date": "2026-11-17", "rain_mm": 1},
            ]
        )

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", rainy)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", lambda *a, **k: None)

    async def context(*args, **kwargs):
        return _context()

    async def fertilizer(*args, **kwargs):
        return _fertilizer()

    async def varieties(*args, **kwargs):
        return _varieties()

    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", context)
    monkeypatch.setattr(tools_mod.czis_mod, "get_fertilizer_recommendation", fertilizer)
    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", varieties)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )

    assert payload["calendar"]["planting_date"] == "2026-11-17"
    assert payload["calendar"]["harvest_date"] == "2027-03-16"
    assert payload["calendar"]["weather_adjustments"][0]["source"] == "Open-Meteo forecast API"


@pytest.mark.asyncio
async def test_season_plan_marks_future_forecast_outside_horizon_degraded(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    await ingest_document(db_session, "Wheat season plan reference", source="FRG")

    async def short_forecast(*args, **kwargs):
        return _weather([{"date": "2026-07-24", "rain_mm": 0}])

    async def context(*args, **kwargs):
        return _context()

    async def fertilizer(*args, **kwargs):
        return _fertilizer()

    async def varieties(*args, **kwargs):
        return _varieties()

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", short_forecast)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", context)
    monkeypatch.setattr(tools_mod.czis_mod, "get_fertilizer_recommendation", fertilizer)
    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", varieties)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )
    assert payload["status"] == "degraded"
    assert "weather_forecast_pending" in payload["unavailable_sources"]


@pytest.mark.asyncio
async def test_season_plan_fertilizer_outage_is_degraded_without_invented_doses(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    await ingest_document(db_session, "Wheat season plan reference", source="FRG")

    async def context(*args, **kwargs):
        return _context()

    async def no_fertilizer(*args, **kwargs):
        raise tools_mod.czis_mod.CzisError("offline")

    async def weather(*args, **kwargs):
        return _weather()

    async def varieties(*args, **kwargs):
        return _varieties()

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", weather)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", context)
    monkeypatch.setattr(
        tools_mod.czis_mod, "get_fertilizer_recommendation", no_fertilizer
    )
    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", varieties)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )

    assert payload["status"] == "degraded"
    assert "fertilizer" in payload["unavailable_sources"]
    assert all(
        event.get("fertilizer_doses") == []
        for event in payload["calendar"]["events"]
        if event["category"] == "fertilizer"
    )
    assert payload["financial_status"] == {"status": "ok"}


@pytest.mark.asyncio
async def test_season_plan_yield_outage_keeps_calendar_but_never_invents_finance(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    await ingest_document(db_session, "Wheat season plan reference", source="FRG")

    async def weather(*args, **kwargs):
        return _weather()

    async def context(*args, **kwargs):
        return _context()

    async def fertilizer(*args, **kwargs):
        return _fertilizer()

    async def no_yield(*args, **kwargs):
        raise tools_mod.czis_mod.CzisError("yield table offline")

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", weather)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", context)
    monkeypatch.setattr(tools_mod.czis_mod, "get_fertilizer_recommendation", fertilizer)
    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", no_yield)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2026-11-15"}
        )
    )

    assert payload["status"] == "degraded"
    assert payload["calendar"]["harvest_date"] == "2027-03-14"
    assert payload["financial_projection"] is None
    assert payload["financial_status"]["status"] == "YIELD_UNAVAILABLE"
    assert "financial_yield" in payload["unavailable_sources"]


@pytest.mark.asyncio
async def test_season_plan_rejects_unknown_crop_before_network(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)

    async def forbidden(*args, **kwargs):
        pytest.fail("network must not run for unsupported crop")

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", forbidden)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke({"crop_name": "Dragon fruit"})
    )
    assert payload["status"] == "UNSUPPORTED_CROP"


@pytest.mark.asyncio
async def test_season_plan_rejects_past_planting_date_before_network(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)

    async def forbidden(*args, **kwargs):
        pytest.fail("network must not run for an already-past planting date")

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", forbidden)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "planting_date": "2000-11-15"}
        )
    )
    assert payload["status"] == "PAST_PLANTING_DATE"


@pytest.mark.asyncio
async def test_season_plan_rejects_non_rajshahi_calendar_before_network(
    auth_client, db_session, monkeypatch
):
    user, farm = await _complete_farm(db_session)
    farm.division_name = "Dhaka"
    await db_session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("Rajshahi calendar must not be applied outside its region")

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", forbidden)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke({"crop_name": "Wheat"})
    )
    assert payload["status"] == "UNSUPPORTED_CALENDAR_REGION"
    assert payload["calendar_region"] == "Rajshahi"


@pytest.mark.asyncio
async def test_season_plan_rejects_high_water_crop_without_irrigation_before_network(
    auth_client, db_session, monkeypatch
):
    user, farm = await _complete_farm(db_session)
    farm.irrigation_available = False
    farm.water_source = "rainfed"
    await db_session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("infeasible Boro plan must stop before external calls")

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", forbidden)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke({"crop_name": "Boro dhan"})
    )
    assert payload["status"] == "IRRIGATION_REQUIRED"
    assert payload["crop"] == "Boro dhan"


@pytest.mark.asyncio
async def test_season_plan_rejects_variety_not_returned_for_farm_point(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)

    async def weather(*args, **kwargs):
        return _weather()

    async def context(*args, **kwargs):
        return _context()

    monkeypatch.setattr(tools_mod.weather_mod, "fetch_forecast", weather)
    monkeypatch.setattr(tools_mod.czis_mod, "get_crop_context", context)
    payload = json.loads(
        await build_season_plan_tool(user).ainvoke(
            {"crop_name": "Wheat", "variety_id": 9999}
        )
    )
    assert payload["status"] == "INVALID_VARIETY"
    assert payload["available_varieties"] == _context()["varieties"]
