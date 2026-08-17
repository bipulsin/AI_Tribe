# Policy module — what is live vs simulated (this build)

This document is the source of truth for demo honesty. Do not remove labels unless the corresponding integration is live **and tested**.

## Live

- Authenticated `/policy` UI inside AI Tribe (same session cookie as the rest of the app).
- Conversation state persisted in PostgreSQL.
- Entity extraction: regex plus the existing MiniLM / spaCy NLU stack when available.
- **EKO Vahan RC lookup** when `EKO_VEHICLE_API_KEY`, `EKO_DEVELOPER_KEY`, and `EKO_INITIATOR_ID` are all set and the API returns vehicle data. Result label: **Live Vahan Lookup**.
- Demo PDF download served from the server.

## Simulated / fallback (labelled in UI)

- **Vehicle lookup fallback** when EKO is unset, incomplete, times out, or errors. Label: **Demo Data — Fallback**. Prefix map: MH Swift, DL Creta, KA Innova, TN Nexon, else generic hatchback.
- **KYC**: `mock_insurer_tagged` only. Label: **Simulated Verification — Insurer-Tagged**. No DigiLocker, UIDAI, or insurer KYC API.
- **Quotations**: three internal demo insurers. Label: **Demo Quotation — Illustrative Only**. Not real premiums.
- **Policy issuance**: local PDF with watermark. Label: **Demo Policy Artifact — Not a Valid Insurance Document**. `source_mode=demo_issuance`.

## Not in this phase

WhatsApp, SMS, payments, real insurer bind, DigiLocker/Aadhaar OTP, face match, renewals, commissions, agent hierarchy, production underwriting.
