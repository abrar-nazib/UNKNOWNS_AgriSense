"""Integration coverage for farm-bound, CZIS-yield financial projections."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agent import tools as tools_mod
from app.agent.tools import _get_or_create_active_farm, build_financial_tool
from app.models import User


async def _complete_farm(db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    farm = await _get_or_create_active_farm(db_session, user)
    farm.area_decimal = 50.0
    farm.irrigation_available = True
    farm.water_source = "shallow tubewell"
    farm.budget_bdt = 30_000
    farm.season = "rabi"
    farm.phase = "ready_for_planning"
    await db_session.commit()
    return user


def _varieties(crop_id=3):
    return {
        "crop_id": crop_id,
        "varieties": [
            {
                "name": "BARI Gom 33",
                "yield_t_ha": "4.0-5.0",
                "duration_days": "115-120",
                "characteristics": "reference",
            },
            {
                "name": "BARI Gom 32",
                "yield_t_ha": "3.5-4.5",
                "duration_days": "110-115",
                "characteristics": "reference",
            },
        ],
        "evidence": {"source": "CZIS", "endpoint": f"/varieties/{crop_id}"},
    }


@pytest.mark.asyncio
async def test_finance_tool_hard_gates_incomplete_profile(auth_client, db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    payload = json.loads(
        await build_financial_tool(user).ainvoke({"crop_name": "Wheat"})
    )
    assert payload["status"] == "PROFILE_INCOMPLETE"


@pytest.mark.asyncio
async def test_finance_tool_uses_live_czis_yield_and_exposes_demo_assumptions(
    auth_client, db_session, monkeypatch
):
    user = await _complete_farm(db_session)

    async def varieties(crop_id, **kwargs):
        assert crop_id == 3
        return _varieties(crop_id)

    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", varieties)
    payload = json.loads(
        await build_financial_tool(user).ainvoke(
            {"crop_name": "Wheat", "variety_name": "BARI Gom 33"}
        )
    )

    assert payload["status"] == "ok"
    projection = payload["financial_projection"]
    assert projection["yield_assumption"]["source"]["source"] == "CZIS"
    assert projection["yield_assumption"]["source"]["variety"] == "BARI Gom 33"
    assert projection["expected"]["yield_t_ha"] == 4.5
    assert projection["price_assumption"]["source_type"] == "seeded_demo_value"
    assert projection["total_cost_bdt"] == sum(
        item["amount_bdt"] for item in projection["cost_items"]
    )
    assert projection["budget"]["available_bdt"] == 30_000


@pytest.mark.asyncio
async def test_finance_tool_farmer_inputs_override_price_yield_and_costs(
    auth_client, db_session, monkeypatch
):
    user = await _complete_farm(db_session)

    async def forbidden(*args, **kwargs):
        pytest.fail("CZIS is unnecessary when the farmer supplies expected yield")

    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", forbidden)
    payload = json.loads(
        await build_financial_tool(user).ainvoke(
            {
                "crop_name": "Wheat",
                "expected_yield_t_ha": 6,
                "sale_price_bdt_per_kg": 45,
                "cost_overrides_bdt": {"seed": 5000, "irrigation": 0},
            }
        )
    )

    assert payload["status"] == "ok"
    projection = payload["financial_projection"]
    assert projection["expected"]["yield_t_ha"] == 6
    assert projection["price_assumption"]["source_type"] == "farmer_estimate"
    assert projection["yield_assumption"]["source"]["source_type"] == "farmer_estimate"
    assert next(i for i in projection["cost_items"] if i["key"] == "seed")[
        "amount_bdt"
    ] == 5000


@pytest.mark.asyncio
async def test_finance_tool_czis_outage_fails_closed_without_inventing_yield(
    auth_client, db_session, monkeypatch
):
    user = await _complete_farm(db_session)

    async def unavailable(*args, **kwargs):
        raise tools_mod.czis_mod.CzisError("offline")

    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", unavailable)
    payload = json.loads(
        await build_financial_tool(user).ainvoke({"crop_name": "Wheat"})
    )

    assert payload["status"] == "YIELD_UNAVAILABLE"
    assert "financial_projection" not in payload
    assert "offline" in payload["error"]


@pytest.mark.asyncio
async def test_finance_tool_supports_a_crop_outside_the_five_season_plan_crops(
    auth_client, db_session, monkeypatch
):
    """Lentil has no BAMIS season-plan calendar (generate_season_plan can't
    build a dated calendar for it) but is one of the 50 seeded Rabi crops the
    standalone finance tool covers, so it should still produce a projection."""
    user = await _complete_farm(db_session)

    async def forbidden(*args, **kwargs):
        pytest.fail("CZIS is unnecessary when the farmer supplies expected yield")

    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", forbidden)
    payload = json.loads(
        await build_financial_tool(user).ainvoke(
            {
                "crop_name": "Lentil",
                "expected_yield_t_ha": 1.3,
                "sale_price_bdt_per_kg": 110,
            }
        )
    )

    assert payload["status"] == "ok"
    assert payload["selected_crop"]["name"] == "Lentil"
    projection = payload["financial_projection"]
    assert projection["total_cost_bdt"] == sum(
        item["amount_bdt"] for item in projection["cost_items"]
    )


@pytest.mark.asyncio
async def test_finance_tool_keeps_existing_focused_crop_aliases(
    auth_client, db_session
):
    """Broad catalog support must not break the existing Banglish aliases."""
    user = await _complete_farm(db_session)

    payload = json.loads(
        await build_financial_tool(user).ainvoke(
            {"crop_name": "sarisha", "expected_yield_t_ha": 2.0}
        )
    )

    assert payload["status"] == "ok"
    assert payload["selected_crop"]["name"] == "Mustard"


@pytest.mark.asyncio
async def test_finance_tool_rejects_crop_season_mismatch_before_network(
    auth_client, db_session, monkeypatch
):
    user = await _complete_farm(db_session)

    async def forbidden(*args, **kwargs):
        pytest.fail("network must not run for a crop outside the farm season")

    monkeypatch.setattr(tools_mod.czis_mod, "get_varieties", forbidden)
    payload = json.loads(
        await build_financial_tool(user).ainvoke({"crop_name": "Rice Aman"})
    )
    assert payload["status"] == "CROP_SEASON_MISMATCH"


@pytest.mark.asyncio
async def test_finance_tool_rejects_unknown_cost_override(
    auth_client, db_session, monkeypatch
):
    user = await _complete_farm(db_session)
    payload = json.loads(
        await build_financial_tool(user).ainvoke(
            {
                "crop_name": "Wheat",
                "expected_yield_t_ha": 5,
                "cost_overrides_bdt": {"magic": 100},
            }
        )
    )
    assert payload["status"] == "INVALID_FINANCIAL_INPUT"
    assert "unknown cost" in payload["message"]
