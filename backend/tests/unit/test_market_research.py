"""Unit tests for the deterministic Tier 2 market-research engine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.adapters import czis as czis_mod
from app.engines import market_research


pytestmark = pytest.mark.unit


def test_reviewed_seed_has_exactly_22_unique_bangladesh_merchants():
    seed = market_research.load_merchant_seed()

    assert len(seed["merchants"]) == 64 * 22
    assert len({row["merchant_key"] for row in seed["merchants"]}) == 64 * 22
    assert all(20.5 <= row["latitude"] <= 26.7 for row in seed["merchants"])
    assert all(88.0 <= row["longitude"] <= 92.8 for row in seed["merchants"])
    assert {row["district_name"] for row in seed["merchants"]} >= {"Chandpur", "Rajshahi"}
    assert all(sum(row["district_name"] == district for row in seed["merchants"]) == 22 for district in {row["district_name"] for row in seed["merchants"]})


def test_all_seeded_crop_quotes_reference_czis_catalog():
    catalog = {row["crop_id"] for row in czis_mod.list_crops()}
    quotes = market_research.build_crop_quote_seed()

    assert {quote["crop_id"] for quote in quotes} <= catalog
    assert len({quote["crop_id"] for quote in quotes}) == 129


def test_haversine_distance_is_symmetric_and_zero_for_same_point():
    assert market_research.haversine_km(24.3745, 88.6042, 24.3745, 88.6042) == 0
    assert market_research.haversine_km(24.3745, 88.6042, 24.3636, 88.6241) == pytest.approx(
        2.35, abs=0.25
    )


def test_supplier_score_exposes_every_approved_component():
    offers = [
        {
            "merchant_key": "near", "latitude": 24.3745, "longitude": 88.6042,
            "rating": 4.2, "base_delivery_days": 1, "service_radius_km": 100,
            "unit_price_bdt": 30, "available_quantity": 1000, "minimum_order_quantity": 10,
            "in_stock": True,
        },
        {
            "merchant_key": "far", "latitude": 24.55, "longitude": 88.80,
            "rating": 4.8, "base_delivery_days": 2, "service_radius_km": 100,
            "unit_price_bdt": 25, "available_quantity": 500, "minimum_order_quantity": 10,
            "in_stock": True,
        },
    ]
    ranked, exclusions = market_research.rank_supplier_offers(offers, 20, 24.3745, 88.6042)

    assert len(ranked) == 2
    assert exclusions == {"out_of_stock": 0, "quantity": 0, "service_radius": 0}
    assert ranked[0]["score_components"] == pytest.approx(
        {
            "price": ranked[0]["score_components"]["price"],
            "distance": ranked[0]["score_components"]["distance"],
            "delivery": ranked[0]["score_components"]["delivery"],
            "rating": ranked[0]["score_components"]["rating"],
            "stock_fit": ranked[0]["score_components"]["stock_fit"],
            "price_weight": 0.40,
            "distance_weight": 0.25,
            "delivery_weight": 0.20,
            "rating_weight": 0.10,
            "stock_fit_weight": 0.05,
        }
    )


def _quotes(prices: list[float]) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {"quote_date": start + timedelta(days=index), "price_per_kg_bdt": price}
        for index, price in enumerate(prices)
    ]


def test_price_history_actions_cover_sell_store_wait():
    assert market_research.analyze_price_history(_quotes([40] * 29 + [48]))["action"] == "SELL_NOW"
    assert market_research.analyze_price_history(_quotes([110] * 23 + [90, 91, 92, 93, 94, 95, 96]))["action"] == "STORE"
    assert market_research.analyze_price_history(_quotes([40] * 30))["action"] == "WAIT"
