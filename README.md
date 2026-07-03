# AI Tribe: Motor Damage Assessment

Proof-of-concept web application for an insurance AI lab. A user submits one to ten photos (plus an optional short video) of a damaged vehicle; a visible, staged AI pipeline screens authenticity, identifies the vehicle, maps damage to parts, grades severity, and produces a survey estimate sheet with part-level pricing.

This is a **lab prototype for demonstrations**, not a production insurer deployment.

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

## Default credentials (change before any real use)

On first seed the app creates:

- **username:** `admin`
- **password:** `admin`

This is a lab default only. The app prints a console warning on every boot while this credential remains active. **Change it before anything resembling production use.**

## Local development

### Prerequisites

- **Python 3.11 or 3.12** for the pretrained ML stack (`torch` / `transformers` wheels). Python 3.13 works for the web app and algorithmic forensics, but may not have PyTorch wheels on all platforms — ML stages then pass with an explicit warning and provisional results.
- PostgreSQL 15+ (Docker Compose ships Postgres 17; a local Homebrew install of 15+ is fine for development)
- `pip` / `venv`
- Docker (optional for local app runs; required for the containerised deployment path)

Pretrained weights (deepfake detector, car-damage classifier, ImageNet ResNet50 for VMMR transfer) are pulled by:

```bash
./scripts/download_models.sh
```

Caches land under `backend/app/ml_weights/` (gitignored).

### One-command spin-up (Docker)

```bash
cp .env.example .env
docker compose -p ai_tribe up --build
```

App: http://localhost:8000  
Login: `admin` / `admin`

The compose project name is `ai_tribe` so container and network names never collide with other stacks.

### Manual (no Docker for the app)

```bash
# 1. Start Postgres (Docker only for the DB is fine)
docker compose -p ai_tribe up -d db

# Or with a local Postgres 17 install, create role/db:
#   createuser ai_tribe -P   # password: ai_tribe
#   createdb -O ai_tribe ai_tribe

cp .env.example .env

# Prefer Python 3.11 or 3.12 so torch/transformers wheels install cleanly.
python3.12 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
./scripts/download_models.sh

cd backend
alembic upgrade head
cd ..
python scripts/seed_db.py

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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
- `docs/ML_Training_Playbook_and_Pretrained_Models.md` — pretrained model choices and training playbook (used from Milestone 5)
- `docs/DEPLOYMENT.md` — paperclip-vm deployment runbook (added with Milestone 10)

## ARM / container notes

Target VM is Oracle Cloud ARM Ampere A1 (`linux/arm64`). Build with:

```bash
docker buildx build --platform linux/arm64 -t ai_tribe:latest .
```

If `mmdet`/`mmcv` (CarDD) prove too heavy on ARM, the containerised deployment falls back to `transformers`-based pretrained options documented in the ML playbook. That decision will be recorded here when Milestone 8 lands.

## Milestone status

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Scaffold, FastAPI, Postgres, Alembic | done |
| 2 | Auth + video-background login | done |
| 3 | Claim submission + storage | done |
| 4 | SSE pipeline stage tracker (stubs) | done |
| 5 | Real forensic / ML services | done |
| 6 | Parts matching + estimate view | pending |
| 7 | AX / minimalist UI polish | pending |
| 8 | Dockerize (multi-stage, arm64) | pending |
| 9 | Push to GitHub `main` | pending |
| 10 | Deploy to `paperclip-vm` | pending |
