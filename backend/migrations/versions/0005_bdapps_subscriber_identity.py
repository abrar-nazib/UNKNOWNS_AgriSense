"""support masked BDApps subscriber identities

Revision ID: 0005_bdapps_subscriber_identity
Revises: 0004_merge_billing_user_union
Create Date: 2026-07-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_bdapps_subscriber_identity"
down_revision: Union[str, None] = "0004_merge_billing_user_union"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "subscriptions",
        "subscriber_id",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.create_index(
        "ix_subscriptions_subscriber_id",
        "subscriptions",
        ["subscriber_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscriptions_subscriber_id", table_name="subscriptions"
    )
    op.alter_column(
        "subscriptions",
        "subscriber_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
