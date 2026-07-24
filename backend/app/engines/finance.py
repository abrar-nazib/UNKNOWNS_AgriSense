"""Deterministic financial projection: itemized cost, revenue, profit, ROI,
break-even (Tier 0 #5, PLAN.md Task 7).

Pure ``Decimal`` math, no I/O — callers (the ``calculate_financials`` tool)
gather real CZIS fertilizer doses + seeded cost/price references and pass
already-resolved numbers in. Every cost item and yield/price scenario carries
a ``source`` label (``czis_computed`` / ``seeded_demo_value`` /
``farmer_estimate``) so the agent can tell the farmer exactly which numbers
are real, which are placeholders, and which they themselves supplied.

Internal-consistency invariants (asserted by construction + gold-tested):
- itemized costs sum EXACTLY to ``total_cost_tk`` (no separate rounding path)
- for every scenario, ``net_profit_tk == revenue_tk - total_cost_tk`` exactly
- ``roi_pct`` sign always matches ``net_profit_tk`` sign
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

TWO_PLACES = Decimal("0.01")

# Case-insensitive substring match, longest key first, against CZIS product
# names (e.g. "Zinc Sulphate (M)", "Urea (if DAP is used)"). Falls back to
# ``_default_tk_per_kg`` — flagged distinctly so the agent never presents an
# unlabeled guess as a real reference price.
_PRICE_LOOKUP_ORDER = [
    "zinc sulphate", "magnesium sulphate", "ammonium sulphate", "boric acid",
    "gypsum", "zinc", "boron", "potash", "urea", "tsp", "dap", "mop",
]


def to_decimal(value) -> Decimal:
    """Convert any numeric-ish input to Decimal via its string form (never
    via float construction, which imports binary-float rounding noise)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class CostItem:
    name: str
    category: str  # "fertilizer" | "seed" | "labor" | "irrigation" | "pesticide" | "other"
    amount_tk: Decimal
    source: str  # "czis_computed" | "seeded_demo_value" | "farmer_estimate"
    note: str = ""


@dataclass
class ScenarioResult:
    label: str  # "low" | "base" | "high"
    yield_kg: Decimal
    price_tk_per_kg: Decimal
    revenue_tk: Decimal
    net_profit_tk: Decimal
    roi_pct: Decimal


@dataclass
class FinancialProjection:
    area_decimal: Decimal
    items: list[CostItem]
    total_cost_tk: Decimal
    scenarios: dict[str, ScenarioResult]
    break_even_yield_kg: Decimal  # yield needed (at base price) to cover total_cost
    break_even_price_tk_per_kg: Decimal  # price needed (at base yield) to cover total_cost
    yield_source: str
    price_source: str
    currency: str = "BDT"


def fertilizer_price_tk_per_kg(
    product_name: str, prices: dict
) -> tuple[Decimal, bool]:
    """Look up a per-kg price for a CZIS product name.

    Returns ``(price, matched)`` — ``matched=False`` means no known fertilizer
    name matched and the bundle's generic default was used (label this
    distinctly; it is a rougher guess than a matched seeded price).
    """
    low = (product_name or "").lower()
    for key in _PRICE_LOOKUP_ORDER:
        if key in low:
            return to_decimal(prices[key]), True
    return to_decimal(prices.get("_default_tk_per_kg", 35)), False


def fertilizer_cost_items(products: list[dict], prices: dict) -> list[CostItem]:
    """Itemize the REAL CZIS fertilizer dose into Tk costs.

    Skips ``is_alternative`` rows (CZIS lists "or" swaps like Urea-if-DAP-used
    vs DAP — summing both would double-count the same nutrient). Converts
    gram amounts to kg before pricing.
    """
    items: list[CostItem] = []
    for p in products:
        if p.get("is_alternative"):
            continue
        amount = p.get("amount") or {}
        value = amount.get("value")
        unit = (amount.get("unit") or "kg").lower()
        if value is None:
            continue
        qty_kg = to_decimal(value) / Decimal(1000) if unit == "gm" else to_decimal(value)
        price, matched = fertilizer_price_tk_per_kg(p.get("product", ""), prices)
        cost = _quantize(qty_kg * price)
        items.append(
            CostItem(
                name=p.get("product", "fertilizer"),
                category="fertilizer",
                amount_tk=cost,
                source="seeded_demo_value" if matched else "seeded_demo_value_default",
                note=f"{qty_kg:g} kg @ {price} Tk/kg (CZIS-computed dose, seeded price)",
            )
        )
    return items


_CATEGORY_LABELS = {
    "seed_tk": ("seed", "seed"),
    "labor_tk": ("labor", "labor"),
    "irrigation_tk": ("irrigation", "irrigation"),
    "pesticide_tk": ("pesticide", "pesticide"),
}


def other_cost_items(
    area_decimal, rates_tk_per_decimal: dict, source: str = "seeded_demo_value"
) -> list[CostItem]:
    """Seed/labor/irrigation/pesticide costs scaled by farm area."""
    area = to_decimal(area_decimal)
    items: list[CostItem] = []
    for rate_key, (name, category) in _CATEGORY_LABELS.items():
        if rate_key not in rates_tk_per_decimal:
            continue
        rate = to_decimal(rates_tk_per_decimal[rate_key])
        amount = _quantize(rate * area)
        items.append(
            CostItem(
                name=name,
                category=category,
                amount_tk=amount,
                source=source,
                note=f"{rate} Tk/decimal x {area:g} decimal",
            )
        )
    return items


def project_financials(
    area_decimal,
    cost_items: list[CostItem],
    yield_kg_per_decimal: dict,
    price_tk_per_kg: dict,
    yield_source: str,
    price_source: str,
) -> FinancialProjection:
    """Compose itemized costs + low/base/high yield x price into a full
    projection. ``yield_kg_per_decimal`` / ``price_tk_per_kg`` are dicts with
    "low"/"base"/"high" keys (per-decimal yield, Tk/kg price).
    """
    area = to_decimal(area_decimal)
    total_cost = _quantize(sum((i.amount_tk for i in cost_items), Decimal(0)))

    scenarios: dict[str, ScenarioResult] = {}
    for label in ("low", "base", "high"):
        yield_per_decimal = to_decimal(yield_kg_per_decimal[label])
        price = to_decimal(price_tk_per_kg[label])
        yield_kg = _quantize(yield_per_decimal * area)
        revenue = _quantize(yield_kg * price)
        profit = _quantize(revenue - total_cost)
        roi_pct = (
            _quantize((profit / total_cost) * Decimal(100))
            if total_cost > 0
            else Decimal("0.00")
        )
        scenarios[label] = ScenarioResult(
            label=label,
            yield_kg=yield_kg,
            price_tk_per_kg=price,
            revenue_tk=revenue,
            net_profit_tk=profit,
            roi_pct=roi_pct,
        )

    base = scenarios["base"]
    break_even_yield_kg = (
        _quantize(total_cost / base.price_tk_per_kg) if base.price_tk_per_kg > 0 else Decimal("0.00")
    )
    break_even_price_tk_per_kg = (
        _quantize(total_cost / base.yield_kg) if base.yield_kg > 0 else Decimal("0.00")
    )

    return FinancialProjection(
        area_decimal=area,
        items=cost_items,
        total_cost_tk=total_cost,
        scenarios=scenarios,
        break_even_yield_kg=break_even_yield_kg,
        break_even_price_tk_per_kg=break_even_price_tk_per_kg,
        yield_source=yield_source,
        price_source=price_source,
    )


def to_jsonable(projection: FinancialProjection) -> dict:
    """Serialize a FinancialProjection to plain JSON-safe types."""
    return {
        "area_decimal": float(projection.area_decimal),
        "currency": projection.currency,
        "cost_items": [
            {
                "name": i.name,
                "category": i.category,
                "amount_tk": float(i.amount_tk),
                "source": i.source,
                "note": i.note,
            }
            for i in projection.items
        ],
        "total_cost_tk": float(projection.total_cost_tk),
        "scenarios": {
            label: {
                "yield_kg": float(s.yield_kg),
                "price_tk_per_kg": float(s.price_tk_per_kg),
                "revenue_tk": float(s.revenue_tk),
                "net_profit_tk": float(s.net_profit_tk),
                "roi_pct": float(s.roi_pct),
            }
            for label, s in projection.scenarios.items()
        },
        "break_even_yield_kg": float(projection.break_even_yield_kg),
        "break_even_price_tk_per_kg": float(projection.break_even_price_tk_per_kg),
        "yield_source": projection.yield_source,
        "price_source": projection.price_source,
    }
