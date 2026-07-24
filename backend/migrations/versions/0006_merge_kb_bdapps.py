"""merge heads: knowledge_chunks + bdapps subscriber identity

Revision ID: 0006_merge_kb_bdapps
Revises: 0005_knowledge_chunks, 0005_bdapps_subscriber_identity
Create Date: 2026-07-24
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "0006_merge_kb_bdapps"
down_revision: Union[str, Sequence[str], None] = (
    "0005_knowledge_chunks",
    "0005_bdapps_subscriber_identity",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
