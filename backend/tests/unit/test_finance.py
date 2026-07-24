"""Gold-number tests for the deterministic crop financial engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.engines.finance import (
    build_financial_projection,
    parse_yield_range,
    seeded_crop_rough_projection,
    supported_finance_crops,
)


def test_parse_yield_range_accepts_czis_formats_and_rejects_missing_numbers():
    assert parse_yield_range("4.0-5.0") == (Decimal("4.0"), Decimal("5.0"))
    assert parse_yield_range("9.7–10.7 t/ha") == (Decimal("9.7"), Decimal("10.7"))
    assert parse_yield_range("6") == (Decimal("6"), Decimal("6"))
    with pytest.raises(ValueError, match="yield"):
        parse_yield_range("not published")


def _projection(**overrides):
    args = {
        "crop_name": "Wheat",
        "area_decimal": 50,
        "yield_low_t_ha": 4,
        "yield_high_t_ha": 5,
        "budget_bdt": 30_000,
        "yield_source": {"source": "CZIS", "variety": "BARI Gom 33"},
    }
    args.update(overrides)
    return build_financial_projection(**args)


def test_projection_is_itemized_and_all_financial_identities_hold():
    result = _projection(sale_price_bdt_per_kg=40)

    assert len(result["cost_items"]) >= 7
    assert result["total_cost_bdt"] == sum(
        item["amount_bdt"] for item in result["cost_items"]
    )
    assert result["scenarios"]["base"]["yield_t_ha"] == 4.5
    for scenario in result["scenarios"].values():
        assert scenario["revenue_bdt"] - result["total_cost_bdt"] == pytest.approx(
            scenario["net_profit_bdt"], abs=0.01
        )
        assert scenario["roi_percent"] == pytest.approx(
            scenario["net_profit_bdt"] / result["total_cost_bdt"] * 100,
            abs=0.01,
        )

    base = result["scenarios"]["base"]
    assert result["break_even"]["yield_kg"] * base["price_bdt_per_kg"] == pytest.approx(
        result["total_cost_bdt"], abs=0.2
    )
    assert result["break_even"]["price_bdt_per_kg"] * base["yield_kg"] == pytest.approx(
        result["total_cost_bdt"], abs=0.2
    )
    assert result["math_checks"] == {
        "cost_items_sum_to_total": True,
        "profit_equals_revenue_minus_cost": True,
    }


def test_projection_changes_correctly_with_area_price_yield_and_cost_inputs():
    base = _projection(sale_price_bdt_per_kg=40)
    double_area = _projection(area_decimal=100, sale_price_bdt_per_kg=40)
    higher_price = _projection(sale_price_bdt_per_kg=50)
    lower_yield = _projection(
        sale_price_bdt_per_kg=40,
        yield_low_t_ha=3,
        yield_high_t_ha=3,
    )
    higher_cost = _projection(sale_price_bdt_per_kg=40, cost_adjustment_percent=20)

    assert double_area["total_cost_bdt"] == base["total_cost_bdt"] * 2
    assert double_area["scenarios"]["base"]["yield_kg"] == pytest.approx(
        base["scenarios"]["base"]["yield_kg"] * 2, abs=0.01
    )
    assert (
        higher_price["scenarios"]["base"]["revenue_bdt"]
        > base["scenarios"]["base"]["revenue_bdt"]
    )
    assert (
        lower_yield["scenarios"]["base"]["revenue_bdt"]
        < base["scenarios"]["base"]["revenue_bdt"]
    )
    assert higher_cost["total_cost_bdt"] == pytest.approx(base["total_cost_bdt"] * 1.2)


def test_farmer_cost_overrides_are_absolute_traceable_amounts():
    result = _projection(
        sale_price_bdt_per_kg=40,
        cost_overrides_bdt={"seed": 9_999, "irrigation": 0},
    )

    seed = next(item for item in result["cost_items"] if item["key"] == "seed")
    irrigation = next(
        item for item in result["cost_items"] if item["key"] == "irrigation"
    )
    assert seed["amount_bdt"] == 9_999
    assert seed["source_type"] == "farmer_estimate"
    assert irrigation["amount_bdt"] == 0
    assert result["assumptions"]["cost_overrides_bdt"] == {
        "irrigation": 0.0,
        "seed": 9999.0,
    }


def test_default_price_and_costs_are_prominently_disclosed_as_demo_values():
    result = _projection()

    assert result["price_assumption"]["source_type"] == "seeded_demo_value"
    assert all(
        item["source_type"] == "seeded_demo_value" for item in result["cost_items"]
    )
    assert any("not live" in warning.lower() for warning in result["warnings"])


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"area_decimal": 0}, "area"),
        ({"sale_price_bdt_per_kg": 0}, "price"),
        ({"cost_overrides_bdt": {"mystery": 10}}, "unknown cost"),
        ({"cost_adjustment_percent": -100}, "adjustment"),
    ],
)
def test_invalid_financial_inputs_fail_closed(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _projection(**kwargs)


# --------------------------------------------------------------------------- #
# Broad seeded crop coverage (beyond the 5 season-plan-only focused crops)
# --------------------------------------------------------------------------- #
def test_supported_finance_crops_covers_the_broader_rabi_list():
    crops = supported_finance_crops()
    assert len(crops) >= 50
    # the 5 focused-path crops that generate_season_plan can build a calendar for
    for name in ("wheat", "mustard", "potato", "maize", "boro dhan"):
        assert name in crops
    # crops with no BAMIS season-plan calendar but still financially projectable
    for name in ("onion", "lentil", "tomato", "garlic", "cabbage"):
        assert name in crops


def test_projection_works_for_a_crop_outside_the_five_focused_crops():
    result = build_financial_projection(
        crop_name="Lentil",
        area_decimal=20,
        yield_low_t_ha=1.1,
        yield_high_t_ha=1.5,
        sale_price_bdt_per_kg=110,
    )
    assert result["total_cost_bdt"] == sum(
        item["amount_bdt"] for item in result["cost_items"]
    )
    assert result["scenarios"]["base"]["revenue_bdt"] - result[
        "total_cost_bdt"
    ] == pytest.approx(result["scenarios"]["base"]["net_profit_bdt"], abs=0.01)


def test_supported_finance_crops_covers_every_czis_kharif_two_crop():
    crops = set(supported_finance_crops())

    assert {
        "b. aman dhan",
        "black gram",
        "bottle gourd",
        "brinjal",
        "chilli",
        "cotton",
        "country bean",
        "cucumber",
        "ground nut",
        "radish",
        "red amaranth",
        "ridge gourd",
        "stem amaranth",
        "t. aman dhan",
    } <= crops


def test_kharif_seeded_projection_keeps_its_source_link_and_demo_label():
    result = seeded_crop_rough_projection("Ash Gourd", area_decimal=10)

    source = result["yield_assumption"]["source"]
    assert source["source_type"] == "official_reference_yield_goal"
    assert source["source_url"].startswith("https://apps.barc.gov.bd/")
