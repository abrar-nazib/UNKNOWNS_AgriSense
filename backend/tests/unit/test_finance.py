"""Gold-number + internal-consistency tests for the deterministic finance
engine (Tier 0 #5, PLAN.md Task 7).

Judges change an input and check the outputs change correctly — these tests
are the regression guard for that: itemized costs must sum exactly to the
total, profit must equal revenue minus cost for every scenario, and area/
price/yield changes must move the numbers in the right direction.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app import finance_ref
from app.engines import finance

pytestmark = pytest.mark.unit


FERT_PRICES = {
    "urea": 27, "tsp": 34, "dap": 40, "mop": 25, "gypsum": 8,
    "zinc sulphate": 130, "_default_tk_per_kg": 35,
}

MUSTARD_COST_RATES = {
    "seed_tk": 15, "labor_tk": 45, "irrigation_tk": 20, "pesticide_tk": 10,
}

MUSTARD_YIELD = {"low": Decimal("4.5"), "base": Decimal("5.3"), "high": Decimal("6.5")}
MUSTARD_PRICE = {"low": Decimal("70"), "base": Decimal("85"), "high": Decimal("100")}


# --------------------------------------------------------------------------- #
# Fertilizer itemization
# --------------------------------------------------------------------------- #
def test_fertilizer_cost_items_skips_alternatives_and_converts_grams():
    products = [
        {"product": "Urea", "element": "Nitrogen",
         "amount": {"value": 58.373, "unit": "kg", "raw": "58.373 kg"},
         "is_alternative": False},
        {"product": "MoP", "element": "Potassium",
         "amount": {"value": 30.864, "unit": "kg", "raw": "30.864 kg"},
         "is_alternative": False},
        {"product": "Zinc Sulphate (M)", "element": "Zinc",
         "amount": {"value": 500, "unit": "gm", "raw": "500 gm"},
         "is_alternative": False},
        {"product": "Urea (if DAP is used)", "element": "Nitrogen",
         "amount": {"value": 40.0, "unit": "kg", "raw": "40 kg"},
         "is_alternative": True},
        {"product": "DAP", "element": "Phosphorus",
         "amount": {"value": 25.0, "unit": "kg", "raw": "25 kg"},
         "is_alternative": True},
    ]
    items = finance.fertilizer_cost_items(products, FERT_PRICES)
    names = [i.name for i in items]
    assert names == ["Urea", "MoP", "Zinc Sulphate (M)"]  # alternatives skipped

    urea = items[0]
    assert urea.amount_tk == Decimal("1576.07")  # 58.373 * 27, rounded
    zinc = items[2]
    # 500 gm -> 0.5 kg * 130 Tk/kg = 65.00
    assert zinc.amount_tk == Decimal("65.00")
    assert all(i.source.startswith("seeded_demo_value") for i in items)


def test_fertilizer_price_unmatched_product_uses_labeled_default():
    price, matched = finance.fertilizer_price_tk_per_kg("Some Obscure Micronutrient", FERT_PRICES)
    assert matched is False
    assert price == Decimal("35")


# --------------------------------------------------------------------------- #
# Other (seeded) costs
# --------------------------------------------------------------------------- #
def test_other_cost_items_scale_with_area():
    items = finance.other_cost_items(Decimal("33"), MUSTARD_COST_RATES)
    by_name = {i.name: i.amount_tk for i in items}
    assert by_name["seed"] == Decimal("495.00")       # 15 * 33
    assert by_name["labor"] == Decimal("1485.00")      # 45 * 33
    assert by_name["irrigation"] == Decimal("660.00")  # 20 * 33
    assert by_name["pesticide"] == Decimal("330.00")   # 10 * 33
    assert all(i.source == "seeded_demo_value" for i in items)


# --------------------------------------------------------------------------- #
# Full projection: gold numbers + internal consistency
# --------------------------------------------------------------------------- #
def _mustard_projection(area_decimal="33", yield_d=None, price_d=None, extra_items=None):
    other = finance.other_cost_items(Decimal(area_decimal), MUSTARD_COST_RATES)
    items = (extra_items or []) + other
    return finance.project_financials(
        Decimal(area_decimal),
        items,
        yield_d or MUSTARD_YIELD,
        price_d or MUSTARD_PRICE,
        yield_source="seeded_demo_value",
        price_source="seeded_demo_value",
    )


def test_gold_projection_for_reference_mustard_plot():
    proj = _mustard_projection()
    # cost = (15+45+20+10) * 33 = 90 * 33 = 2970.00
    assert proj.total_cost_tk == Decimal("2970.00")

    base = proj.scenarios["base"]
    # yield_kg = 5.3 * 33 = 174.9 ; revenue = 174.9 * 85 = 14866.50
    assert base.yield_kg == Decimal("174.90")
    assert base.revenue_tk == Decimal("14866.50")
    assert base.net_profit_tk == Decimal("11896.50")
    assert base.roi_pct == Decimal("400.56")


@pytest.mark.parametrize("label", ["low", "base", "high"])
def test_profit_equals_revenue_minus_cost_every_scenario(label):
    proj = _mustard_projection()
    s = proj.scenarios[label]
    assert s.net_profit_tk == s.revenue_tk - proj.total_cost_tk


def test_itemized_costs_sum_exactly_to_total():
    proj = _mustard_projection()
    assert sum((i.amount_tk for i in proj.items), Decimal(0)) == proj.total_cost_tk


def test_roi_sign_matches_profit_sign():
    # A price so low the plot runs at a loss -> ROI must be negative too.
    loss_price = {"low": Decimal("1"), "base": Decimal("1"), "high": Decimal("1")}
    proj = _mustard_projection(price_d=loss_price)
    for s in proj.scenarios.values():
        assert (s.net_profit_tk < 0) == (s.roi_pct < 0)


def test_break_even_consistency():
    proj = _mustard_projection()
    base = proj.scenarios["base"]
    # total_cost == break_even_yield * base_price (within cent rounding)
    assert abs(proj.break_even_yield_kg * base.price_tk_per_kg - proj.total_cost_tk) < Decimal("1")
    # total_cost == break_even_price * base_yield
    assert abs(proj.break_even_price_tk_per_kg * base.yield_kg - proj.total_cost_tk) < Decimal("1")


# --------------------------------------------------------------------------- #
# "Change an input -> outputs change correctly" (the judging criterion)
# --------------------------------------------------------------------------- #
def test_doubling_area_doubles_cost_yield_and_revenue_but_not_roi():
    proj_33 = _mustard_projection(area_decimal="33")
    proj_66 = _mustard_projection(area_decimal="66")

    assert proj_66.total_cost_tk == proj_33.total_cost_tk * 2
    b33, b66 = proj_33.scenarios["base"], proj_66.scenarios["base"]
    assert b66.yield_kg == b33.yield_kg * 2
    assert b66.revenue_tk == b33.revenue_tk * 2
    assert b66.net_profit_tk == b33.net_profit_tk * 2
    # ROI is a ratio — ratio of two things that both doubled == unchanged.
    assert b66.roi_pct == b33.roi_pct


def test_farmer_price_override_changes_revenue_and_profit():
    base_proj = _mustard_projection()
    low_price = {"low": Decimal("40"), "base": Decimal("40"), "high": Decimal("40")}
    dropped_proj = _mustard_projection(price_d=low_price)

    assert dropped_proj.scenarios["base"].revenue_tk < base_proj.scenarios["base"].revenue_tk
    assert dropped_proj.total_cost_tk == base_proj.total_cost_tk  # cost unaffected by price
    assert dropped_proj.scenarios["base"].net_profit_tk < base_proj.scenarios["base"].net_profit_tk


def test_adding_real_fertilizer_cost_increases_total_but_not_revenue():
    fert_items = finance.fertilizer_cost_items(
        [{"product": "Urea", "element": "Nitrogen",
          "amount": {"value": 58.373, "unit": "kg", "raw": "58.373 kg"},
          "is_alternative": False}],
        FERT_PRICES,
    )
    with_fert = _mustard_projection(extra_items=fert_items)
    without_fert = _mustard_projection()

    assert with_fert.total_cost_tk > without_fert.total_cost_tk
    assert (
        with_fert.scenarios["base"].revenue_tk
        == without_fert.scenarios["base"].revenue_tk
    )
    assert with_fert.scenarios["base"].net_profit_tk < without_fert.scenarios["base"].net_profit_tk


# --------------------------------------------------------------------------- #
# Seeded reference data accessor
# --------------------------------------------------------------------------- #
def test_crop_reference_lookup_is_case_insensitive():
    ref = finance_ref.crop_reference("MUSTARD")
    assert ref is not None
    assert ref["category"] == "oilseed"
    assert finance_ref.crop_reference("mustard") == ref


def test_crop_reference_unknown_crop_returns_none():
    assert finance_ref.crop_reference("Mango") is None  # perennial — out of scope
    assert finance_ref.crop_reference("Nonexistent Crop XYZ") is None


def test_covered_crops_are_all_seeded_and_labeled():
    names = finance_ref.covered_crops()
    assert len(names) >= 50
    assert "seeded_demo_value" in finance_ref.source().lower()
