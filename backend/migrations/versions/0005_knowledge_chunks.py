"""knowledge_chunks table (RAG knowledge base — Task 4)

Revision ID: 0005_knowledge_chunks
Revises: 0004_merge_billing_user_union
Create Date: 2026-07-24

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0005_knowledge_chunks"
down_revision: Union[str, None] = "0004_merge_billing_user_union"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# text-embedding-3-small native dimension. Fixed at migration time — changing
# the embed model/dim later means a new migration + full re-ingest.
KB_EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("crop", sa.String(length=60), nullable=False),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(KB_EMBEDDING_DIM), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_source"), "knowledge_chunks", ["source"]
    )
    op.create_index(op.f("ix_knowledge_chunks_crop"), "knowledge_chunks", ["crop"])
    # Corpus is small (hundreds of chunks) — exact scan is fine, no ivfflat
    # index needed; add one only if the corpus grows past ~50k rows.


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_chunks_crop"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_source"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
