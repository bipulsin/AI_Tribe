#!/usr/bin/env bash
# Pre-warm Hugging Face / torchvision model caches for ML_MODE=live.
# Refuses to run unless ML_MODE=live — local stub-mode dev must not pull weights.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEIGHTS_DIR="${ROOT}/backend/app/ml_weights"

ML_MODE="${ML_MODE:-stub}"
if [[ "${ML_MODE}" != "live" ]]; then
  echo "error: scripts/download_models.sh requires ML_MODE=live" >&2
  echo "  Local development uses ML_MODE=stub (default) and must not download weights." >&2
  echo "  For a live-model smoke test, run inside a throwaway container, e.g.:" >&2
  echo "    docker run --rm --memory=2g --cpus=2 -e ML_MODE=live ..." >&2
  exit 1
fi

mkdir -p "${WEIGHTS_DIR}"
cd "${ROOT}"

if [[ -f "${ROOT}/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT}/venv/bin/activate"
fi

export PYTHONPATH="${ROOT}/backend${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME="${WEIGHTS_DIR}/huggingface"
export TORCH_HOME="${WEIGHTS_DIR}/torch"
export ML_MODE=live
mkdir -p "${HF_HOME}" "${TORCH_HOME}"

python - <<'PY'
from pathlib import Path

print("Downloading deepfake detector weights...")
from transformers import pipeline
pipeline(
    "image-classification",
    model="prithivMLmods/Deep-Fake-Detector-v2-Model",
    device=-1,
)
print("  deepfake: ok")

print("Downloading car damage classifier weights...")
pipeline(
    "image-classification",
    model="beingamit99/car_damage_detection",
    device=-1,
)
print("  damage: ok")

print("Downloading ImageNet ResNet50 weights for VMMR transfer...")
from torchvision.models import ResNet50_Weights, resnet50
resnet50(weights=ResNet50_Weights.DEFAULT)
print("  vmmr backbone: ok")

print("Model download complete.")
print(f"Caches under: {Path('backend/app/ml_weights').resolve()}")
PY
