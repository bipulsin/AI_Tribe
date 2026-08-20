# EKO API integration (Vehicle RC + PAN Lite)

Live EKO Platform Services are used for **vehicle RC** and **PAN Lite** only. Quotes and issued PDFs stay illustrative.

## Credentials

Set these on the host `.env` (never in git, never in the browser):

| Variable | Purpose |
| --- | --- |
| `EKO_ACCESS_KEY` | HMAC access key (`EKO_VEHICLE_API_KEY` is a compatible alias) |
| `EKO_DEVELOPER_KEY` | Static `developer_key` header |
| `EKO_INITIATOR_ID` | Registered mobile. A leading `+` is stripped in the request body |
| `EKO_BASE_URL` | UAT: `https://staging.eko.in/ekoapi/v3`. Production: `https://api.eko.in/ekoicici/v3` |

HMAC: base64-encode the access key **string**, HMAC-SHA256 the millisecond timestamp with that string as the key, then base64-encode the digest. Implemented in `app/services/eko_auth.py` (`get_eko_headers()`). A new timestamp is generated for every call.

## Endpoints

- Vehicle RC: `POST {EKO_BASE_URL}/tools/kyc/vehicle-rc`
  Body: `initiator_id`, `vehicle_number`, `client_ref_id` (max 20 chars)
- PAN Lite: `POST {EKO_BASE_URL}/tools/kyc/pan-lite`
  Body: `initiator_id`, `pan_number`, `name`, `dob` (`YYYY-MM-DD`), `client_ref_id`

Success is `response_status_id == 0`. Status `1` on HTTP 200 is a genuine miss (user can retype). Any other failure — HTTP 401/403, timeout, non-JSON, `response_status_id` 2/4, missing payload, or an exception — **immediately mimics** dummy data so the chat never stalls. Mimic RC is labelled **Fallback Data**. Mimic PAN is labelled **Simulated Verification — Insurer-Tagged** (never **Live** / **EKO PAN Verification — Live** unless the live call actually succeeded).

## Caching and fallback

Vehicle lookups are cached per `session_id` + registration for 24 hours. Fallback data is labelled **Fallback Data** (`source=demo_fallback`). Live RC is labelled **Live Vahan Lookup** (`source=live_api`). Blacklisted vehicles pause the flow until the agent continues or resets.

PAN Lite runs when KYC mode is **EKO PAN Lite / Insurer API** and EKO is configured. Mock KYC remains the default. Live PAN failures mimic on the first attempt (no retry trap). Live PAN results use **EKO PAN Verification — Live**; mock uses **Simulated Verification — Insurer-Tagged**. Full PAN is never shown (masked `XXXX` + last four).

## Settings tests

`/policy/settings` → **Test EKO Connection** calls RC with `HR26DA8398` and PAN Lite with `ABCDE1234F` / `Test User` / `1990-01-01`. The response shows `response_status_id` and a data snippet. Credentials are not returned.

## Tests

```bash
cd backend && python3 -m unittest tests.test_eko_auth tests.test_policy
```
