"""Tier 2 seeded market-research tables.

Revision ID: 0007_market_research
Revises: 0006_merge_kb_bdapps
Create Date: 2026-07-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_market_research"
down_revision = "0006_merge_kb_bdapps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_merchants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("district_name", sa.String(length=80), nullable=False),
        sa.Column("upazila_name", sa.String(length=80), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("base_delivery_days", sa.Integer(), nullable=False),
        sa.Column("service_radius_km", sa.Float(), nullable=False),
        sa.Column("source_label", sa.String(length=48), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_key"),
    )
    op.create_index(op.f("ix_market_merchants_merchant_key"), "market_merchants", ["merchant_key"])
    op.create_index(op.f("ix_market_merchants_role"), "market_merchants", ["role"])
    op.create_table(
        "market_input_offers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("input_key", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=False),
        sa.Column("unit_price_bdt", sa.Float(), nullable=False),
        sa.Column("available_quantity", sa.Float(), nullable=False),
        sa.Column("minimum_order_quantity", sa.Float(), nullable=False),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("source_label", sa.String(length=48), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["market_merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_input_offers_input_key"), "market_input_offers", ["input_key"])
    op.create_index(op.f("ix_market_input_offers_merchant_id"), "market_input_offers", ["merchant_id"])
    op.create_table(
        "market_crop_quotes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("crop_id", sa.Integer(), nullable=False),
        sa.Column("crop_name", sa.String(length=120), nullable=False),
        sa.Column("quote_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_basis", sa.String(length=24), nullable=False),
        sa.Column("price_per_kg_bdt", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_label", sa.String(length=48), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["market_merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_crop_quotes_crop_id"), "market_crop_quotes", ["crop_id"])
    op.create_index(op.f("ix_market_crop_quotes_merchant_id"), "market_crop_quotes", ["merchant_id"])
    op.create_index(op.f("ix_market_crop_quotes_quote_date"), "market_crop_quotes", ["quote_date"])
    op.create_index("ix_market_crop_quotes_crop_date", "market_crop_quotes", ["crop_id", "quote_date"])
    op.create_index("ix_market_crop_quotes_merchant_date", "market_crop_quotes", ["merchant_id", "quote_date"])


def downgrade() -> None:
    op.drop_table("market_crop_quotes")
    op.drop_table("market_input_offers")
    op.drop_table("market_merchants")
