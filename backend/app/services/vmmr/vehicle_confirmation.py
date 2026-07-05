"""Manual vehicle identification pause, resume, and correction-queue logging."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Claim, ClaimImage, DamageDetection, Vehicle, VmmrCorrectionQueue
from app.services.parts.damage_aggregation import assess_extensive_damage
from app.services.vmmr.vmmr_classifier import (
    PRICING_CONFIRMED,
    PRICING_NEEDS_CONFIRMATION,
    PRICING_PROVISIONAL,
)

logger = logging.getLogger("ai_tribe.vmmr.confirm")

IDENTITY_SOURCE_VMMR = "vmmr"
IDENTITY_SOURCE_MANUAL = "manual_entry"

VMMR_CORRECTIONS_ROOT = Path(
    os.environ.get("VMMR_CORRECTIONS_ROOT", "/mnt/ml-scratch/vmmr_corrections")
)

PAUSE_STAGE_KEY = "vehicle_confirmation"
PAUSE_STAGE_LABEL = "Confirm vehicle make and model"
PAUSE_MESSAGE = (
    "This vehicle shows severe damage and could not be reliably identified. "
    "Please confirm the make and model to continue."
)


def vmmr_identity_unreliable(vehicle: Vehicle | None) -> bool:
    if vehicle is None:
        return True
    if vehicle.identity_confirmed:
        return False
    if vehicle.pricing_basis in {PRICING_PROVISIONAL, PRICING_NEEDS_CONFIRMATION}:
        return True
    return False


def should_pause_for_vehicle_confirmation(
    db: Session, claim_id: int
) -> tuple[bool, str]:
    """Evaluate after severity_grading; before catalogue pricing stages."""
    vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))
    detections = list(
        db.scalars(
            select(DamageDetection).where(DamageDetection.claim_id == claim_id)
        ).all()
    )
    extensive, extensive_reason = assess_extensive_damage(detections)
    unreliable = vmmr_identity_unreliable(vehicle)

    if extensive and unreliable:
        return True, f"{PAUSE_MESSAGE} ({extensive_reason})"
    if extensive:
        return True, f"{PAUSE_MESSAGE} ({extensive_reason})"
    if unreliable:
        return True, PAUSE_MESSAGE
    return False, ""


def _copy_images_to_scratch(claim_id: int, image_paths: list[str]) -> list[str]:
    """Copy claim images into /mnt/ml-scratch for future retrain assembly."""
    dest_root = VMMR_CORRECTIONS_ROOT / str(claim_id)
    dest_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    upload_root = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
    if not upload_root.is_absolute():
        from app.core.config import REPO_ROOT

        upload_root = REPO_ROOT / upload_root

    for rel_path in image_paths:
        src = upload_root / rel_path
        if not src.exists():
            logger.warning("Correction queue: missing image %s", src)
            continue
        dest = dest_root / Path(rel_path).name
        shutil.copy2(src, dest)
        copied.append(str(dest))
    return copied


def log_manual_correction(
    db: Session,
    *,
    claim_id: int,
    confirmed_make: str,
    confirmed_model: str,
    submitted_by: int,
) -> VmmrCorrectionQueue:
    images = db.scalars(
        select(ClaimImage.file_path)
        .where(ClaimImage.claim_id == claim_id)
        .order_by(ClaimImage.image_order.asc())
    ).all()
    image_paths = list(images)
    scratch_paths: list[str] = []
    try:
        if VMMR_CORRECTIONS_ROOT.parent.exists():
            scratch_paths = _copy_images_to_scratch(claim_id, image_paths)
        else:
            logger.warning(
                "VMMR corrections root %s unavailable; logging paths only",
                VMMR_CORRECTIONS_ROOT,
            )
    except OSError as exc:
        logger.exception("Failed to copy correction images to ml-scratch: %s", exc)

    row = VmmrCorrectionQueue(
        claim_id=claim_id,
        image_paths=image_paths,
        scratch_image_paths=scratch_paths or None,
        confirmed_make=confirmed_make.strip(),
        confirmed_model=confirmed_model.strip(),
        submitted_by=submitted_by,
    )
    db.add(row)
    return row


def apply_manual_vehicle_identity(
    db: Session,
    *,
    claim_id: int,
    make: str,
    model: str,
    submitted_by: int,
) -> Vehicle:
    vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))
    if vehicle is None:
        vehicle = Vehicle(source_claim_id=claim_id)
        db.add(vehicle)

    vehicle.make = make.strip()
    vehicle.model = model.strip()
    vehicle.identity_confirmed = True
    vehicle.pricing_basis = PRICING_CONFIRMED
    vehicle.identity_source = IDENTITY_SOURCE_MANUAL

    log_manual_correction(
        db,
        claim_id=claim_id,
        confirmed_make=make,
        confirmed_model=model,
        submitted_by=submitted_by,
    )
    db.flush()
    return vehicle


def correction_queue_summary(db: Session) -> dict:
    rows = db.execute(
        select(
            VmmrCorrectionQueue.confirmed_make,
            VmmrCorrectionQueue.confirmed_model,
            func.count().label("count"),
        )
        .where(VmmrCorrectionQueue.used_in_training.is_(False))
        .group_by(
            VmmrCorrectionQueue.confirmed_make,
            VmmrCorrectionQueue.confirmed_model,
        )
        .order_by(func.count().desc())
    ).all()
    total = db.scalar(select(func.count()).select_from(VmmrCorrectionQueue)) or 0
    pending = db.scalar(
        select(func.count())
        .select_from(VmmrCorrectionQueue)
        .where(VmmrCorrectionQueue.used_in_training.is_(False))
    ) or 0
    by_make_model = [
        {"make": make, "model": model, "count": count} for make, model, count in rows
    ]
    summary = {
        "total_corrections": total,
        "pending_training": pending,
        "by_make_model": by_make_model,
        "scratch_root": str(VMMR_CORRECTIONS_ROOT),
    }
    logger.info("VMMR correction queue: %s", summary)
    return summary


def catalog_makes_models(db: Session) -> list[dict[str, list[str]]]:
    from app.models import PartsCatalog

    makes = db.scalars(
        select(PartsCatalog.make).distinct().order_by(PartsCatalog.make.asc())
    ).all()
    result: list[dict[str, list[str]]] = []
    for make in makes:
        if not make:
            continue
        models = db.scalars(
            select(PartsCatalog.model)
            .where(PartsCatalog.make == make)
            .distinct()
            .order_by(PartsCatalog.model.asc())
        ).all()
        result.append({"make": make, "models": [m for m in models if m]})
    return result
