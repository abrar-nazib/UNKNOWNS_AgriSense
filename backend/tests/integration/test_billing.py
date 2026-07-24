"""Integration tests for persisted mock billing and subscriptions."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.adapters.billing import OtpStartResult, SubscriptionResult
from app.config import settings
from app.models import Subscription
from app.routers import billing as billing_router

pytestmark = pytest.mark.integration
MASKED_SUBSCRIBER = f"tel:{'a' * 96}"


@pytest.fixture(autouse=True)
def mock_billing_provider(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_PROVIDER", "mock")
    monkeypatch.setattr(settings, "MOCK_OTP_CODE", "1234")
    for name in (
        "BDAPPS_PLUS_APPLICATION_ID",
        "BDAPPS_PLUS_PASSWORD",
        "BDAPPS_PLUS_APPLICATION_HASH",
        "BDAPPS_PRO_APPLICATION_ID",
        "BDAPPS_PRO_PASSWORD",
        "BDAPPS_PRO_APPLICATION_HASH",
        "BDAPPS_APPLICATION_ID",
        "BDAPPS_PASSWORD",
        "BDAPPS_APPLICATION_HASH",
    ):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "BDAPPS_PLAN_ID", "plus")


async def test_billing_requires_auth(client):
    assert (await client.get("/api/billing/plans")).status_code == 401
    assert (await client.get("/api/billing/subscription")).status_code == 401


async def test_plan_catalog_identifies_the_provisioned_bdapps_tariff(
    auth_client, monkeypatch
):
    mock_catalog = (await auth_client.get("/api/billing/plans")).json()
    assert mock_catalog["subscribable_plan_ids"] == ["plus", "pro"]

    monkeypatch.setattr(settings, "BILLING_PROVIDER", "bdapps")
    monkeypatch.setattr(settings, "BDAPPS_PLUS_APPLICATION_ID", "APP_PLUS")
    monkeypatch.setattr(settings, "BDAPPS_PLUS_PASSWORD", "plus-secret")
    monkeypatch.setattr(settings, "BDAPPS_PRO_APPLICATION_ID", "APP_PRO")
    monkeypatch.setattr(settings, "BDAPPS_PRO_PASSWORD", "pro-secret")
    bdapps_catalog = (await auth_client.get("/api/billing/plans")).json()
    assert bdapps_catalog["provider"] == "bdapps"
    assert bdapps_catalog["subscribable_plan_ids"] == ["plus", "pro"]


async def test_mock_subscription_persists_and_cancels(auth_client):
    initial = await auth_client.get("/api/billing/subscription")
    assert initial.status_code == 200
    assert initial.json()["plan_id"] == "free"
    assert initial.json()["status"] == "active"

    started = await auth_client.post(
        "/api/billing/otp/request", json={"plan_id": "plus"}
    )
    assert started.status_code == 201, started.text
    challenge = started.json()
    assert challenge["demo_otp"] == "1234"
    assert challenge["status_code"] == "S1000"

    wrong = await auth_client.post(
        "/api/billing/otp/verify",
        json={"challenge_id": challenge["challenge_id"], "otp": "9999"},
    )
    assert wrong.status_code == 400

    verified = await auth_client.post(
        "/api/billing/otp/verify",
        json={"challenge_id": challenge["challenge_id"], "otp": "1234"},
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["plan_id"] == "plus"
    assert body["status"] == "active"
    assert body["provider"] == "mock"
    assert body["amount_bdt"] == 199

    persisted = await auth_client.get("/api/billing/subscription")
    assert persisted.status_code == 200
    assert persisted.json()["plan_id"] == "plus"

    switch_without_cancelling = await auth_client.post(
        "/api/billing/otp/request", json={"plan_id": "pro"}
    )
    assert switch_without_cancelling.status_code == 409

    cancelled = await auth_client.post("/api/billing/subscription/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status_code"] == "S1000"
    assert cancelled.json()["subscription"]["status"] == "cancelled"

    after = await auth_client.get("/api/billing/subscription")
    assert after.json()["status"] == "cancelled"


async def test_server_rejects_free_plan_otp(auth_client):
    response = await auth_client.post(
        "/api/billing/otp/request", json={"plan_id": "free"}
    )
    assert response.status_code == 400


async def test_billing_otp_request_has_carrier_cooldown(auth_client):
    first = await auth_client.post(
        "/api/billing/otp/request", json={"plan_id": "plus"}
    )
    assert first.status_code == 201

    second = await auth_client.post(
        "/api/billing/otp/request", json={"plan_id": "plus"}
    )
    assert second.status_code == 429


async def test_bdapps_masked_identity_is_reused_for_status_and_cancel(
    auth_client, monkeypatch
):
    class FakeBdAppsProvider:
        name = "bdapps"

        def __init__(self):
            self.status_subscribers = []
            self.cancel_subscribers = []

        async def request_otp(self, subscriber_id):
            assert subscriber_id == "tel:8801712345678"
            return OtpStartResult(
                reference_no="real-reference",
                status_code="S1000",
                status_detail="Success",
            )

        async def verify_otp(self, reference_no, otp):
            assert reference_no == "real-reference"
            assert otp == "5678"
            return SubscriptionResult(
                status_code="S1000",
                status_detail="Success",
                subscription_status="REGISTERED",
                subscriber_id=MASKED_SUBSCRIBER,
            )

        async def get_status(self, subscriber_id):
            self.status_subscribers.append(subscriber_id)
            return SubscriptionResult(
                status_code="S1000",
                status_detail="Success",
                subscription_status="REGISTERED",
                subscriber_id=subscriber_id,
            )

        async def unsubscribe(self, subscriber_id):
            self.cancel_subscribers.append(subscriber_id)
            return SubscriptionResult(
                status_code="S1000",
                status_detail="Success",
                subscription_status="UNREGISTERED",
                subscriber_id=subscriber_id,
            )

    provider = FakeBdAppsProvider()
    monkeypatch.setattr(settings, "BILLING_PROVIDER", "bdapps")

    def provider_for(plan_id):
        assert plan_id == "plus"
        return provider

    monkeypatch.setattr(
        billing_router, "get_billing_provider", provider_for
    )

    started = await auth_client.post(
        "/api/billing/otp/request", json={"plan_id": "plus"}
    )
    assert started.status_code == 201
    verified = await auth_client.post(
        "/api/billing/otp/verify",
        json={
            "challenge_id": started.json()["challenge_id"],
            "otp": "5678",
        },
    )
    assert verified.status_code == 200
    assert verified.json()["subscriber_id"] == "01712345678"

    current = await auth_client.get("/api/billing/subscription")
    assert current.status_code == 200
    assert provider.status_subscribers == [MASKED_SUBSCRIBER]

    cancelled = await auth_client.post("/api/billing/subscription/cancel")
    assert cancelled.status_code == 200
    assert provider.cancel_subscribers == [MASKED_SUBSCRIBER]


async def test_bdapps_sms_callback_requires_matching_application(client, monkeypatch):
    monkeypatch.setattr(settings, "BDAPPS_PLUS_APPLICATION_ID", "APP_PLUS")
    monkeypatch.setattr(settings, "BDAPPS_PLUS_PASSWORD", "plus-secret")
    monkeypatch.setattr(settings, "BDAPPS_PRO_APPLICATION_ID", "APP_PRO")
    monkeypatch.setattr(settings, "BDAPPS_PRO_PASSWORD", "pro-secret")
    payload = {
        "version": "1.0",
        "applicationId": "APP_PLUS",
        "sourceAddress": "tel:8801712345678",
        "message": "PLAN",
        "requestId": "sms-request-1",
        "encoding": "0",
    }

    accepted = await client.post("/api/bdapps/sms/receive", json=payload)
    assert accepted.status_code == 200
    assert accepted.json() == {
        "statusCode": "S1000",
        "statusDetail": "Request was successfully processed",
    }

    payload["applicationId"] = "APP_PRO"
    accepted_pro = await client.post("/api/bdapps/sms/receive", json=payload)
    assert accepted_pro.status_code == 200

    payload["applicationId"] = "APP_OTHER"
    rejected = await client.post("/api/bdapps/sms/receive", json=payload)
    assert rejected.status_code == 403


async def test_bdapps_notification_synchronizes_subscription(
    auth_client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "BDAPPS_PLUS_APPLICATION_ID", "APP_PLUS")
    monkeypatch.setattr(settings, "BDAPPS_PLUS_PASSWORD", "plus-secret")
    notification = {
        "timeStamp": "2607241800",
        "version": "1.0",
        "applicationId": "APP_PLUS",
        "password": "plus-secret",
        "subscriberId": "tel:8801712345678",
        "frequency": "monthly",
        "status": "REGISTERED.",
    }

    registered = await auth_client.post(
        "/api/bdapps/subscription/notify", json=notification
    )
    assert registered.status_code == 200
    subscription = await auth_client.get("/api/billing/subscription")
    assert subscription.status_code == 200
    assert subscription.json()["plan_id"] == "plus"
    assert subscription.json()["status"] == "active"
    assert subscription.json()["provider"] == "bdapps"

    stored_result = await db_session.execute(select(Subscription))
    stored = stored_result.scalar_one()
    stored.subscriber_id = MASKED_SUBSCRIBER
    await db_session.commit()

    notification["subscriberId"] = MASKED_SUBSCRIBER
    notification["status"] = "UNREGISTERED."
    unregistered = await auth_client.post(
        "/api/bdapps/subscription/notify", json=notification
    )
    assert unregistered.status_code == 200
    subscription = await auth_client.get("/api/billing/subscription")
    assert subscription.json()["status"] == "cancelled"

    notification["password"] = "wrong"
    rejected = await auth_client.post(
        "/api/bdapps/subscription/notify", json=notification
    )
    assert rejected.status_code == 403


async def test_bdapps_pro_callback_uses_pro_tariff_and_ignores_stale_plus_cancel(
    auth_client, monkeypatch
):
    monkeypatch.setattr(settings, "BDAPPS_PLUS_APPLICATION_ID", "APP_PLUS")
    monkeypatch.setattr(settings, "BDAPPS_PLUS_PASSWORD", "plus-secret")
    monkeypatch.setattr(settings, "BDAPPS_PRO_APPLICATION_ID", "APP_PRO")
    monkeypatch.setattr(settings, "BDAPPS_PRO_PASSWORD", "pro-secret")

    pro_notification = {
        "timeStamp": "2607241800",
        "version": "1.0",
        "applicationId": "APP_PRO",
        "password": "pro-secret",
        "subscriberId": "tel:8801712345678",
        "frequency": "monthly",
        "status": "REGISTERED.",
    }
    registered = await auth_client.post(
        "/api/bdapps/subscription/notify", json=pro_notification
    )
    assert registered.status_code == 200
    subscription = await auth_client.get("/api/billing/subscription")
    assert subscription.json()["plan_id"] == "pro"
    assert subscription.json()["amount_bdt"] == 499
    assert subscription.json()["status"] == "active"

    stale_plus_cancel = {
        **pro_notification,
        "applicationId": "APP_PLUS",
        "password": "plus-secret",
        "status": "UNREGISTERED.",
    }
    ignored = await auth_client.post(
        "/api/bdapps/subscription/notify", json=stale_plus_cancel
    )
    assert ignored.status_code == 200
    subscription = await auth_client.get("/api/billing/subscription")
    assert subscription.json()["plan_id"] == "pro"
    assert subscription.json()["status"] == "active"
