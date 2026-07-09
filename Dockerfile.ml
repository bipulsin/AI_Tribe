# Live-inference image (ML_MODE=live). Built only via the compose `ml` profile
# or paperclip-vm deployment — never the default local `docker compose up`.

FROM python:3.11-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-ml.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements-ml.txt

FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    ML_MODE=live \
    HF_HOME=/app/backend/app/ml_weights/huggingface \
    TORCH_HOME=/app/backend/app/ml_weights/torch

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY data/parts_seed/ /app/data/parts_seed/
COPY scripts/ /app/scripts/

RUN mkdir -p /app/data/uploads \
        /app/data/profile_photos \
        /app/backend/app/ml_weights/huggingface \
        /app/backend/app/ml_weights/torch \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "cd /app/backend && alembic upgrade head && python -m app.db.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
