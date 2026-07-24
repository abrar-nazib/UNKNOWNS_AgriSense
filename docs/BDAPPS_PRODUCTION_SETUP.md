# BDApps production setup

AgriSense uses the BDApps OTP and Subscription APIs. OTP verification is the
terminal activation action; there is no second payment/continue step. Plus and
Pro require separate BDApps applications because each application has one
provisioned recurring tariff.

## BDApps portal values

| Portal field | Value |
|---|---|
| Enable Mobile Originated SMS | Yes |
| Message Receiving URL | `https://agrisense.cortextech.dev/api/bdapps/sms/receive` |
| Enable Mobile Terminated SMS | Yes |
| Default Sender Address | The sender/short code assigned by BDApps |
| SMS Keyword | Plus: `agrisense`; Pro: `agrisense_pro` |
| USSD | Disabled; AgriSense has no USSD listener |
| CaaS | Disabled; recurring charging is owned by Subscription |
| Subscription Required | Yes |
| Subscription Response Message | `AgriSense Subscription is activated!` |
| Un-subscription Response Message | `AgriSense Subscription deactivated!` |
| Subscriber Confirmation Required | Yes |
| Send Subscription Notification | Yes |
| Subscription Notification URL | `https://agrisense.cortextech.dev/api/bdapps/subscription/notify` |
| Robi charging frequency | Monthly for both applications |
| Robi charging amount | Plus: BDT 199; Pro: BDT 499 |

## Server-only environment values

Put these in the production `.env` on the host. Never put them in a
`NEXT_PUBLIC_*` variable, browser code, Git, screenshots, or chat.

```dotenv
BILLING_PROVIDER=bdapps
BDAPPS_BASE_URL=https://developer.bdapps.com
BDAPPS_PLUS_APPLICATION_ID=APP_139278
BDAPPS_PLUS_PASSWORD=REPLACE_WITH_PLUS_APPLICATION_API_PASSWORD
BDAPPS_PLUS_APPLICATION_HASH=
BDAPPS_PRO_APPLICATION_ID=APP_REPLACE_WITH_PRO_ID
BDAPPS_PRO_PASSWORD=REPLACE_WITH_PRO_APPLICATION_API_PASSWORD
BDAPPS_PRO_APPLICATION_HASH=
BDAPPS_TIMEOUT_SECONDS=15
NEXT_PUBLIC_API_URL=https://agrisense.cortextech.dev
```

- `BDAPPS_PLUS_APPLICATION_ID`: the BDT 199 application's provisioned ID
  (`APP_139278`).
- `BDAPPS_PRO_APPLICATION_ID`: the BDT 499 application's provisioned `APP_…`
  ID.
- `BDAPPS_*_PASSWORD`: application password/API key from each app's
  credentials view. These are not the BDApps account password.
- `BDAPPS_*_APPLICATION_HASH`: optional for the web flow. Leave empty unless
  BDApps explicitly provides a hash for that application.

The legacy `BDAPPS_APPLICATION_ID`, `BDAPPS_PASSWORD`,
`BDAPPS_APPLICATION_HASH`, and `BDAPPS_PLAN_ID` values are supported only as a
single-app migration fallback. New production configuration should use the
per-plan variables above.

## Deploy

From the production checkout after the feature branch is merged:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 backend
```

The backend entrypoint applies Alembic migrations automatically. Migration
`0005_bdapps_subscriber_identity` expands the provider identity column for
masked BDApps Pro subscriber tokens.

## End-to-end acceptance test

1. Confirm `https://agrisense.cortextech.dev/health` returns HTTP 200.
2. Register or sign in with an eligible Robi number.
3. Open **Profile → Plan & billing** and choose **Plus**.
4. Test Plus: request the OTP, enter the real code, and confirm immediate
   activation at BDT 199.
5. Cancel Plus and confirm both AgriSense and the Plus BDApps app show
   UNREGISTERED.
6. Test Pro the same way and confirm BDT 499 and the Pro application are used.
7. Cancel Pro and confirm both systems show UNREGISTERED.

AgriSense deliberately requires cancellation before switching plans so a
subscriber cannot accidentally remain active—and charged—in both BDApps
applications.

Keep `BILLING_PROVIDER=mock` locally when a real Robi-number test is not being
performed; mock mode uses OTP `1234` and never charges a mobile account.

## Pre-approval sandbox testing

Until BDApps approves the applications and exposes their API passwords, test the
complete AgriSense checkout locally with `BILLING_PROVIDER=mock`. Rebuild the
services, register or sign in with any valid local phone, select Plus or Pro,
request the OTP, enter `1234`, verify that the plan becomes active immediately,
refresh Profile → Billing, and then cancel it. This exercises AgriSense's real
frontend, API routes, database persistence, and cancellation state without
calling BDApps or charging a number.

BDApps also publishes a separate Pro Developer Kit and SDK Simulator Guide for
gateway-level local testing. Use the simulator-provided base URL and credentials
from that guide; do not guess its host, port, application password, or OTP. If
the simulator exposes the production-compatible HTTP routes, temporarily set
`BILLING_PROVIDER=bdapps`, point `BDAPPS_BASE_URL` at the simulator, and put its
Plus/Pro test credentials in the matching `BDAPPS_*` variables. Revert to
`BILLING_PROVIDER=mock` afterward.

An application account password is not an application API password. Without
approved app credentials—or simulator-issued credentials—the real
`https://developer.bdapps.com` OTP flow cannot be authenticated.
