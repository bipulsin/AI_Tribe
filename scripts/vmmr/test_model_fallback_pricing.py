#!/usr/bin/env python3
"""Verify same-make catalog fallback disclosure for Mahindra XUV500."""

from __future__ import annotations

from app.core.database import SessionLocal
from app.models import Claim, ClaimImage, DamageDetection, Vehicle
from app.models.enums import ClaimStatus, DamageType, Severity
from app.services.parts.estimate_builder import build_estimate
from app.services.parts.parts_matcher import (
    PRICING_MODEL_FALLBACK,
    PRICING_NEEDS_CONFIRMATION,
    match_detections,
)


def main() -> None:
    db = SessionLocal()
    claim = None
    try:
        claim = Claim(
            claim_reference="TEST-XUV500-FALLBACK",
            status=ClaimStatus.estimate_ready,
            created_by=1,
        )
        db.add(claim)
        db.flush()

        image = ClaimImage(
            claim_id=claim.id,
            file_path="/tmp/xuv500_test.jpg",
            image_order=0,
        )
        db.add(image)
        db.flush()

        db.add(
            Vehicle(
                make="Mahindra",
                model="XUV500",
                identity_confirmed=False,
                pricing_basis=PRICING_NEEDS_CONFIRMATION,
                source_claim_id=claim.id,
            )
        )
        db.add(
            DamageDetection(
                claim_id=claim.id,
                claim_image_id=image.id,
                part_name="Front Bumper",
                damage_type=DamageType.dent,
                severity=Severity.moderate,
                repair_or_replace="replace",
                confidence_score=0.9,
            )
        )
        db.commit()

        context = match_detections(db, claim.id)
        built = build_estimate(db, claim.id)

        print("identity_pricing_basis", context.identity_pricing_basis)
        print("pricing_basis", context.pricing_basis)
        print("identified", context.identified_vehicle_label)
        print("catalogue", context.catalogue_vehicle_label)
        print("fallback_source_model", context.fallback_source_model)
        print("grand_total", built.grand_total)
        print("reason_summary", built.reason_summary[:500])

        assert context.identity_pricing_basis == PRICING_NEEDS_CONFIRMATION
        assert context.pricing_basis == PRICING_MODEL_FALLBACK
        assert context.fallback_source_model
        assert "XUV700" in (context.fallback_source_model or "")
        assert "XUV500" in context.identified_vehicle_label
        assert "XUV700" in built.reason_summary
        assert "XUV500" in built.reason_summary
        assert built.grand_total > 0
        print("OK: XUV500 → XUV700 same-make fallback disclosed with real total")
        print("OK: both identity needs_confirmation and model_fallback_priced active")
    finally:
        if claim is not None and claim.id:
            try:
                db.query(DamageDetection).filter(
                    DamageDetection.claim_id == claim.id
                ).delete()
                db.query(Vehicle).filter(Vehicle.source_claim_id == claim.id).delete()
                db.query(ClaimImage).filter(ClaimImage.claim_id == claim.id).delete()
                db.query(Claim).filter(Claim.id == claim.id).delete()
                db.commit()
            except Exception:
                db.rollback()
        db.close()


if __name__ == "__main__":
    main()
