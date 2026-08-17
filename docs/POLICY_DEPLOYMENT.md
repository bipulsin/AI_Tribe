# Policy module deployment

## Environment (paperclip-vm)

Add to `/opt/stack/ai_tribe/.env` (never commit real secrets):

```
EKO_VEHICLE_API_KEY=<access-key>
EKO_DEVELOPER_KEY=<developer-key>
EKO_INITIATOR_ID=<registered-mobile>
KYC_MODE=mock_insurer_tagged
KYC_TIER1_ENABLED=false
KYC_TIER2_ENABLED=false
POLICY_DEMO_WATERMARK=DEMO POLICY — NOT A VALID INSURANCE DOCUMENT
POLICY_DOCS_DIR=/app/data/policy_docs
```

`EKO_VEHICLE_API_KEY` is the HMAC access key. It is **never** sent to the browser. Live Vahan also needs `EKO_DEVELOPER_KEY` and `EKO_INITIATOR_ID`. If those are missing, lookup uses **Demo Data — Fallback** and says so.

Placeholders live in `.env.example`.

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

## Verify

1. Logged-in left menu shows **Policy**; `/policy` shows the WhatsApp-style shell and the demo disclaimer. Anonymous `/policy` redirects to `/login`.
2. Complete a booking; refresh mid-flow; state is kept.
3. Registration lookup shows **Live Vahan Lookup** or **Demo Data — Fallback**.
4. KYC shows **Simulated Verification — Insurer-Tagged**; ID is masked in chat, summary, and DB.
5. Three quote cards, labelled illustrative; premiums differ by vehicle.
6. PDF download contains `DEMO POLICY — NOT A VALID INSURANCE DOCUMENT`.
7. `/policy/crm` lists completed and abandoned sessions; filters work.
8. `/policy/settings` masks the EKO key; test connection reports live vs fallback; settings persist.

## Tests

```bash
cd backend && python -m unittest tests.test_policy
```
