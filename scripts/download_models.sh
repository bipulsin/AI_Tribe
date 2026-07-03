#!/usr/bin/env bash
# Download pretrained model weights into backend/app/ml_weights/.
# Populated fully in Milestone 5 when real ML services are wired.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEIGHTS_DIR="${ROOT}/backend/app/ml_weights"
mkdir -p "${WEIGHTS_DIR}"

echo "ML weight download script (Milestone 5)."
echo "Weights directory: ${WEIGHTS_DIR}"
echo "No models downloaded yet — stubs are active until Milestone 5."
