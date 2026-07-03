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

## paperclip-vm (Milestone 10 — not done yet)

When deployment happens:

1. Inspect existing containers, networks, and Caddy config read-only first.
2. Deploy as a fully separate compose project (`-p ai_tribe`) under e.g.
   `/opt/stack/ai_tribe/`.
3. Use the `ml` profile (or equivalent) only on the VM if live inference is
   required for the demo; keep resource limits (`mem_limit` / `cpus`) in place.
4. Join the existing Caddy Docker network; do not publish app ports on `0.0.0.0`.
5. Add `tribe.tradentical.com` via `caddy reload` after validating the Caddyfile.
6. Verify `paperclip.tradentical.com` and every pre-existing container remain
   undisturbed.
