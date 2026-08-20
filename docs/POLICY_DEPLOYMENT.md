# Policy module deployment

## Environment (paperclip-vm)

Add to `/opt/stack/ai_tribe/.env` (never commit real secrets):

```
EKO_ACCESS_KEY=<access-key>
EKO_VEHICLE_API_KEY=<access-key-alias-optional>
EKO_DEVELOPER_KEY=<developer-key>
EKO_INITIATOR_ID=+91xxxxxxxxxx
EKO_BASE_URL=https://staging.eko.in/ekoapi/v3
KYC_MODE=mock_insurer_tagged
KYC_TIER1_ENABLED=false
KYC_TIER2_ENABLED=false
POLICY_DEMO_WATERMARK=NOT A VALID INSURANCE DOCUMENT
POLICY_DOCS_DIR=/app/data/policy_docs
```

`POLICY_DOCS_DIR` must be writable by the app user (compose volume `ai_tribe_policy_docs` maps to `/app/data/policy_docs`). ReportLab (`reportlab==4.2.5` in `backend/requirements.txt`) generates the illustrative PDF.

`EKO_ACCESS_KEY` is the HMAC access key (alias: `EKO_VEHICLE_API_KEY`). It is **never** sent to the browser. Live Vahan and PAN Lite also need `EKO_DEVELOPER_KEY` and `EKO_INITIATOR_ID`. If those are missing **or the live call fails** (403, timeout, auth, non-JSON), lookup uses **Fallback Data** and KYC uses **Simulated Verification — Insurer-Tagged** immediately so the chat does not stall.

Placeholders live in `.env.example`. Do not commit real keys.

## EKO API Integration

UAT base URL: `https://staging.eko.in/ekoapi/v3`. When production keys are issued, switch `EKO_BASE_URL` to `https://api.eko.in/ekoicici/v3` and replace the three secrets.

Test numbers (settings page and lab only): vehicle `HR26DA8398`, PAN `ABCDE1234F`, name `Test User`, DOB `1990-01-01`.

### Troubleshooting

- **Authentication (`response_status_id=2`)**: check access key, developer key, and that HMAC uses the base64 *string* of the access key (not decoded bytes). Logs never include `secret-key`.
- **Timeout / `response_status_id=4`**: the chat shows a delay notice and continues on fallback data.
- **HTTP 403 on `staging.eko.in/ekoapi/v3`**: the HMAC is accepted (production replies `Kindly use your production key` for these UAT credentials), but the UAT gateway currently returns Tomcat **403 Forbidden**. Ask EKO to whitelist the paperclip-vm egress IP for UAT, or confirm the exact UAT base path. Until that is open, lookups **immediately mimic** dummy data labelled **Fallback Data** / **Simulated Verification — Insurer-Tagged**. The chat continues.
- **Initiator rejected**: body must send `9170…` without a leading `+`.

## Deploy steps

```bash
ssh paperclip
cd /opt/stack/ai_tribe
git pull origin main
# If disk allows a rebuild:
# docker compose -p ai_tribe --profile ml up -d --build app_ml
# Otherwise hot-copy Python/templates/static, then:
docker exec ai_tribe_app_ml /opt/venv/bin/pip install -q reportlab==4.2.5
docker exec ai_tribe_app_ml sh -c "cd /app/backend && alembic upgrade head"
docker restart ai_tribe_app_ml
```

Hot-copy Python/templates/static **per file** (do not `docker cp` a directory, which can nest `policy/policy`). Do not `compose up --no-build` after a hot-copy unless you restore the copied files — recreate drops the writable layer.

## Verify

1. Logged-in left menu shows **Policy**; `/policy` shows the WhatsApp-style shell and the booking disclaimer. Anonymous `/policy` redirects to `/login`.
2. Complete a booking; refresh mid-flow; state is kept.
3. Registration lookup shows **Live Vahan Lookup** or **Fallback Data**.
4. KYC shows **Simulated Verification — Insurer-Tagged**; ID is masked in chat, summary, and DB.
5. Three quote cards, labelled illustrative; premiums differ by vehicle.
6. Select a quote — the simulated payment card appears. Pay Now issues the PDF. Download contains `NOT A VALID INSURANCE DOCUMENT`.
7. `/policy/crm` lists completed and abandoned sessions; filters work. Payment method and policy link show on the detail page.
8. `/policy/settings` masks the EKO key; test connection reports live vs fallback; settings persist.

## Tests

```bash
cd backend && python -m unittest tests.test_policy
```
