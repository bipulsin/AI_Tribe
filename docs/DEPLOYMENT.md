# Deployment notes

## Status

**Live at https://tribe.tradentical.com** (deployed 2026-07-03/04 on paperclip-vm).

The live deployment runs **`ML_MODE=stub`** (no torch/transformers in the image).
Local development and Milestone 5 live-model verification on the laptop are
separate; host ML caches were removed after the ML_MODE retrofit.

## Local vs live ML

| Path | How | ML_MODE | Dependencies |
| --- | --- | --- | --- |
| Local laptop / default compose | `pip install -r backend/requirements.txt` or `docker compose -p ai_tribe up` | `stub` | No torch / transformers |
| Live models on paperclip-vm | See “Switching to ML_MODE=live” below | `live` | `requirements-ml.txt` |

Never install `requirements-ml.txt` or run `scripts/download_models.sh` on a
developer laptop as the default workflow.

## paperclip-vm access

```bash
ssh paperclip echo connected
# → connected
```

| Field | Value |
| --- | --- |
| Host | `paperclip` |
| HostName | `140.245.14.17` |
| User | `ubuntu` |
| IdentityFile | `~/.ssh/paperclip_key` |

## Live deployment topology

| Item | Value |
| --- | --- |
| Compose project | `ai_tribe` (`docker compose -p ai_tribe`) |
| Directory | `/opt/stack/ai_tribe/` |
| App container | `ai_tribe_app` |
| DB container | `ai_tribe_db` (Postgres 17, **isolated**) |
| App internal port | **8000** (not published on the host) |
| App networks | `ai_tribe_internal` (to reach `db`) **and** external `stack_web` (for Caddy) |
| DB networks | `internal` only — **not** on `stack_web` |
| ML mode | **`stub`** (`Dockerfile`, `requirements.txt` only) |
| Admin auth | `ADMIN_PASSWORD` **required** (`APP_ENV=production`); stored in `/opt/stack/ai_tribe/.env` (mode 600), not in git |

```
                    ┌──────────── stack_web (external) ────────────┐
                    │                                              │
  Internet ──► caddy ──► ai_tribe_app:8000                         │
                    │         │                                    │
                    │         │ internal network only              │
                    │         ▼                                    │
                    │    ai_tribe_db:5432                          │
                    │    (not on stack_web)                        │
                    └──────────────────────────────────────────────┘
```

Caddy does **not** publish the app port; it reaches `ai_tribe_app` by container
name on `stack_web`, same pattern as `paperclip:3100`.

### Caddy

| Item | Value |
| --- | --- |
| Live config | `/opt/stack/caddy/Caddyfile` |
| Backup | `/opt/stack/caddy/Caddyfile.bak.20260703` |
| Validate | `docker exec caddy caddy validate --config /etc/caddy/Caddyfile` |
| Reload | `docker exec caddy caddy reload --config /etc/caddy/Caddyfile` |

Site block added:

```caddy
tribe.tradentical.com {
    reverse_proxy ai_tribe_app:8000
    encode gzip
}
```

### Admin password (live)

- Local dev: still seeds `admin` / `admin` when `ADMIN_PASSWORD` is unset.
- Production (`APP_ENV=production`): **`ADMIN_PASSWORD` is required**; boot fails without it.
- On first boot with `ADMIN_PASSWORD` set, if the admin user still has the seeded
  default password, it is rotated automatically.
- Live secret lives only in `/opt/stack/ai_tribe/.env` (and the compose env).
  Do not commit it.

### Redeploy / update code

```bash
ssh paperclip
cd /opt/stack/ai_tribe
git pull origin main
docker compose -p ai_tribe up -d --build
```

### Switching to ML_MODE=live (when ready)

Build and run the ML image **on the VM** (native ARM), not under laptop emulation:

```bash
cd /opt/stack/ai_tribe
# Ensure ADMIN_PASSWORD remains set in .env / compose
docker compose -p ai_tribe --profile ml up -d --build app_ml
# Then point Caddy at ai_tribe_app_ml:8000 (or replace the app service with Dockerfile.ml)
```

Today the live site uses the stub `app` service only. Bringing up `app_ml` requires
joining it to `stack_web` and updating the Caddy upstream if the container name changes.

## Co-located stacks (must remain untouched)

| Name | Role |
| --- | --- |
| `caddy`, `paperclip`, `postgres` | Paperclip stack on `stack_web` |
| `twcto-*` | Separate TWCTO compose project |

Never restart `/opt/stack/docker-compose.yml` for AI Tribe changes. Only
`caddy reload` and `docker compose -p ai_tribe ...`.

## DNS

| Check | Result |
| --- | --- |
| VM public IP | `140.245.14.17` |
| `tribe.tradentical.com` | `140.245.14.17` |
| `paperclip.tradentical.com` | `140.245.14.17` |

## ARM image builds

| Image | Dockerfile | Where to build |
| --- | --- | --- |
| Stub app | `Dockerfile` | Built natively on paperclip-vm (done) |
| Live ML | `Dockerfile.ml` | Build natively on paperclip-vm when enabling live ML |

## Rollback (if needed)

```bash
# Restore Caddy
cp /opt/stack/caddy/Caddyfile.bak.20260703 /opt/stack/caddy/Caddyfile
docker exec caddy caddy validate --config /etc/caddy/Caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile

# Remove AI Tribe stack (does not touch Paperclip/TWCTO)
cd /opt/stack/ai_tribe
docker compose -p ai_tribe down
```
