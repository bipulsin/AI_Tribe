# AI Tribe: Motor Damage Assessment

Proof-of-concept web application for an insurance AI lab. A user submits one to ten photos (plus an optional short video) of a damaged vehicle; a visible, staged AI pipeline screens authenticity, identifies the vehicle, maps damage to parts, grades severity, and produces a survey estimate sheet with part-level pricing.

This is a **lab prototype for demonstrations**, not a production insurer deployment.

## Deployment status

**Not deployed to `paperclip-vm` yet.** All work to date, including Milestone 5 live-model verification, has run on the local laptop only. See `docs/DEPLOYMENT.md`.

## Hard technology constraints

Do not deviate from these:

| Layer | Choice |
| --- | --- |
| Backend | Python 3.11+ and **FastAPI** only |
| Database | **PostgreSQL** via SQLAlchemy 2.x + Alembic |
| Frontend | Server-rendered Jinja2 + **HTMX** + **Alpine.js** + Tailwind (CDN/CLI). No React/Vue/Next/bundler |
| Jobs / live progress | FastAPI `BackgroundTasks` / asyncio + **Server-Sent Events** |
| Object storage | Local filesystem under `data/uploads/` behind a swappable storage interface |
| Packages | `pip` + pinned `requirements.txt` in a virtualenv |
| Deployment | Docker, co-located on `paperclip-vm` without touching existing containers |

No authentication-as-a-service, no cloud AI APIs, no paid third-party services. Everything runs locally.

## ML_MODE: stub vs live

| Mode | Default | Behaviour |
| --- | --- | --- |
| `stub` | **yes** | Deterministic fixture responses for deepfake / damage / VMMR. **Never imports torch or transformers.** |
| `live` | no | Loads pretrained HF / torchvision models. Requires `requirements-ml.txt`. |

Local development installs **`backend/requirements.txt` only** and runs with `ML_MODE=stub`. Live inference is for the paperclip-vm `ml` compose profile (or a throwaway container), not day-to-day laptop work.

## Default credentials (change before any real use)

On first seed the app creates:

- **username:** `admin`
- **password:** `admin`

This is a lab default only. The app prints a console warning on every boot while this credential remains active. **Change it before anything resembling production use.**

## Local development

### Prerequisites

- Python 3.11+ (3.13 is fine for stub mode)
- PostgreSQL 15+ (Docker Compose ships Postgres 17; a local Homebrew install of 15+ is fine for development)
- `pip` / `venv`
- Docker (optional for local app runs; required for the containerised deployment path)

### One-command spin-up (Docker, stub mode)

```bash
cp .env.example .env
docker compose -p ai_tribe up --build
```

App: http://localhost:8000  
Login: `admin` / `admin`  
`ML_MODE=stub` — no ML packages in the image.

The compose project name is `ai_tribe` so container and network names never collide with other stacks.

Live-model container (paperclip-vm path only; resource-capped):

```bash
docker compose -p ai_tribe --profile ml up --build app_ml
# listens on localhost:8001 when used locally
```

### Manual (no Docker for the app)

```bash
# 1. Start Postgres (Docker only for the DB is fine)
docker compose -p ai_tribe up -d db

# Or with a local Postgres install, create role/db:
#   createuser ai_tribe -P   # password: ai_tribe
#   createdb -O ai_tribe ai_tribe

cp .env.example .env
# ML_MODE=stub is the default in .env.example

python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
# Do NOT install requirements-ml.txt for local dev.
# Do NOT run scripts/download_models.sh unless ML_MODE=live (it will refuse otherwise).

cd backend
alembic upgrade head
cd ..
python scripts/seed_db.py

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Live-model smoke test (throwaway container only)

If a live-model check is genuinely needed during development, run it inside a
memory-capped throwaway container — never install torch on the host:

```bash
docker run --rm --memory=2g --cpus=2 -e ML_MODE=live ...
```

`scripts/download_models.sh` requires `ML_MODE=live` and exits otherwise.

### Background video asset

Login page background video lives at:

```
frontend/static/video/login_bg.mp4
```

Replace this file to change the looping background. The current asset was sourced from the lab's `twcto.mp4` clip.

## Project layout

See the repository tree under `backend/`, `frontend/`, `data/`, and `scripts/`. Key entry points:

- `backend/app/main.py` — FastAPI application
- `backend/app/services/pipeline_orchestrator.py` — staged AI pipeline
- `backend/app/core/events.py` — in-memory SSE pub/sub bus
- `backend/app/services/storage.py` — filesystem storage interface (S3-swappable)
- `backend/requirements.txt` — default / stub-mode dependencies
- `backend/requirements-ml.txt` — live-inference extras (torch, transformers, …)
- `docs/ML_Training_Playbook_and_Pretrained_Models.md` — pretrained model choices and training playbook
- `docs/DEPLOYMENT.md` — paperclip-vm deployment notes (not yet executed)

## ARM / container notes

Target VM is Oracle Cloud ARM Ampere A1 (`linux/arm64`). Default image:

```bash
docker buildx build --platform linux/arm64 -t ai_tribe:latest .
```

Live-model image (`Dockerfile.ml`) is only built via `--profile ml`. If `mmdet`/`mmcv` (CarDD) prove too heavy on ARM, the live path uses the `transformers`-based options from the ML playbook.

## Milestone status

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Scaffold, FastAPI, Postgres, Alembic | done |
| 2 | Auth + video-background login | done |
| 3 | Claim submission + storage | done |
| 4 | SSE pipeline stage tracker (stubs) | done |
| 5 | Real forensic / ML services (gated by `ML_MODE`) | done |
| 6 | Parts matching + estimate view | done |
| 7 | AX / minimalist UI polish | pending |
| 8 | Dockerize (multi-stage, arm64) | pending |
| 9 | Push to GitHub `main` | pending |
| 10 | Deploy to `paperclip-vm` | pending |
