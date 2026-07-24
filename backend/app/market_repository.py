"""Async persistence/query boundary for the seeded Tier 2 market dataset."""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .engines import market_research
from .models import MarketCropQuote, MarketInputOffer, MarketMerchant


async def seed_market_catalog(session: AsyncSession) -> dict[str, int]:
    expected_merchants = len(market_research.load_merchant_seed()["merchants"])
    existing = await session.scalar(select(func.count()).select_from(MarketMerchant))
    if existing == expected_merchants:
        return {"merchants": 0, "input_offers": 0, "crop_quotes": 0}
    if existing:
        await session.execute(delete(MarketMerchant))
        await session.flush()
    merchants_by_key: dict[str, MarketMerchant] = {}
    offer_count = 0
    for row in market_research.load_merchant_seed()["merchants"]:
        merchant = MarketMerchant(
            merchant_key=row["merchant_key"], name=row["name"], role=row["role"],
            district_name=row["district_name"], upazila_name=row["upazila_name"],
            latitude=row["latitude"], longitude=row["longitude"], rating=row["rating"],
            base_delivery_days=row["base_delivery_days"], service_radius_km=row["service_radius_km"],
        )
        session.add(merchant)
        merchants_by_key[row["merchant_key"]] = merchant
    await session.flush()
    for row in market_research.load_merchant_seed()["merchants"]:
        for input_key, unit, price, available, minimum in row["input_offers"]:
            session.add(MarketInputOffer(
                merchant_id=merchants_by_key[row["merchant_key"]].id, input_key=input_key,
                unit=unit, unit_price_bdt=price, available_quantity=available,
                minimum_order_quantity=minimum, in_stock=True,
            ))
            offer_count += 1
    quote_rows = market_research.build_crop_quote_seed()
    session.add_all(MarketCropQuote(
        merchant_id=merchants_by_key[row["merchant_key"]].id,
        crop_id=row["crop_id"], crop_name=row["crop_name"], quote_date=row["quote_date"],
        price_basis=row["price_basis"], price_per_kg_bdt=row["price_per_kg_bdt"],
        confidence=row["confidence"], source_label=row["source_label"],
    ) for row in quote_rows)
    await session.commit()
    return {"merchants": len(merchants_by_key), "input_offers": offer_count, "crop_quotes": len(quote_rows)}


async def find_input_offers(session: AsyncSession, input_key: str, unit: str) -> list[dict]:
    await seed_market_catalog(session)
    rows = (await session.execute(
        select(MarketInputOffer, MarketMerchant)
        .join(MarketMerchant, MarketMerchant.id == MarketInputOffer.merchant_id)
        .where(MarketInputOffer.input_key == input_key, MarketInputOffer.unit == unit)
    )).all()
    return [{
        "merchant_key": merchant.merchant_key, "merchant_name": merchant.name,
        "district_name": merchant.district_name, "upazila_name": merchant.upazila_name,
        "latitude": merchant.latitude, "longitude": merchant.longitude, "rating": merchant.rating,
        "base_delivery_days": merchant.base_delivery_days, "service_radius_km": merchant.service_radius_km,
        "unit": offer.unit, "unit_price_bdt": offer.unit_price_bdt,
        "available_quantity": offer.available_quantity, "minimum_order_quantity": offer.minimum_order_quantity,
        "in_stock": offer.in_stock, "source_label": offer.source_label,
    } for offer, merchant in rows]


async def crop_quotes(session: AsyncSession, crop_id: int, district_name: str = "") -> list[dict]:
    await seed_market_catalog(session)
    query = (
        select(MarketCropQuote, MarketMerchant)
        .join(MarketMerchant, MarketMerchant.id == MarketCropQuote.merchant_id)
        .where(MarketCropQuote.crop_id == crop_id)
        .order_by(MarketCropQuote.quote_date)
    )
    if district_name:
        query = query.where(MarketMerchant.district_name == district_name)
    rows = (await session.execute(query)).all()
    return [{
        "merchant_key": merchant.merchant_key, "merchant_name": merchant.name,
        "district_name": merchant.district_name, "upazila_name": merchant.upazila_name,
        "latitude": merchant.latitude, "longitude": merchant.longitude, "rating": merchant.rating,
        "crop_id": quote.crop_id, "crop_name": quote.crop_name, "quote_date": quote.quote_date,
        "price_basis": quote.price_basis, "price_per_kg_bdt": quote.price_per_kg_bdt,
        "confidence": quote.confidence, "source_label": quote.source_label,
    } for quote, merchant in rows]


async def count_distinct_quoted_crops(session: AsyncSession) -> int:
    await seed_market_catalog(session)
    return int(await session.scalar(select(func.count(func.distinct(MarketCropQuote.crop_id))) ) or 0)
