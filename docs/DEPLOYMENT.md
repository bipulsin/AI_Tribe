# Deployment notes

## Status (as of Milestone 5 retrofit)

**This application has not yet been deployed to `paperclip-vm`.**

All work to date — including Milestone 5's live-model verification — has run on
the local laptop only. Live weights were exercised once on the host during that
milestone and have since been gated behind `ML_MODE=live` and removed from the
default local install path.

Deployment to `paperclip-vm` (isolated compose project, Caddy site for
`tribe.tradentical.com`, no disruption to existing Paperclip containers) is
Milestone 10 and must follow the read-first, change-second procedure in the
project brief.

## Local vs live ML

| Path | How | ML_MODE | Dependencies |
| --- | --- | --- | --- |
| Local laptop / default compose | `pip install -r backend/requirements.txt` or `docker compose -p ai_tribe up` | `stub` | No torch / transformers |
| Live models (paperclip-vm only) | `docker compose -p ai_tribe --profile ml up` (builds `Dockerfile.ml`) | `live` | `requirements-ml.txt` |

Never install `requirements-ml.txt` or run `scripts/download_models.sh` on a
developer laptop as the default workflow. If a live-model smoke test is
genuinely required during development, use a throwaway container:

```bash
docker run --rm --memory=2g --cpus=2 -e ML_MODE=live ...
```

## ARM image builds (Milestone 8 status)

**Not verified on the development laptop.** This Mac has no Docker daemon
(Docker Desktop / Colima not installed; Homebrew install of Colima was blocked
on a from-source Go bootstrap and was abandoned). Image builds must run where
Docker is available.

| Image | Dockerfile | Platform | Local laptop | paperclip-vm (native ARM) |
| --- | --- | --- | --- | --- |
| Base app (`ai_tribe_app`) | `Dockerfile` | `linux/arm64` | Attempt when Docker is present; should be fast (no torch) | Preferred if laptop cannot build |
| Live ML (`ai_tribe_app_ml`) | `Dockerfile.ml` | `linux/arm64` | **Do not chase** slow/failing cross-builds under QEMU for torch/transformers | **Build natively on the VM** during deployment |

Commands (run on a machine with Docker, ideally the VM for ML):

```bash
# Base stub image — expected to succeed quickly
docker buildx build --platform linux/arm64 -t ai_tribe_app:arm64 -f Dockerfile --load .
docker run --rm --platform linux/arm64 -e ML_MODE=stub ai_tribe_app:arm64 \
  python -c "from app.core.config import get_settings; print(get_settings().ml_mode)"

# Live ML image — build on paperclip-vm only (native ARM)
docker buildx build --platform linux/arm64 -t ai_tribe_app_ml:arm64 -f Dockerfile.ml --load .
```

Default compose (no ML profile) starts only `db` + `app` (stub):

```bash
docker compose -p ai_tribe up --build
# does NOT start app_ml unless: docker compose -p ai_tribe --profile ml up
```

## paperclip-vm access (confirmed from AI_Tribe workspace)

SSH works from this workspace with the same alias other Cursor workspaces use:

```bash
ssh paperclip echo connected
# → connected
```

`~/.ssh/config` block:

| Field | Value |
| --- | --- |
| Host | `paperclip` |
| HostName | `140.245.14.17` |
| User | `ubuntu` |
| IdentityFile | `~/.ssh/paperclip_key` |

## Read-only reconnaissance (2026-07-04) — no changes made

### Running containers (`docker ps`)

| Name | Image | Status | Ports | Up |
| --- | --- | --- | --- | --- |
| `caddy` | `caddy:2-alpine` | Up 3 weeks | `80`, `443` published | 3 weeks |
| `paperclip` | `stack-paperclip` | Up 7 weeks | `3100/tcp` (internal) | 7 weeks |
| `postgres` | `postgres:17-alpine` | Up 7 weeks (healthy) | `5432/tcp` (internal) | 7 weeks |
| `twcto-nginx-1` | `ghcr.io/bipulsin/twcto-nginx:latest` | Up 4 hours (healthy) | `8080→80` | 4 hours |
| `twcto-app-1` | `ghcr.io/bipulsin/twcto-app:latest` | Up 4 hours (healthy) | `8000/tcp` | 4 hours |
| `twcto-redis-1` | `redis:7-alpine` | Up 47 hours (healthy) | internal | 47 hours |
| `twcto-postgres-1` | `ghcr.io/bipulsin/twcto-postgres:latest` | Up 47 hours (healthy) | internal | 47 hours |

Paperclip stack and TWCTO stack are **separate** compose projects. AI Tribe must
be a third isolated project (`-p ai_tribe`), with its **own** Postgres — do not
reuse `postgres` or `twcto-postgres-1`.

### Networks (`docker network ls`)

| Name | Notes |
| --- | --- |
| `stack_web` | Paperclip + Caddy + Paperclip Postgres (compose project `stack`, network key `web`) |
| `twcto_default` | TWCTO stack |
| `bridge` / `host` / `none` | defaults |

Caddy, `paperclip`, and `postgres` are all on **`stack_web`**. Caddy reverse-proxies
to Paperclip by **container name** (`paperclip:3100`). TWCTO is reached via the
`stack_web` gateway host IP `172.18.0.1:8080` (published nginx port).

**AI Tribe deploy pattern:** attach `ai_tribe_app` to external network `stack_web`
(join, do not recreate), do **not** publish the app port on `0.0.0.0`, and let
Caddy proxy to `ai_tribe_app:8000` by name.

### Compose and Caddy locations

| Path | Role |
| --- | --- |
| `/opt/stack/docker-compose.yml` | Live Paperclip stack (caddy, postgres, paperclip) |
| `/opt/stack/caddy/Caddyfile` | Live Caddy config (mounted read-only into `caddy`) |
| `/opt/stack/.env` | Stack secrets (do not commit; do not modify for AI Tribe) |
| `/opt/stack/caddy/`, `paperclip-data/`, `paperclip-src/`, `postgres-data/` | Existing stack data |

Caddy site blocks today:

- `paperclip.tradentical.com` → `reverse_proxy paperclip:3100`
- `tradentical.com` / `www.tradentical.com` → static site
- `tradewithcto.com` / `www.tradewithcto.com` / `twcto.tradentical.com` / bare IP → TWCTO via `172.18.0.1:8080`
- Global ACME email: `tradentical@gmail.com`

**Planned AI Tribe block (not applied yet):**

```caddy
tribe.tradentical.com {
    reverse_proxy ai_tribe_app:8000
    encode gzip
}
```

Apply only after backing up the Caddyfile, `caddy validate`, then `caddy reload`
(never stop/start the shared stack).

### DNS check

| Source | Result |
| --- | --- |
| VM public IP (`curl -s ifconfig.me` on paperclip) | `140.245.14.17` |
| `dig +short tribe.tradentical.com` (laptop / 8.8.8.8) | `140.245.14.17` |
| `dig +short paperclip.tradentical.com` | `140.245.14.17` |

**DNS for `tribe.tradentical.com` already points at this VM.** Caddy should be able
to issue a TLS certificate for it once the site block is added (assuming port 80
remains reachable for ACME).

## Deployment steps (Milestone 10 — not executed yet)

1. ~~Inspect existing containers, networks, and Caddy config read-only~~ (done above).
2. Deploy as a fully separate compose project (`-p ai_tribe`) under e.g.
   `/opt/stack/ai_tribe/`, with its own Postgres volume and containers
   (`ai_tribe_app`, `ai_tribe_db`).
3. Build images **on the VM** (native ARM): base `Dockerfile` first; `Dockerfile.ml`
   only if live ML is required for the demo.
4. Attach `ai_tribe_app` to external network `stack_web`; do not publish app ports
   on `0.0.0.0`.
5. Backup `/opt/stack/caddy/Caddyfile`, add `tribe.tradentical.com` site block,
   `caddy validate`, then `caddy reload` (never stop/start shared stack).
6. Verify `https://paperclip.tradentical.com` and `https://tribe.tradentical.com`,
   and confirm every pre-existing container still has the same start time.
