# Policy Booking Demo Module — architecture

The Policy module is a **browser-only** guided booking assistant. It is styled like WhatsApp (bubbles, chips, timestamps) but has **no WhatsApp API, SDK, or mobile channel**.

## Component map

```
Left menu (user_chrome.html) → GET /policy
        │
        ▼
  Chat shell (policy/chat.html + policy_chat.js)
        │  POST /policy/chat/message
        ▼
  Flow engine (app/policy/flow.py)
        ├── extraction.py  regex + existing spaCy/MiniLM NLU
        ├── vehicle.py     EkoVahanProvider | DemoFallbackProvider
        ├── kyc.py         MockInsurerTaggedProvider (live); others placeholder
        ├── quotes.py      Demo Insurer A/B/C
        └── documents.py   ReportLab demo PDF
        │
        ▼
  PostgreSQL: policy_booking_requests and child tables
        │
        ├── GET /policy/crm        HTMX list + filters
        ├── GET /policy/crm/{id}   transcript + artefacts
        └── GET /policy/settings   Fernet-encrypted module settings
```

## Conversation steps

`welcome → collect_registration_number → vehicle_lookup → confirm_vehicle → collect_customer_name → collect_phone → collect_id_type → collect_id_number → collect_dob → collect_gender → collect_address → collect_pincode → collect_previous_policy → kyc_simulation → generate_quotes → select_quote → issue_policy → completed`

Session id is a cookie (`atr_policy_sid`) tied to the logged-in user and stored on `policy_booking_requests.session_id`. Refresh resumes the same booking.

## Honesty labels

| Capability | Live in this build | Label |
| --- | --- | --- |
| Vehicle lookup | EKO when keys + HMAC succeed; else fallback | Live Vahan Lookup **or** Demo Data — Fallback |
| KYC | Simulated only | Simulated Verification — Insurer-Tagged |
| Quotes | Internal rules | Demo Quotation — Illustrative Only |
| Policy PDF | Generated locally | Demo Policy Artifact — Not a Valid Insurance Document |

## Routers

Registered from `app/main.py` like every other feature:

- `routes_policy.py` — pages, CRM, summary fragment
- `routes_policy_chat.py` — start + message
- `routes_policy_vehicle.py` — GET lookup
- `routes_policy_kyc.py` — POST validate
- `routes_policy_quotes.py` — generate / select
- `routes_policy_issue.py` — issue + PDF download
- `routes_policy_settings.py` — encrypted settings + EKO test
