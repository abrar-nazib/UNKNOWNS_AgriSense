"""Deterministic fertilizer & irrigation scheduler (Tier 1).

Turns the live CZIS farm-scaled fertilizer products and the BAMIS crop-water
requirement into an inspectable, costed schedule:

* per growth-stage chemical fertilizer quantities (relayed from CZIS) with a
  seeded, clearly-labelled retail cost;
* organic alternatives per product, sized by transparent nutrient-equivalence
  against the chemical's nutrient fraction and typical organic-source nutrient
  content (FRG 2024 organic-manure / IPNS guidance) — always flagged as an
  approximation that needs local IPNS adjustment, never a precise dose;
* an irrigation water balance from the BAMIS crop-water requirement minus
  effective rainfall, yielding the net irrigation depth, application count and
  a seeded cost, with a yield-risk flag when the deficit cannot be met.

No I/O, no LLM: pure functions over caller-supplied data so the numbers are
gold-tested and every figure states its provenance. Seeded money/price values
are demo assumptions (labelled ``seeded_demo_value``); crop-water requirement
and the CZIS quantities are real.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from .season_planner import CROP_PLANS, _profile

# --------------------------------------------------------------------------- #
# Seeded, clearly-labelled demo prices (BDT/kg retail, Bangladesh Rabi 2024).
# Not live supplier quotes — the tool/agent must present them as such.
# --------------------------------------------------------------------------- #
FERTILIZER_PRICES_BDT_PER_KG: dict[str, float] = {
    "urea": 27.0,
    "tsp": 27.0,
    "dap": 21.0,
    "mop": 20.0,
    "muriate of potash": 20.0,
    "gypsum": 12.0,
    "zinc sulphate": 220.0,
    "zinc": 220.0,
    "boron": 260.0,
    "magnesium sulphate": 30.0,
}

# Nutrient fraction supplied by each chemical carrier, used only to size an
# organic equivalent for the SAME element the CZIS row already lists.
CHEMICAL_NUTRIENT_FRACTION: dict[str, float] = {
    "urea": 0.46,          # % N
    "tsp": 0.46,           # % P2O5
    "dap": 0.46,           # dominant P2O5 (also 18% N)
    "mop": 0.60,           # % K2O
    "muriate of potash": 0.60,
    "gypsum": 0.18,        # % S
    "zinc sulphate": 0.33,  # % Zn (monohydrate)
    "zinc": 0.33,
}

# Typical nutrient content of organic sources (FRG 2024 organic-manure /
# Integrated Plant Nutrition System reference values). Percentages are on an
# air-dry basis and vary locally — hence every organic figure is emitted as an
# approximation requiring IPNS confirmation, never a precise recommendation.
ORGANIC_SOURCES_BY_ELEMENT: dict[str, list[dict[str, Any]]] = {
    "N": [
        {"name": "Mustard oil cake", "nutrient_pct": 5.0},
        {"name": "Poultry manure", "nutrient_pct": 2.5},
        {"name": "Vermicompost", "nutrient_pct": 1.5},
        {"name": "Well-rotted cowdung (FYM)", "nutrient_pct": 0.5},
    ],
    "P": [
        {"name": "Bone meal", "nutrient_pct": 20.0},
        {"name": "Poultry manure", "nutrient_pct": 1.8},
        {"name": "Compost / FYM", "nutrient_pct": 0.25},
    ],
    "K": [
        {"name": "Wood ash", "nutrient_pct": 5.0},
        {"name": "Vermicompost", "nutrient_pct": 1.0},
        {"name": "Compost / FYM", "nutrient_pct": 0.5},
    ],
    "S": [{"name": "Compost / FYM", "nutrient_pct": 0.2}],
    "Zn": [{"name": "Zinc-enriched compost", "nutrient_pct": 0.1}],
}

_ELEMENT_ALIASES = {
    "n": "N",
    "p": "P",
    "p2o5": "P",
    "k": "K",
    "k2o": "K",
    "s": "S",
    "zn": "Zn",
    "zinc": "Zn",
}

# Seeded irrigation assumptions (demo values, clearly labelled).
IRRIGATION_APPLICATION_DEPTH_MM = 50.0
IRRIGATION_COST_BDT_PER_DECIMAL_PER_APPLICATION = 20.0
# Rajshahi Rabi season is dry; a low seeded effective-rainfall default keeps the
# water balance defined when no live seasonal figure is supplied.
DEFAULT_SEASON_EFFECTIVE_RAINFALL_MM = 60.0

_MONEY = Decimal("0.01")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(_MONEY, rounding=ROUND_HALF_UP))


def _norm(name: str) -> str:
    return str(name or "").strip().lower()


def price_for(product_name: str) -> Optional[float]:
    """Seeded retail price (BDT/kg) for a fertilizer product, or ``None``."""
    return FERTILIZER_PRICES_BDT_PER_KG.get(_norm(product_name))


def _element_of(product_name: str, element: str) -> Optional[str]:
    canonical = _ELEMENT_ALIASES.get(_norm(element))
    if canonical:
        return canonical
    # Fall back to the carrier's dominant element when CZIS omits it.
    name = _norm(product_name)
    if name in ("urea",):
        return "N"
    if name in ("tsp", "dap"):
        return "P"
    if name in ("mop", "muriate of potash"):
        return "K"
    if name == "gypsum":
        return "S"
    if "zinc" in name:
        return "Zn"
    return None


def organic_alternatives(product_name: str, element: str, total_kg: float) -> dict:
    """Approximate organic substitutes to supply the same nutrient as ``total_kg``.

    Sizing: ``nutrient_kg = total_kg * chemical_fraction``; each organic option
    is ``nutrient_kg / (source_pct/100)``. Emitted as an IPNS approximation.
    """
    canonical = _element_of(product_name, element)
    fraction = CHEMICAL_NUTRIENT_FRACTION.get(_norm(product_name))
    if canonical is None or fraction is None or total_kg <= 0:
        return {
            "status": "unavailable",
            "reason": "no nutrient-equivalence reference for this product",
            "options": [],
        }
    nutrient_kg = _d(total_kg) * _d(fraction)
    options = []
    for source in ORGANIC_SOURCES_BY_ELEMENT.get(canonical, []):
        pct = _d(source["nutrient_pct"])
        if pct <= 0:
            continue
        qty = nutrient_kg / (pct / Decimal("100"))
        options.append(
            {
                "name": source["name"],
                "approx_kg": float(qty.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
                "nutrient_pct": float(pct),
            }
        )
    return {
        "status": "approximate",
        "element": canonical,
        "nutrient_kg": float(nutrient_kg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "options": options,
        "basis": (
            "Nutrient-equivalence approximation using the chemical carrier's "
            "nutrient fraction and typical organic-source content (FRG 2024 "
            "organic-manure / IPNS guidance). Confirm locally via IPNS; not a "
            "precise per-crop organic dose."
        ),
    }


def build_fertilizer_schedule(
    *,
    fertilizer_events: list[dict],
    soil_texture: str = "",
) -> dict:
    """Per-stage costed fertilizer schedule + season organic alternatives.

    ``fertilizer_events`` are the calendar's ``category == 'fertilizer'`` events,
    each carrying ``fertilizer_doses`` (product/element/amount) from the live
    CZIS farm-scaled recommendation.
    """
    stages: list[dict] = []
    product_totals: dict[str, dict] = {}
    total_cost = Decimal("0")
    priced_all = True

    for event in fertilizer_events:
        rows = []
        for dose in event.get("fertilizer_doses") or []:
            product = str(dose.get("product") or "").strip()
            amount = dose.get("amount") or {}
            try:
                kg = float(amount.get("value"))
            except (TypeError, ValueError):
                continue
            unit = amount.get("unit") or "kg"
            unit_price = price_for(product) if unit.lower() == "kg" else None
            if unit_price is None:
                priced_all = False
                cost = None
            else:
                cost = _money(_d(kg) * _d(unit_price))
                total_cost += _d(cost)
            rows.append(
                {
                    "product": product,
                    "element": dose.get("element"),
                    "kg": kg,
                    "unit": unit,
                    "unit_price_bdt_per_kg": unit_price,
                    "cost_bdt": cost,
                    "cost_source": "seeded_demo_value" if unit_price is not None else "unavailable",
                }
            )
            key = _norm(product)
            bucket = product_totals.setdefault(
                key, {"product": product, "element": dose.get("element"), "kg": 0.0}
            )
            bucket["kg"] = round(bucket["kg"] + kg, 3)
        stages.append(
            {
                "date": event.get("date"),
                "days_after_planting": event.get("days_after_planting"),
                "title": event.get("title"),
                "action": event.get("action"),
                "products": rows,
                "stage_cost_bdt": _money(
                    sum((_d(r["cost_bdt"]) for r in rows if r["cost_bdt"] is not None), Decimal("0"))
                ),
            }
        )

    organic = []
    for bucket in product_totals.values():
        organic.append(
            {
                "product": bucket["product"],
                "season_total_kg": bucket["kg"],
                "organic_equivalent": organic_alternatives(
                    bucket["product"], bucket["element"] or "", bucket["kg"]
                ),
            }
        )

    soil_note = None
    if _norm(soil_texture) in ("sandy", "sandy loam", "loamy sand"):
        soil_note = (
            "Sandy / light soils leach nitrogen faster: keep nitrogen in splits "
            "as scheduled and prioritise organic matter to improve retention."
        )

    return {
        "stages": stages,
        "season_product_totals": [
            {"product": b["product"], "element": b["element"], "kg": b["kg"]}
            for b in product_totals.values()
        ],
        "organic_alternatives": organic,
        "total_chemical_cost_bdt": _money(total_cost),
        "cost_complete": priced_all,
        "soil_note": soil_note,
        "cost_provenance": (
            "Chemical quantities are the live CZIS farm-scaled recommendation; "
            "prices are seeded demo retail values (BDT/kg), not live quotes."
        ),
    }


def crop_water_requirement_mm(crop_name: str) -> dict:
    """BAMIS-cited seasonal crop-water requirement, or an explicit unknown."""
    profile = _profile(crop_name)
    req = profile.get("water_requirement") or {}
    if req.get("total_mm"):
        return {"status": "known", "requirement_mm": float(req["total_mm"]), "basis": "BAMIS total_mm"}
    if req.get("seasonal_range_mm"):
        low, high = req["seasonal_range_mm"]
        return {
            "status": "known",
            "requirement_mm": float((low + high) / 2),
            "range_mm": [float(low), float(high)],
            "basis": "BAMIS seasonal range midpoint",
        }
    return {
        "status": "unknown",
        "requirement_mm": None,
        "note": req.get("note") or "BAMIS profile does not publish a seasonal water requirement for this crop.",
    }


def build_irrigation_schedule(
    *,
    crop_name: str,
    irrigation_events: list[dict],
    area_decimal: float,
    effective_rainfall_mm: Optional[float] = None,
    rainfall_change_percent: float = 0.0,
) -> dict:
    """Water balance -> net irrigation depth, application count and seeded cost.

    ``rainfall_change_percent`` (e.g. ``-30``) scales the effective rainfall for
    scenario simulation. Irrigation checkpoints come from the calendar; the cost
    uses seeded per-application demo values.
    """
    if area_decimal <= 0:
        raise ValueError("area must be greater than zero")

    water = crop_water_requirement_mm(crop_name)
    checkpoints = [
        {"date": e.get("date"), "days_after_planting": e.get("days_after_planting"), "action": e.get("action")}
        for e in irrigation_events
    ]

    baseline_rain = (
        float(effective_rainfall_mm)
        if effective_rainfall_mm is not None
        else DEFAULT_SEASON_EFFECTIVE_RAINFALL_MM
    )
    rain_source = "caller_supplied" if effective_rainfall_mm is not None else "seeded_demo_value"
    factor = Decimal("1") + _d(rainfall_change_percent) / Decimal("100")
    if factor < 0:
        factor = Decimal("0")
    adjusted_rain = float((_d(baseline_rain) * factor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    if water["status"] != "known":
        return {
            "water_balance": {"status": "unknown", **water},
            "checkpoints": checkpoints,
            "checkpoint_count": len(checkpoints),
            "note": "No seasonal water requirement published; irrigation cost not computed to avoid invention.",
            "cost_provenance": "No invented numbers: crop-water requirement unavailable for this crop.",
        }

    requirement = _d(water["requirement_mm"])
    deficit_mm = requirement - _d(adjusted_rain)
    if deficit_mm < 0:
        deficit_mm = Decimal("0")
    applications = int(math.ceil(float(deficit_mm) / IRRIGATION_APPLICATION_DEPTH_MM)) if deficit_mm > 0 else 0
    cost = _money(
        _d(applications)
        * _d(IRRIGATION_COST_BDT_PER_DECIMAL_PER_APPLICATION)
        * _d(area_decimal)
    )

    return {
        "water_balance": {
            "status": "known",
            "requirement_mm": float(requirement),
            "effective_rainfall_mm": adjusted_rain,
            "baseline_rainfall_mm": baseline_rain,
            "rainfall_change_percent": float(rainfall_change_percent),
            "rainfall_source": rain_source,
            "net_irrigation_mm": float(deficit_mm),
            "requirement_basis": water["basis"],
        },
        "recommended_applications": applications,
        "application_depth_mm": IRRIGATION_APPLICATION_DEPTH_MM,
        "estimated_cost_bdt": cost,
        "checkpoints": checkpoints,
        "checkpoint_count": len(checkpoints),
        "cost_provenance": (
            "Water requirement is BAMIS-cited; effective rainfall, application "
            "depth (50 mm) and per-application cost are seeded demo values."
        ),
    }
