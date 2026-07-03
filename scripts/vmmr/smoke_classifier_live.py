#!/usr/bin/env python3
"""Exercise live VMMR classifier (margin gate + ImageNet fallback)."""

from __future__ import annotations

from pathlib import Path

from app.services.vmmr.vmmr_classifier import (
    CHECKPOINT_PATH,
    PROVISIONAL_ONLY_MODELS,
    TRAINED_CATALOG_MODELS,
    classify_image,
)


def main() -> None:
    print("checkpoint", CHECKPOINT_PATH, CHECKPOINT_PATH.exists())
    print("trained", sorted(TRAINED_CATALOG_MODELS))
    print("provisional_only", sorted(PROVISIONAL_ONLY_MODELS))

    cases = [
        ("city_hi", Path("/mnt/ml-scratch/vmmr_data/crops/Honda_City/test_5802_0.jpg")),
        (
            "baleno_low_margin",
            Path("/mnt/ml-scratch/vmmr_data/crops/Maruti_Baleno/train_3830_2.jpg"),
        ),
        ("swift_hi", Path("/mnt/ml-scratch/vmmr_data/crops/Maruti_Swift/train_415_3.jpg")),
        (
            "city_mis_as_swift_high_margin",
            Path("/mnt/ml-scratch/vmmr_data/crops/Honda_City/test_5091_3.jpg"),
        ),
    ]
    for label, path in cases:
        result = classify_image(path)
        print(
            label,
            {
                "make": result.make,
                "model": result.model,
                "confidence": round(result.confidence, 4),
                "margin": round(result.margin, 4),
                "identity_confirmed": result.identity_confirmed,
                "detail": result.detail[:200],
            },
        )


if __name__ == "__main__":
    main()
