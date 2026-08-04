# Usability Report (admin)

Admin-only observability for **who used AI Tribe, on which UTC days, and which
feature areas** they touched. Live UI: `/admin/usage-report` (linked from the
Admin panel → **Usability Report**).

## What is tracked

Table: `usage_events`

| Column | Notes |
| --- | --- |
| `user_id` | Session user when known; may be null for rare anonymous hits |
| `username_snapshot` | Username/email at event time |
| `event_type` | e.g. `login`, `chat_message`, `submit_claim`, `damage_assessment`, `estimate_view`, `api_marketplace_call`, `vmmr_labeling`, `admin_action` |
| `feature_area` | `chat` \| `form_ui` \| `api_marketplace` \| `lab_vmmr` \| `admin` \| `auth` \| `settings` \| `other` |
| `endpoint_or_route` | `METHOD path` only — never request bodies or uploads |
| `occurred_at` | UTC |
| `session_id` / `ip_address` | Optional |
| `metadata` | Small JSONB (e.g. `claim_id`) — no API keys / PII blobs |

Logged by HTTP middleware in `main.py` after each successful/failed response for
interesting routes. Skipped: `/static/`, `/uploads/`, `/health`, OpenAPI, SSE
pipeline streams, suggest endpoints, OPTIONS/HEAD.

**Not logged:** BYOK key material, model inference internals, file contents.

External partner API calls are also classified under `api_marketplace` when they
hit `/api/v1/external/*` (session may be absent; user_id may be null unless a
session cookie is also present).

## Admin API

```http
GET /api/admin/usage-report?start=2026-07-01&end=2026-07-31&user_id=
GET /api/admin/usage-report/detail?user_id=3&day=2026-07-15
```

Requires an admin session (same `require_admin` gate as other `/api/admin/*`
routes).

## Manual psql queries

```sql
-- Active users by day (last 14 days)
SELECT
  (occurred_at AT TIME ZONE 'UTC')::date AS day,
  user_id,
  username_snapshot,
  count(*) AS events,
  array_agg(DISTINCT feature_area ORDER BY feature_area) AS areas
FROM usage_events
WHERE occurred_at >= now() - interval '14 days'
  AND user_id IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2;

-- Feature mix for one user
SELECT feature_area, event_type, count(*)
FROM usage_events
WHERE user_id = 1
  AND occurred_at >= date_trunc('day', now() AT TIME ZONE 'UTC') - interval '7 days'
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Top routes today
SELECT endpoint_or_route, count(*)
FROM usage_events
WHERE occurred_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
GROUP BY 1
ORDER BY 2 DESC
LIMIT 30;
```

On paperclip:

```bash
docker exec -it ai_tribe_db psql -U ai_tribe -d ai_tribe
```
