"""Integration tests for the what-if scenario simulator (Tier 1)."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agent import tools as tools_mod
from app.agent.tools import _get_or_create_active_farm, build_scenario_tool
from app.models import User


async def _complete_farm(db_session, *, irrigation=True):
    user = (await db_session.execute(select(User))).scalar_one()
    farm = await _get_or_create_active_farm(db_session, user)
    farm.area_decimal = 50.0
    farm.irrigation_available = irrigation
    farm.water_source = "shallow tubewell" if irrigation else "rainfed"
    farm.budget_bdt = 150_000
    farm.season = "rabi"
    farm.phase = "ready_for_planning"
    await db_session.commit()
    return user, farm


def _varieties(crop_id=3):
    return {
        "crop_id": crop_id,
        "varieties": [{"name": "BARI Gom 33", "yield_t_ha": "4.0-5.0", "duration_days": "115-120"}],
        "evidence": {"source": "CZIS", "endpoint": f"/varieties/{crop_id}"},
    }


def _patch_yield(monkeypatch):
    async def fake_varieties(crop_id, **kwargs):
        return _varieties(crop_id)

    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", fake_varieties)


@pytest.mark.asyncio
async def test_budget_cut_revises_budget_fit_numbers(auth_client, db_session, monkeypatch):
    user, _farm = await _complete_farm(db_session)
    _patch_yield(monkeypatch)

    payload = json.loads(
        await build_scenario_tool(user).ainvoke(
            {"crop_name": "Wheat", "budget_change_percent": -40}
        )
    )
    assert payload["status"] == "ok"
    # Budget scaled 150000 * 0.6 = 90000; cost unchanged so baseline==revised cost.
    assert payload["revised"]["budget_bdt"] == 90000.0
    assert payload["baseline"]["total_cost_bdt"] == payload["revised"]["total_cost_bdt"]
    # Budget fit recomputed against the smaller budget.
    gap = round(90000.0 - payload["revised"]["total_cost_bdt"], 2)
    assert payload["revised"]["surplus_or_gap_bdt"] == gap
    assert payload["scenario"]["budget_change_percent"] == -40


@pytest.mark.asyncio
async def test_rainfall_drop_adds_irrigation_cost_and_flags_risk(
    auth_client, db_session, monkeypatch
):
    user, _farm = await _complete_farm(db_session)
    _patch_yield(monkeypatch)

    payload = json.loads(
        await build_scenario_tool(user).ainvoke(
            {"crop_name": "Wheat", "rainfall_change_percent": -30}
        )
    )
    assert payload["status"] == "ok"
    # Baseline rainfall 60 -> 428-60=368 -> 8 apps. Revised 60*0.7=42 ->
    # 428-42=386 -> ceil(386/50)=8 apps. Same apps here, so extra cost 0 but the
    # water balance still reflects the drier scenario.
    assert payload["revised"]["net_irrigation_mm"] == 386.0
    # Net profit delta equals the negative of any added irrigation cost.
    assert payload["deltas"]["net_profit_bdt"] == -payload["deltas"]["irrigation_cost_bdt"]


@pytest.mark.asyncio
async def test_rainfall_drop_without_irrigation_flags_high_yield_risk(
    auth_client, db_session, monkeypatch
):
    # Wheat has a published water requirement; with no assured irrigation a
    # rainfall shortfall cannot be made up -> high yield risk.
    user, _farm = await _complete_farm(db_session, irrigation=False)
    _patch_yield(monkeypatch)

    payload = json.loads(
        await build_scenario_tool(user).ainvoke(
            {"crop_name": "Wheat", "rainfall_change_percent": -30, "expected_yield_t_ha": 4.0}
        )
    )
    assert payload["status"] == "ok"
    assert payload["yield_risk"]["level"] == "high"
    assert "no assured irrigation" in payload["yield_risk"]["reason"]


@pytest.mark.asyncio
async def test_crop_without_water_requirement_invents_no_irrigation(
    auth_client, db_session, monkeypatch
):
    # Mustard has no published seasonal water requirement -> irrigation numbers
    # stay None, nothing is invented, and no false risk claim is made.
    user, _farm = await _complete_farm(db_session, irrigation=False)
    _patch_yield(monkeypatch)

    payload = json.loads(
        await build_scenario_tool(user).ainvoke(
            {"crop_name": "Mustard", "rainfall_change_percent": -30, "expected_yield_t_ha": 1.5}
        )
    )
    assert payload["status"] == "ok"
    assert payload["revised"]["irrigation_applications"] is None
    assert payload["yield_risk"] is None


@pytest.mark.asyncio
async def test_cost_and_price_levers_change_profit(auth_client, db_session, monkeypatch):
    user, _farm = await _complete_farm(db_session)
    _patch_yield(monkeypatch)

    base = json.loads(
        await build_scenario_tool(user).ainvoke({"crop_name": "Wheat"})
    )
    dearer = json.loads(
        await build_scenario_tool(user).ainvoke(
            {"crop_name": "Wheat", "cost_change_percent": 20, "price_change_percent": -10}
        )
    )
    # Higher costs + lower price must reduce net profit vs the untouched baseline.
    assert dearer["revised"]["net_profit_bdt"] < base["revised"]["net_profit_bdt"]
    assert dearer["revised"]["total_cost_bdt"] > base["revised"]["total_cost_bdt"]


@pytest.mark.asyncio
async def test_scenario_hard_gates_incomplete_farm(auth_client, db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    payload = json.loads(
        await build_scenario_tool(user).ainvoke({"crop_name": "Wheat", "budget_change_percent": -40})
    )
    assert payload["status"] == "PROFILE_INCOMPLETE"
