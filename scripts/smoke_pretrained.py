#!/usr/bin/env python3
"""Smoke-test pretrained deepfake and damage models (ML_MODE=live only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("ML_MODE", "live")
os.environ.setdefault("HF_HOME", str(ROOT / "backend" / "app" / "ml_weights" / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(ROOT / "backend" / "app" / "ml_weights" / "torch"))

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


def main() -> None:
    settings = get_settings()
    if not settings.ml_live:
        raise SystemExit("smoke_pretrained.py requires ML_MODE=live")

    samples = sorted((ROOT / "data" / "sample_claims").glob("*.png"))[:3]
    if len(samples) < 2:
        raise SystemExit("Need at least 2 sample images in data/sample_claims/")

    from app.services.forensics import deepfake_detector
    from app.services.damage import damage_segmenter

    print("=== Deepfake detector ===")
    deepfake_results = []
    for path in samples:
        result = deepfake_detector.classify_image(path)
        deepfake_results.append(result)
        print(f"  {path.name}: label={result.label!r} score={result.score:.4f} "
              f"is_fake={result.is_fake} detail={result.detail!r} "
              f"model_available={result.model_available}")
        if not result.model_available:
            raise SystemExit("Deepfake model did not load")

    print("=== Damage classifier ===")
    damage_results = []
    for path in samples:
        result = damage_segmenter.classify_image(path)
        damage_results.append(result)
        print(f"  {path.name}: label={result.label!r} part={result.part_name!r} "
              f"type={result.damage_type.value} conf={result.confidence:.4f} "
              f"detail={result.detail!r} model_available={result.model_available}")
        if not result.model_available:
            raise SystemExit("Damage model did not load")

    # Fixture-shaped responses are constant; live models should vary across images
    # or at least not match the exact stub strings.
    stub_deepfake = "Image cleared (realism 92%, deepfake 8%)."
    stub_damage = "Front Door: scratch (85%)."
    if all(r.detail == stub_deepfake for r in deepfake_results):
        raise SystemExit("Deepfake outputs look like stub fixtures")
    if all(r.detail == stub_damage for r in damage_results):
        raise SystemExit("Damage outputs look like stub fixtures")

    scores = [r.score for r in deepfake_results]
    confs = [r.confidence for r in damage_results]
    print("=== Variation check ===")
    print(f"  deepfake scores: {scores}")
    print(f"  damage confidences: {confs}")
    print("SMOKE OK")


if __name__ == "__main__":
    main()
