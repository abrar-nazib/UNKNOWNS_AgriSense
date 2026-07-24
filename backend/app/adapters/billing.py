"""Billing providers: deterministic local mock and real BDApps subscription API."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from uuid import uuid4

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class BillingProviderError(RuntimeError):
    """Safe provider error that can be returned to an API client."""


@dataclass(frozen=True)
class OtpStartResult:
    reference_no: str
    status_code: str
    status_detail: str
    demo_otp: str | None = None


@dataclass(frozen=True)
class SubscriptionResult:
    status_code: str
    status_detail: str
    subscription_status: str
    subscriber_id: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code == "S1000"


@dataclass(frozen=True)
class BdAppsCredentials:
    plan_id: str
    application_id: str
    password: str
    application_hash: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.application_id and self.password)


def bdapps_credentials_for_plan(plan_id: str) -> BdAppsCredentials:
    """Resolve one provisioned BDApps application for an internal plan."""

    if plan_id == "plus":
        configured = BdAppsCredentials(
            plan_id="plus",
            application_id=settings.BDAPPS_PLUS_APPLICATION_ID.strip(),
            password=settings.BDAPPS_PLUS_PASSWORD,
            application_hash=settings.BDAPPS_PLUS_APPLICATION_HASH.strip(),
        )
    elif plan_id == "pro":
        configured = BdAppsCredentials(
            plan_id="pro",
            application_id=settings.BDAPPS_PRO_APPLICATION_ID.strip(),
            password=settings.BDAPPS_PRO_PASSWORD,
            application_hash=settings.BDAPPS_PRO_APPLICATION_HASH.strip(),
        )
    else:
        return BdAppsCredentials(plan_id=plan_id, application_id="", password="")

    if (
        configured.application_id
        or configured.password
        or configured.application_hash
    ):
        return configured

    if settings.BDAPPS_PLAN_ID.strip() == plan_id:
        return BdAppsCredentials(
            plan_id=plan_id,
            application_id=settings.BDAPPS_APPLICATION_ID.strip(),
            password=settings.BDAPPS_PASSWORD,
            application_hash=settings.BDAPPS_APPLICATION_HASH.strip(),
        )
    return configured


def configured_bdapps_plan_ids() -> list[str]:
    return [
        plan_id
        for plan_id in ("plus", "pro")
        if bdapps_credentials_for_plan(plan_id).is_complete
    ]


def bdapps_subscriber_id(phone: str) -> str:
    """Convert canonical 01XXXXXXXXX into BDApps' tel:8801… form."""
    return f"tel:88{phone}"


class MockBillingProvider:
    name = "mock"

    async def request_otp(self, subscriber_id: str) -> OtpStartResult:
        return OtpStartResult(
            reference_no=f"mock-{uuid4()}",
            status_code="S1000",
            status_detail="Demo OTP generated.",
            demo_otp=settings.MOCK_OTP_CODE,
        )

    async def verify_otp(
        self, reference_no: str, otp: str
    ) -> SubscriptionResult:
        if otp != settings.MOCK_OTP_CODE:
            return SubscriptionResult(
                status_code="E1312",
                status_detail="Invalid OTP.",
                subscription_status="UNREGISTERED",
            )
        return SubscriptionResult(
            status_code="S1000",
            status_detail="Subscription activated in demo mode.",
            subscription_status="REGISTERED",
        )

    async def get_status(self, subscriber_id: str) -> SubscriptionResult:
        return SubscriptionResult(
            status_code="S1000",
            status_detail="Demo subscription status loaded.",
            subscription_status="REGISTERED",
            subscriber_id=subscriber_id,
        )

    async def unsubscribe(self, subscriber_id: str) -> SubscriptionResult:
        return SubscriptionResult(
            status_code="S1000",
            status_detail="Subscription cancelled.",
            subscription_status="UNREGISTERED",
            subscriber_id=subscriber_id,
        )


class BdAppsBillingProvider:
    name = "bdapps"

    def __init__(self, credentials: BdAppsCredentials) -> None:
        self.credentials = credentials
        if not credentials.is_complete:
            raise BillingProviderError(
                f"BDApps credentials for the {credentials.plan_id} plan "
                "are missing."
            )

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{settings.BDAPPS_BASE_URL.rstrip('/')}{path}"
        body = {
            "applicationId": self.credentials.application_id,
            "password": self.credentials.password,
            **payload,
        }
        try:
            async with httpx.AsyncClient(
                timeout=settings.BDAPPS_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json;charset=utf-8"},
                )
        except httpx.RequestError as exc:
            logger.warning(
                "BDApps request failed (path=%s, error=%s)",
                path,
                type(exc).__name__,
            )
            raise BillingProviderError(
                "BDApps is temporarily unavailable. Please try again."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(
                "BDApps returned non-JSON data (path=%s, status=%s)",
                path,
                response.status_code,
            )
            raise BillingProviderError(
                "BDApps returned an invalid response."
            ) from exc

        if not isinstance(data, dict):
            raise BillingProviderError("BDApps returned an invalid response.")
        if response.is_error:
            detail = str(
                data.get("statusDetail") or "BDApps rejected the request."
            )
            logger.warning(
                "BDApps rejected request (path=%s, status=%s, code=%s)",
                path,
                response.status_code,
                data.get("statusCode", "unknown"),
            )
            raise BillingProviderError(detail)
        return data

    async def request_otp(self, subscriber_id: str) -> OtpStartResult:
        payload = {"subscriberId": subscriber_id}
        if self.credentials.application_hash:
            payload["applicationHash"] = self.credentials.application_hash
        data = await self._post("/otp/request", payload)
        code = str(data.get("statusCode", ""))
        if code != "S1000" or not data.get("referenceNo"):
            raise BillingProviderError(
                str(data.get("statusDetail") or "BDApps could not send the OTP.")
            )
        return OtpStartResult(
            reference_no=str(data["referenceNo"]),
            status_code=code,
            status_detail=str(data.get("statusDetail", "Success")),
        )

    async def verify_otp(
        self, reference_no: str, otp: str
    ) -> SubscriptionResult:
        data = await self._post(
            "/otp/verify", {"referenceNo": reference_no, "otp": otp}
        )
        return SubscriptionResult(
            status_code=str(data.get("statusCode", "")),
            status_detail=str(data.get("statusDetail", "OTP verification failed.")),
            subscription_status=str(
                data.get("subscriptionStatus", "UNREGISTERED")
            ).rstrip("."),
            subscriber_id=str(data.get("subscriberId", "")),
        )

    async def get_status(self, subscriber_id: str) -> SubscriptionResult:
        data = await self._post(
            "/subscription/getStatus", {"subscriberId": subscriber_id}
        )
        return SubscriptionResult(
            status_code=str(data.get("statusCode", "")),
            status_detail=str(data.get("statusDetail", "Status query failed.")),
            subscription_status=str(
                data.get("subscriptionStatus", "UNREGISTERED")
            ).rstrip("."),
            subscriber_id=subscriber_id,
        )

    async def unsubscribe(self, subscriber_id: str) -> SubscriptionResult:
        data = await self._post(
            "/subscription/send",
            {"subscriberId": subscriber_id, "action": "0"},
        )
        return SubscriptionResult(
            status_code=str(data.get("statusCode", "")),
            status_detail=str(data.get("statusDetail", "Unsubscribe failed.")),
            subscription_status=str(
                data.get("subscriptionStatus", "UNREGISTERED")
            ).rstrip("."),
            subscriber_id=subscriber_id,
        )


def get_billing_provider(plan_id: str | None = None):
    provider = settings.BILLING_PROVIDER.strip().lower()
    if provider == "mock":
        return MockBillingProvider()
    if provider == "bdapps":
        if not plan_id:
            raise BillingProviderError(
                "A billing plan is required for BDApps."
            )
        return BdAppsBillingProvider(bdapps_credentials_for_plan(plan_id))
    raise BillingProviderError(
        "BILLING_PROVIDER must be either 'mock' or 'bdapps'."
    )
