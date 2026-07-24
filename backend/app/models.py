"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Display name — not unique (two farmers can share a name).
    username: Mapped[str] = mapped_column(String(150), index=True)
    # Mobile number is the unique identity + login credential (rural users
    # have phones, not email). Stored canonical as 11-digit "01XXXXXXXXX".
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    # Registration address — BBS/CZIS geocodes stored alongside display names
    # so the agent can feed upazila_code straight into CZIS/weather tools.
    division_name: Mapped[str] = mapped_column(String(80), default="")
    division_code: Mapped[str] = mapped_column(String(8), default="")
    district_name: Mapped[str] = mapped_column(String(80), default="")
    district_code: Mapped[str] = mapped_column(String(8), default="")
    upazila_name: Mapped[str] = mapped_column(String(80), default="")
    upazila_code: Mapped[str] = mapped_column(String(12), default="")
    union_name: Mapped[str] = mapped_column(String(80), default="")
    union_code: Mapped[str] = mapped_column(String(12), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class Farm(Base):
    """A farmer's field. Location is FARM-level, not user-level.

    Registration address only *prefills* the first farm — a user registered in
    Rajshahi can describe land in Naogaon, and one user can own several farms
    whose plans must never mix (docs/EXAMPLE_FLOW.md #2, #8).
    """

    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="")
    # Exactly one active farm per user drives the conversation context.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Location (BBS/CZIS geocodes; names + codes as at registration).
    division_name: Mapped[str] = mapped_column(String(80), default="")
    division_code: Mapped[str] = mapped_column(String(8), default="")
    district_name: Mapped[str] = mapped_column(String(80), default="")
    district_code: Mapped[str] = mapped_column(String(8), default="")
    upazila_name: Mapped[str] = mapped_column(String(80), default="")
    upazila_code: Mapped[str] = mapped_column(String(12), default="")
    union_name: Mapped[str] = mapped_column(String(80), default="")
    union_geocode: Mapped[str] = mapped_column(String(12), default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Area — normalized to decimals (shotok). The original value/unit and any
    # farmer-confirmed local conversion factor are kept for the audit trail.
    area_decimal: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_area_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_area_unit: Mapped[str] = mapped_column(String(24), default="")
    area_conversion_note: Mapped[str] = mapped_column(String(255), default="")

    # Land / soil.
    land_type: Mapped[str] = mapped_column(String(40), default="")
    soil_texture: Mapped[str] = mapped_column(String(40), default="")
    soil_test: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Water.
    irrigation_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    water_source: Mapped[str] = mapped_column(String(80), default="")

    # Constraints / preferences.
    budget_bdt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    season: Mapped[str] = mapped_column(String(20), default="")
    previous_crop: Mapped[str] = mapped_column(String(60), default="")
    risk_tolerance: Mapped[str] = mapped_column(String(12), default="")
    preferred_crops: Mapped[list] = mapped_column(JSON, default=list)
    excluded_crops: Mapped[list] = mapped_column(JSON, default=list)

    # Workflow phase for the bounded intake -> plan loop.
    phase: Mapped[str] = mapped_column(String(30), default="intake")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
    )


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class OtpChallenge(Base):
    """Short-lived OTP state for billing and password recovery."""

    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    provider_reference: Mapped[str] = mapped_column(String(160), default="")
    otp_hash: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class Subscription(Base):
    """The application's authoritative subscription record for a user."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(24), default="free")
    status: Mapped[str] = mapped_column(String(24), default="inactive")
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    provider_status: Mapped[str] = mapped_column(String(64), default="")
    # BDApps Pro applications may return an opaque/masked subscriber token
    # instead of the MSISDN. Keep the provider value verbatim so subsequent
    # status, cancellation and notification calls can be correlated.
    subscriber_id: Mapped[str] = mapped_column(
        String(255), default="", index=True
    )
    amount_bdt: Mapped[int] = mapped_column(Integer, default=0)
    billing_cycle: Mapped[str] = mapped_column(String(24), default="monthly")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_upto_id: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, default="")
    tool_trace: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_chat_messages_session_id_id", "session_id", "id"),)


class KnowledgeChunk(Base):
    """RAG knowledge base (FRG 2024 corpus + hand-curated agronomy notes).

    Separate from ``long_term_memory`` on purpose: different embedding
    provider/dimension (PLAN.md D3) and global (not user-scoped) content.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Document identity — re-ingesting the same source replaces its chunks.
    source: Mapped[str] = mapped_column(String(120), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional facets for filtered retrieval (e.g. crop="mustard").
    crop: Mapped[str] = mapped_column(String(60), default="", index=True)
    topic: Mapped[str] = mapped_column(String(120), default="")
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(settings.KB_EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(settings.EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
