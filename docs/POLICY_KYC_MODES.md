# Policy KYC modes

Stored per user in `policy_settings` (Fernet-encrypted JSON, same pattern as BYOK). Env defaults: `KYC_MODE=mock_insurer_tagged`, `KYC_TIER1_ENABLED=false`, `KYC_TIER2_ENABLED=false`.

## 1. Insurer API / DigiLocker (`insurer_api`)

Placeholder for a future live insurer or DigiLocker integration.

**This build: Not Configured.** Selecting it falls back to mock and shows a warning on `/policy/settings`.

To activate later: implement a real provider in `app/policy/kyc.py`, require tested credentials, then stop falling back in `resolved_kyc_mode()`.

## 2. Local Extraction Pipeline (`local_extraction`)

- Tier 1 OCR (PaddleOCR) — **Disabled — not configured**
- Tier 2 Vision LLM (BYOK) — **Disabled — not configured**

Both toggles default off. Selecting this mode without a tested pipeline falls back to mock.

## 3. Mock Insurer-Tagged (`mock_insurer_tagged`) — default, working

- Format-validates PAN / Aadhaar on the server.
- First attempt: ~1 in 5 returns invalid (`document appears unclear, please re-enter`).
- Retry in the same session: always valid.
- Never invalid more than once per session.
- Stores and displays **last four characters only**.
- UI always shows **Simulated Verification — Insurer-Tagged**.
