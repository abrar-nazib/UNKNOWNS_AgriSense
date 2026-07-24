"""Deterministic Tier 2 marketplace and crop-market calculations."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from ..adapters import czis as czis_mod
from .. import geo as geo_mod


SOURCE_LABEL = "seeded_demo_market_data"
EARTH_RADIUS_KM = 6371.0088
_SEED_PATH = Path(__file__).parent.parent / "data" / "market_merchants.json"

INPUT_ALIASES = {
    "seed": "seed",
    "seeds": "seed",
    "beej": "seed",
    "urea": "urea",
    "tsp": "tsp",
    "mop": "mop",
    "potash": "mop",
    "irrigation": "irrigation_service",
    "water": "irrigation_service",
    "pesticide": "crop_protection",
    "crop protection": "crop_protection",
}


def load_merchant_seed() -> dict[str, Any]:
    with _SEED_PATH.open(encoding="utf-8") as source:
        payload = json.load(source)
    templates = payload.get("merchants") or []
    districts = sorted(geo_mod.districts(), key=lambda row: row["code"])
    if len(templates) != 22 or len(districts) != 64:
        raise ValueError("market seed requires 22 templates and 64 Bangladesh districts")
    merchants = []
    for district in districts:
        for index, template in enumerate(templates):
            row, col = divmod(index, 5)
            # Small deterministic offsets avoid 22 merchants sharing one centroid.
            lat = float(district["lat"]) + (row - 2) * 0.012 + (col - 2) * 0.004
            lon = float(district["lon"]) + (col - 2) * 0.012 + (row - 2) * 0.004
            merchants.append({
                **template,
                "merchant_key": f"{district['code']}-{template['merchant_key']}",
                "name": f"{district['name_en']} {template['name']}",
                "district_code": district["code"],
                "district_name": district["name_en"],
                "upazila_name": "District service area",
                "latitude": round(lat, 5), "longitude": round(lon, 5),
            })
    return {"source_label": SOURCE_LABEL, "merchants": merchants}


def canonical_input_name(value: str) -> str:
    normalized = " ".join(str(value or "").lower().replace("_", " ").split())
    return INPUT_ALIASES.get(normalized, normalized.replace(" ", "_"))


def canonical_crop(crop_name: str) -> dict[str, Any] | None:
    needle = str(crop_name or "").strip().casefold()
    if not needle:
        return None
    crops = czis_mod.list_crops()
    exact = next((row for row in crops if row["name"].casefold() == needle), None)
    if exact:
        return exact
    return next((row for row in crops if needle in row["name"].casefold()), None)


def _base_crop_price(crop: dict[str, Any]) -> float:
    name = crop["name"].casefold()
    if any(token in name for token in ("rice", "dhan", "wheat", "maize", "corn", "barley")):
        base = 34.0
    elif any(token in name for token in ("potato", "onion", "garlic", "ginger", "turmeric")):
        base = 48.0
    elif any(token in name for token in ("mango", "banana", "guava", "papaya", "litchi")):
        base = 62.0
    elif any(token in name for token in ("jute", "tea", "tobacco", "cotton", "sugarcane")):
        base = 42.0
    else:
        base = 45.0
    return round(base + (int(crop["crop_id"]) % 11) * 1.85, 2)


def build_crop_quote_seed(as_of: date | None = None) -> list[dict[str, Any]]:
    """Build fixed daily histories for every catalog crop and two buyers."""
    quote_day = as_of or date.today()
    merchants = load_merchant_seed()["merchants"]
    buyers_by_district: dict[str, list[dict[str, Any]]] = {}
    for merchant in merchants:
        if merchant["role"] in {"crop_buyer", "hybrid"}:
            buyers_by_district.setdefault(merchant["district_code"], []).append(merchant)
    quotes: list[dict[str, Any]] = []
    for crop in czis_mod.list_crops():
        crop_id = int(crop["crop_id"])
        base = _base_crop_price(crop)
        for district_index, buyers in enumerate(buyers_by_district.values()):
            merchant = buyers[(crop_id + district_index) % len(buyers)]
            for offset in range(14):
                day = quote_day - timedelta(days=13 - offset)
                cycle = ((offset % 9) - 4) * 0.28
                phase = crop_id % 3
                trend = (offset - 30) * (0.055 if phase == 0 else -0.035 if phase == 1 else 0.006)
                price = max(8.0, base + (district_index % 7) * 0.35 + cycle + trend)
                quotes.append(
                    {
                        "merchant_key": merchant["merchant_key"],
                        "crop_id": crop_id,
                        "crop_name": crop["name"],
                        "quote_date": datetime.combine(day, time.min, tzinfo=timezone.utc),
                            "price_basis": "farmgate" if district_index % 2 == 0 else "wholesale",
                        "price_per_kg_bdt": round(price, 2),
                            "confidence": 0.78 if district_index % 2 == 0 else 0.72,
                        "source_label": SOURCE_LABEL,
                    }
                )
    return quotes


def haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (lat_a, lon_a, lat_b, lon_b))
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(value))


def _normalized(value: float, values: list[float], *, lower_is_better: bool) -> float:
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return 1.0
    ratio = (value - low) / (high - low)
    return 1.0 - ratio if lower_is_better else ratio


def rank_supplier_offers(
    offers: list[dict[str, Any]], quantity: float, farm_lat: float, farm_lon: float
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    exclusions = {"out_of_stock": 0, "quantity": 0, "service_radius": 0}
    for offer in offers:
        if not offer["in_stock"]:
            exclusions["out_of_stock"] += 1
            continue
        if quantity < offer["minimum_order_quantity"] or quantity > offer["available_quantity"]:
            exclusions["quantity"] += 1
            continue
        distance = haversine_km(farm_lat, farm_lon, offer["latitude"], offer["longitude"])
        if distance > offer["service_radius_km"]:
            exclusions["service_radius"] += 1
            continue
        delivery_days = min(7, int(offer["base_delivery_days"] + math.ceil(distance / 80)))
        candidates.append(
            {
                **offer,
                "distance_km": distance,
                "estimated_delivery_days": delivery_days,
                "total_item_price_bdt": quantity * offer["unit_price_bdt"],
                "stock_fit": min(1.0, offer["available_quantity"] / max(quantity, 1.0)),
            }
        )
    if not candidates:
        return [], exclusions
    prices = [row["total_item_price_bdt"] for row in candidates]
    distances = [row["distance_km"] for row in candidates]
    deliveries = [row["estimated_delivery_days"] for row in candidates]
    ratings = [row["rating"] for row in candidates]
    stock_fits = [row["stock_fit"] for row in candidates]
    for row in candidates:
        components = {
            "price": _normalized(row["total_item_price_bdt"], prices, lower_is_better=True),
            "distance": _normalized(row["distance_km"], distances, lower_is_better=True),
            "delivery": _normalized(row["estimated_delivery_days"], deliveries, lower_is_better=True),
            "rating": _normalized(row["rating"], ratings, lower_is_better=False),
            "stock_fit": _normalized(row["stock_fit"], stock_fits, lower_is_better=False),
        }
        row["score"] = round(
            0.40 * components["price"]
            + 0.25 * components["distance"]
            + 0.20 * components["delivery"]
            + 0.10 * components["rating"]
            + 0.05 * components["stock_fit"],
            4,
        )
        row["score_components"] = {
            **{key: round(value, 4) for key, value in components.items()},
            "price_weight": 0.40,
            "distance_weight": 0.25,
            "delivery_weight": 0.20,
            "rating_weight": 0.10,
            "stock_fit_weight": 0.05,
        }
        row["distance_km"] = round(row["distance_km"], 1)
    return sorted(candidates, key=lambda row: (-row["score"], row["distance_km"], row["merchant_key"])), exclusions


def analyze_price_history(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(quotes, key=lambda row: row["quote_date"])
    if len(rows) < 14:
        return {"action": "WAIT", "reason_code": "INSUFFICIENT_HISTORY", "observation_count": len(rows)}
    prices = [float(row["price_per_kg_bdt"]) for row in rows]
    latest = prices[-1]
    recent_7 = prices[-7:]
    recent_30 = prices[-30:]
    mean_7 = sum(recent_7) / len(recent_7)
    mean_30 = sum(recent_30) / len(recent_30)
    low, high = min(recent_30), max(recent_30)
    volatility = (high - low) / mean_30 if mean_30 else 0.0
    range_position = (latest - low) / (high - low) if high > low else 0.5
    movement_7 = (
        ((latest - recent_7[0]) / recent_7[0] * 100) if recent_7[0] else 0.0
    )
    if range_position >= 0.78 or (latest >= mean_30 * 1.05 and movement_7 <= 1.5):
        action, reason = "SELL_NOW", "PRICE_FAVOURABLE_IN_RECENT_RANGE"
    elif latest < mean_30 * 0.985 and movement_7 >= 3.0 and volatility <= 0.25:
        action, reason = "STORE", "RECOVERING_FROM_RECENT_LOW"
    else:
        action, reason = "WAIT", "MARKET_SIGNAL_INCONCLUSIVE"
    return {
        "action": action,
        "reason_code": reason,
        "observation_count": len(rows),
        "latest_price_per_kg_bdt": round(latest, 2),
        "average_7_day_bdt": round(mean_7, 2),
        "average_30_day_bdt": round(mean_30, 2),
        "range_30_day_bdt": {"low": round(low, 2), "high": round(high, 2)},
        "movement_7_day_percent": round(movement_7, 2),
        "volatility_30_day": round(volatility, 4),
        "range_position": round(range_position, 4),
    }
