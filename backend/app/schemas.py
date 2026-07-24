"""Pydantic request/response schemas and serialization helpers."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Bangladeshi mobile number: 11 digits, 01[3-9] + 8 digits (e.g. 01812345678).
_BD_PHONE_RE = re.compile(r"^01[3-9]\d{8}$")


def normalize_bd_phone(raw: str) -> str:
    """Accept 01…, +8801…, 8801… and return canonical 11-digit 01XXXXXXXXX.

    Raises ValueError if the result is not a valid BD mobile number.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("880"):
        digits = digits[3:]
    if len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits  # dropped leading zero
    if not _BD_PHONE_RE.match(digits):
        raise ValueError("Enter a valid Bangladeshi mobile number (e.g. 01712345678).")
    return digits


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)  # display name
    phone: str
    password1: str = Field(min_length=8)
    password2: str = Field(min_length=8)
    # Address (each cell carries its CZIS/BBS code alongside the name).
    division_name: str = Field(min_length=1, max_length=80)
    division_code: str = Field(min_length=1, max_length=8)
    district_name: str = Field(min_length=1, max_length=80)
    district_code: str = Field(min_length=1, max_length=8)
    upazila_name: str = Field(min_length=1, max_length=80)
    upazila_code: str = Field(min_length=1, max_length=12)
    # Union is OPTIONAL — some upazilas have no union rows in the gazetteer
    # (city corporations etc.). When provided it pins the farm to the union
    # centroid; when absent, coordinates fall back to the upazila centroid.
    # If a code IS sent it must be a real union of the chosen upazila.
    union_name: str = Field(default="", max_length=80)
    union_code: str = Field(default="", max_length=12)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return normalize_bd_phone(v)


class Address(BaseModel):
    division_name: str = ""
    division_code: str = ""
    district_name: str = ""
    district_code: str = ""
    upazila_name: str = ""
    upazila_code: str = ""
    union_name: str = ""
    union_code: str = ""


class UserOut(BaseModel):
    id: int
    username: str
    phone: str
    address: Address


class LoginRequest(BaseModel):
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return normalize_bd_phone(v)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class PasswordResetStartRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return normalize_bd_phone(v)


class PasswordResetStartOut(BaseModel):
    challenge_id: str
    expires_in_seconds: int
    message: str
    demo_otp: str | None = None


class PasswordResetConfirmRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    otp: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=256)


class ActionOut(BaseModel):
    message: str


# --------------------------------------------------------------------------- #
# Billing
# --------------------------------------------------------------------------- #
class BillingPlanOut(BaseModel):
    id: str
    name: str
    amount_bdt: int
    billing_cycle: str
    features: list[str]


class BillingPlansOut(BaseModel):
    results: list[BillingPlanOut]
    provider: str
    subscribable_plan_ids: list[str]


class SubscriptionOut(BaseModel):
    plan_id: str
    status: str
    provider: str
    provider_status: str = ""
    subscriber_id: str
    amount_bdt: int
    billing_cycle: str
    started_at: datetime | None = None
    cancelled_at: datetime | None = None


class BillingOtpStartRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=24)


class BillingOtpStartOut(BaseModel):
    challenge_id: str
    expires_in_seconds: int
    status_code: str
    status_detail: str
    demo_otp: str | None = None


class BillingOtpVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    otp: str = Field(min_length=4, max_length=8)


class BillingCancelOut(BaseModel):
    subscription: SubscriptionOut
    status_code: str
    status_detail: str


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None


class ToolTraceEntry(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    model: str = ""
    created_at: datetime


class SessionOut(BaseModel):
    id: int
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListOut(BaseModel):
    results: list[SessionOut]


class MessageListOut(BaseModel):
    session_id: int
    results: list[MessageOut]


# --------------------------------------------------------------------------- #
# Serialization helpers (used for both REST bodies and SSE frames)
# --------------------------------------------------------------------------- #
def user_out(user) -> "UserOut":
    return UserOut(
        id=user.id,
        username=user.username,
        phone=user.phone,
        address=Address(
            division_name=user.division_name,
            division_code=user.division_code,
            district_name=user.district_name,
            district_code=user.district_code,
            upazila_name=user.upazila_name,
            upazila_code=user.upazila_code,
            union_name=getattr(user, "union_name", "") or "",
            union_code=getattr(user, "union_code", "") or "",
        ),
    )


def serialize_message(msg) -> dict[str, Any]:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content or "",
        "tool_trace": msg.tool_trace or [],
        "model": msg.model or "",
        "created_at": _iso(msg.created_at),
    }


def serialize_session(session, message_count: int) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title or "",
        "message_count": message_count,
        "created_at": _iso(session.created_at),
        "updated_at": _iso(session.updated_at),
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
