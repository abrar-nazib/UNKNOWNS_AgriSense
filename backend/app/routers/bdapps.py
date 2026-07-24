"""Public callbacks used by the BDApps platform."""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.billing import (
    BdAppsCredentials,
    bdapps_credentials_for_plan,
)
from ..database import get_db
from ..models import Subscription, User
from .billing import PLANS

router = APIRouter(prefix="/api/bdapps", tags=["bdapps"])
logger = logging.getLogger(__name__)


class BdAppsPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class SmsReceiveIn(BdAppsPayload):
    version: str
    application_id: str = Field(alias="applicationId")
    source_address: str = Field(alias="sourceAddress")
    message: str
    request_id: str = Field(alias="requestId")
    encoding: str


class SubscriptionNotificationIn(BdAppsPayload):
    time_stamp: str = Field(alias="timeStamp")
    version: str
    application_id: str = Field(alias="applicationId")
    password: str
    subscriber_id: str = Field(alias="subscriberId")
    frequency: str
    status: str


class BdAppsAck(BdAppsPayload):
    status_code: str = Field(alias="statusCode")
    status_detail: str = Field(alias="statusDetail")


def _require_bdapps_credentials(
    application_id: str, password: str | None = None
) -> BdAppsCredentials:
    configured_apps = [
        credentials
        for plan_id in ("plus", "pro")
        if (credentials := bdapps_credentials_for_plan(plan_id)).is_complete
    ]
    if not configured_apps:
        raise HTTPException(
            status_code=503,
            detail="BDApps application credentials are not configured.",
        )

    for credentials in configured_apps:
        app_matches = hmac.compare_digest(
            application_id, credentials.application_id
        )
        password_matches = password is None or hmac.compare_digest(
            password, credentials.password
        )
        if app_matches and password_matches:
            return credentials
    raise HTTPException(status_code=403, detail="Invalid BDApps callback.")


def _canonical_phone(subscriber_id: str) -> str | None:
    raw = subscriber_id.strip()
    if raw.lower().startswith("tel:"):
        raw = raw[4:]
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) == 13 and digits.startswith("8801"):
        return digits[2:]
    if len(digits) == 11 and digits.startswith("01"):
        return digits
    return None


def _ack(detail: str = "Request was successfully processed") -> BdAppsAck:
    return BdAppsAck(status_code="S1000", status_detail=detail)


@router.post("/sms/receive", response_model=BdAppsAck)
async def receive_sms(payload: SmsReceiveIn) -> BdAppsAck:
    """Acknowledge inbound SMS delivery from BDApps.

    AgriSense does not use SMS text as an application command. Keeping this
    endpoint deliberately side-effect free satisfies the BDApps message
    receiving contract without persisting private message content.
    """

    credentials = _require_bdapps_credentials(payload.application_id)
    logger.info(
        "BDApps inbound SMS acknowledged "
        "(plan=%s, request_id=%s, encoding=%s)",
        credentials.plan_id,
        payload.request_id,
        payload.encoding,
    )
    return _ack()


@router.post("/subscription/notify", response_model=BdAppsAck)
async def subscription_notification(
    payload: SubscriptionNotificationIn,
    db: AsyncSession = Depends(get_db),
) -> BdAppsAck:
    """Synchronize asynchronous BDApps registration changes into Postgres."""

    credentials = _require_bdapps_credentials(
        payload.application_id, payload.password
    )
    provider_subscriber_id = payload.subscriber_id.strip()
    subscription_result = await db.execute(
        select(Subscription).where(
            Subscription.provider == "bdapps",
            Subscription.plan_id == credentials.plan_id,
            Subscription.subscriber_id == provider_subscriber_id,
        )
    )
    subscription = subscription_result.scalar_one_or_none()

    user = None
    if subscription is not None:
        user_result = await db.execute(
            select(User).where(User.id == subscription.user_id)
        )
        user = user_result.scalar_one_or_none()

    if user is None:
        phone = _canonical_phone(provider_subscriber_id)
        if phone is not None:
            user_result = await db.execute(
                select(User).where(User.phone == phone)
            )
            user = user_result.scalar_one_or_none()

    if user is None:
        # A masked notification received before the user completes OTP cannot
        # yet be correlated. Acknowledge it to prevent retries; OTP verification
        # and later status polling remain authoritative.
        logger.warning(
            "BDApps subscription notification had no correlated local user"
        )
        return _ack()

    if subscription is None:
        subscription_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = subscription_result.scalar_one_or_none()

    provider_status = payload.status.upper().rstrip(".")
    now = datetime.now(timezone.utc)

    if provider_status == "REGISTERED":
        plan = PLANS.get(credentials.plan_id)
        if plan is None or plan.id == "free":
            logger.error("BDApps callback does not identify a paid plan")
            return _ack()
        if subscription is None:
            subscription = Subscription(user_id=user.id)
            db.add(subscription)
        subscription.plan_id = plan.id
        subscription.status = "active"
        subscription.provider = "bdapps"
        subscription.provider_status = provider_status
        subscription.subscriber_id = provider_subscriber_id
        subscription.amount_bdt = plan.amount_bdt
        subscription.billing_cycle = payload.frequency.lower()
        subscription.started_at = subscription.started_at or now
        subscription.cancelled_at = None
    elif (
        subscription is not None
        and subscription.plan_id != credentials.plan_id
    ):
        # A delayed cancellation/inactive notification from the old BDApps
        # application must not cancel a newer plan.
        logger.info(
            "Ignored stale BDApps notification (callback_plan=%s, active_plan=%s)",
            credentials.plan_id,
            subscription.plan_id,
        )
    elif provider_status == "UNREGISTERED" and subscription is not None:
        subscription.status = "cancelled"
        subscription.provider_status = provider_status
        subscription.cancelled_at = now
    elif subscription is not None:
        subscription.status = "inactive"
        subscription.provider_status = provider_status

    await db.commit()
    return _ack()
