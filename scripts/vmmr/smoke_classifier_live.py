#!/usr/bin/env python3
"""Exercise live VMMR classifier (margin gate + reliability tier)."""

from __future__ import annotations

from pathlib import Path

from app.services.vmmr.vmmr_classifier import (
    CHECKPOINT_PATH,
    CLASS_RELIABILITY_TIER,
    PROVISIONAL_ONLY_MODELS,
    TRAINED_CATALOG_MODELS,
    classify_image,
)


def _summary(result) -> dict:
    return {
        "make": result.make,
        "model": result.model,
        "label": result.label,
        "confidence": round(result.confidence, 4),
        "margin": round(result.margin, 4),
        "reliability_tier": result.reliability_tier,
        "identity_confirmed": result.identity_confirmed,
        "pricing_basis": result.pricing_basis,
        "detail": result.detail[:220],
    }


def main() -> None:
    print("checkpoint", CHECKPOINT_PATH, CHECKPOINT_PATH.exists())
    print("tiers", CLASS_RELIABILITY_TIER)
    print("trained", sorted(TRAINED_CATALOG_MODELS))
    print("provisional_only", sorted(PROVISIONAL_ONLY_MODELS))

    cases = [
        ("city_hi_true_city", Path("/mnt/ml-scratch/vmmr_data/crops/Honda_City/test_5802_0.jpg")),
        (
            "baleno_low_margin",
            Path("/mnt/ml-scratch/vmmr_data/crops/Maruti_Baleno/train_3830_2.jpg"),
        ),
        ("swift_hi", Path("/mnt/ml-scratch/vmmr_data/crops/Maruti_Swift/train_415_3.jpg")),
        # Known City→Swift confusion (margin was ~0.84, Swift is reliable-tier).
        (
            "city_mislabelled_as_swift",
            Path("/mnt/ml-scratch/vmmr_data/crops/Honda_City/test_5091_3.jpg"),
        ),
    ]
    for label, path in cases:
        result = classify_image(path)
        print(label, _summary(result))

    # Explicit assertion notes for the City/Swift residual case.
    miss = classify_image(
        Path("/mnt/ml-scratch/vmmr_data/crops/Honda_City/test_5091_3.jpg")
    )
    print("\n=== City/Swift residual case ===")
    print(_summary(miss))
    if miss.identity_confirmed and miss.label == "Maruti_Swift":
        print(
            "KNOWN_MISS: still auto-finalizes as Maruti Swift "
            f"(tier={miss.reliability_tier}, pricing_basis={miss.pricing_basis}). "
            "Tier gating does not fix reliable-tier reverse confusion."
        )
    elif miss.pricing_basis == "needs_confirmation":
        print("CHANGED: now needs_confirmation (unexpected for Swift prediction).")
    else:
        print(f"OTHER: pricing_basis={miss.pricing_basis}")


if __name__ == "__main__":
    main()
