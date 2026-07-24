"""Deterministic, inspectable financial projections for the focused crop path.

The engine performs no I/O and uses ``Decimal`` for every calculation.  Yield
comes from the caller (normally the live CZIS variety table).  Farmer-provided
price and item costs override the bundled, prominently labelled demo values.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DECIMAL_PER_HECTARE = Decimal("247.105")
_MONEY = Decimal("0.01")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_DATA_PATH = Path(__file__).parent.parent / "data" / "finance_assumptions.json"


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _number(value: Decimal, places: str = "0.01") -> float:
    return float(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    with open(_DATA_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def parse_yield_range(raw: str) -> tuple[Decimal, Decimal]:
    """Parse CZIS yield strings such as ``9.7-10.7 t/ha``."""
    values = [_d(value) for value in _NUMBER.findall(str(raw or ""))]
    if not values:
        raise ValueError("yield range contains no numeric value")
    low = values[0]
    high = values[1] if len(values) > 1 else values[0]
    if low <= 0 or high <= 0:
        raise ValueError("yield values must be positive")
    return (min(low, high), max(low, high))


def supported_finance_crops() -> list[str]:
    return sorted(_catalog()["crops"])


def seeded_crop_cost(crop_name: str, area_decimal: float) -> dict:
    """Return the disclosed demo cultivation-cost estimate for ranking.

    This deliberately excludes yield and sale price. It lets the recommender
    compare the farmer's one-season budget to a one-crop estimate instead of
    incorrectly comparing it to CZIS full-rotation cost.
    """
    key = str(crop_name or "").strip().lower()
    crop = _catalog()["crops"].get(key)
    area = _d(area_decimal)
    if crop is None:
        raise ValueError("unsupported crop for seeded cost estimate")
    if area <= 0:
        raise ValueError("area must be greater than zero")
    total = sum(
        (_d(rate) * area for rate in crop["cost_bdt_per_decimal"].values()),
        Decimal("0"),
    )
    return {
        "total_cost_bdt": float(_money(total)),
        "source_type": "seeded_demo_value",
        "catalog_version": _catalog()["version"],
        "warning": "Not a live quote; confirm actual input and labor costs locally.",
    }


def seeded_crop_rough_projection(crop_name: str, area_decimal: float) -> dict:
    """Build the disclosed crop-only comparison used by the recommender.

    Yield is an official FRG crop yield goal. Price and item costs remain
    prominently labelled demo assumptions, so this is suitable for shortlist
    comparison but never presented as a live quote or guaranteed return.
    """
    key = str(crop_name or "").strip().lower()
    crop = _catalog()["crops"].get(key)
    if crop is None:
        raise ValueError("unsupported crop for seeded rough projection")
    yield_ref = crop["reference_yield_t_ha"]
    source_name = str(yield_ref["source"])
    source_type = (
        "seeded_demo_value"
        if source_name.casefold().startswith("agrisense seeded demo")
        else "official_reference_yield_goal"
    )
    return build_financial_projection(
        crop_name=crop_name,
        area_decimal=area_decimal,
        yield_low_t_ha=yield_ref["low"],
        yield_high_t_ha=yield_ref["high"],
        yield_source={
            "source": yield_ref["source"],
            "pages": yield_ref["pages"],
            "basis": yield_ref["basis"],
            "source_type": source_type,
            **(
                {"source_url": yield_ref["source_url"]}
                if yield_ref.get("source_url")
                else {}
            ),
        },
    )


def build_financial_projection(
    *,
    crop_name: str,
    area_decimal: float,
    yield_low_t_ha: float,
    yield_high_t_ha: float,
    budget_bdt: Optional[float] = None,
    sale_price_bdt_per_kg: Optional[float] = None,
    cost_overrides_bdt: Optional[dict[str, float]] = None,
    cost_adjustment_percent: float = 0,
    yield_source: Optional[dict] = None,
) -> dict:
    """Return an itemized low/base/high projection with auditable formulas."""
    key = str(crop_name or "").strip().lower()
    crop = _catalog()["crops"].get(key)
    if crop is None:
        raise ValueError(
            "unsupported crop; choose one of: " + ", ".join(supported_finance_crops())
        )

    area = _d(area_decimal)
    low_yield = _d(yield_low_t_ha)
    high_yield = _d(yield_high_t_ha)
    adjustment = _d(cost_adjustment_percent)
    if area <= 0:
        raise ValueError("area must be greater than zero")
    if low_yield <= 0 or high_yield <= 0:
        raise ValueError("yield must be greater than zero")
    if adjustment <= Decimal("-100"):
        raise ValueError("cost adjustment must be greater than -100 percent")
    low_yield, high_yield = min(low_yield, high_yield), max(low_yield, high_yield)

    if sale_price_bdt_per_kg is None:
        price = _d(crop["price_bdt_per_kg"])
        price_source = "seeded_demo_value"
    else:
        price = _d(sale_price_bdt_per_kg)
        price_source = "farmer_estimate"
    if price <= 0:
        raise ValueError("price must be greater than zero")

    overrides = {
        str(name).strip().lower(): _d(value)
        for name, value in (cost_overrides_bdt or {}).items()
    }
    allowed = set(crop["cost_bdt_per_decimal"])
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise ValueError("unknown cost item(s): " + ", ".join(unknown))
    if any(value < 0 for value in overrides.values()):
        raise ValueError("cost overrides cannot be negative")

    factor = Decimal("1") + adjustment / Decimal("100")
    items: list[dict] = []
    for item_key, raw_rate in crop["cost_bdt_per_decimal"].items():
        if item_key in overrides:
            amount = _money(overrides[item_key])
            source_type = "farmer_estimate"
            rate = None
        else:
            rate_decimal = _d(raw_rate) * factor
            amount = _money(rate_decimal * area)
            source_type = "seeded_demo_value"
            rate = _number(rate_decimal)
        items.append(
            {
                "key": item_key,
                "label": item_key.replace("_", " ").title(),
                "amount_bdt": float(amount),
                "rate_bdt_per_decimal": rate,
                "source_type": source_type,
            }
        )
    total_cost = _money(sum((_d(item["amount_bdt"]) for item in items), Decimal("0")))

    area_ha = area / DECIMAL_PER_HECTARE
    yields = {
        "low": low_yield,
        "base": (low_yield + high_yield) / Decimal("2"),
        "high": high_yield,
    }
    prices = {
        "low": price * Decimal("0.90"),
        "base": price,
        "high": price * Decimal("1.10"),
    }
    scenarios: dict[str, dict] = {}
    profit_checks = []
    for name in ("low", "base", "high"):
        total_yield_kg = (yields[name] * Decimal("1000") * area_ha).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        scenario_price = prices[name].quantize(_MONEY, rounding=ROUND_HALF_UP)
        revenue = _money(total_yield_kg * scenario_price)
        net = _money(revenue - total_cost)
        roi = _money(net / total_cost * Decimal("100")) if total_cost else None
        scenarios[name] = {
            "yield_t_ha": _number(yields[name]),
            "yield_kg": float(total_yield_kg),
            "price_bdt_per_kg": float(scenario_price),
            "revenue_bdt": float(revenue),
            "net_profit_bdt": float(net),
            "roi_percent": float(roi) if roi is not None else None,
        }
        profit_checks.append(net == revenue - total_cost)

    base = scenarios["base"]
    break_even_yield = total_cost / _d(base["price_bdt_per_kg"])
    break_even_price = total_cost / _d(base["yield_kg"])
    warnings = [
        "Seeded demo cost values are not live supplier quotes; replace them with farmer or supplier figures before spending."
    ]
    if price_source == "seeded_demo_value":
        warnings.append(
            "The sale price is a seeded demo value, not a live farmgate market price; confirm it locally."
        )

    budget = _d(budget_bdt) if budget_bdt is not None else None
    budget_payload = None
    if budget is not None:
        budget_payload = {
            "available_bdt": _number(budget),
            "within_budget": total_cost <= budget,
            "surplus_or_gap_bdt": float(_money(budget - total_cost)),
        }

    return {
        "crop_name": crop_name,
        "area_decimal": _number(area),
        "area_hectare": _number(area_ha, "0.0001"),
        "cost_items": items,
        "total_cost_bdt": float(total_cost),
        "scenarios": scenarios,
        "expected": scenarios["base"],
        "break_even": {
            "yield_kg": _number(break_even_yield),
            # Four decimals keep the displayed break-even identity inspectable
            # even for small plots; ordinary money totals remain at paisa.
            "price_bdt_per_kg": _number(break_even_price, "0.0001"),
        },
        "budget": budget_payload,
        "yield_assumption": {
            "low_t_ha": _number(low_yield),
            "high_t_ha": _number(high_yield),
            "source": yield_source or {"source_type": "caller_provided"},
        },
        "price_assumption": {
            "value_bdt_per_kg": _number(price),
            "source_type": price_source,
        },
        "assumptions": {
            "catalog_version": _catalog()["version"],
            "cost_adjustment_percent": _number(adjustment),
            "cost_overrides_bdt": {
                name: _number(value) for name, value in sorted(overrides.items())
            },
            "scenario_rule": "low uses low yield and -10% price; base uses midpoint yield and base price; high uses high yield and +10% price",
        },
        "warnings": warnings,
        "math_checks": {
            "cost_items_sum_to_total": total_cost
            == sum((_d(item["amount_bdt"]) for item in items), Decimal("0")),
            "profit_equals_revenue_minus_cost": all(profit_checks),
        },
    }
