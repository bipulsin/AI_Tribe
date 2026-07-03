"""Pipeline orchestrator — real forensic/ML stages (Milestone 5).

Each stage writes a pipeline_events row at start and end, and publishes onto
the in-memory SSE bus so the processing UI updates live.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.events import event_bus
from app.models import (
    Claim,
    ClaimImage,
    DamageDetection,
    FraudSignal,
    PipelineEvent,
    Vehicle,
)
from app.models.enums import (
    AuthenticityVerdict,
    ClaimStatus,
    PipelineEventStatus,
)
from app.services.damage import damage_segmenter, severity as severity_service
from app.services.forensics import (
    deepfake_detector,
    ela,
    metadata_forensics,
    phash_reuse,
    quality_gate,
)
from app.services.fraud import risk_scorer, rules_engine
from app.services.image_utils import claim_image_paths
from app.services.vmmr import vmmr_classifier

logger = logging.getLogger("ai_tribe.pipeline")

PIPELINE_STAGES: list[tuple[str, str]] = [
    ("intake", "Image rendering"),
    ("quality_gate", "Checking image quality"),
    ("deepfake_check", "Deepfake identification in process"),
    ("vehicle_forensics", "Vehicle forensics in process"),
    ("duplicate_check", "Checking for reused images"),
    ("vehicle_id", "Identifying make and model"),
    ("consistency_check", "Confirming all images match the same vehicle"),
    ("damage_detection", "Mapping damage to vehicle parts"),
    ("severity_grading", "Grading damage severity"),
    ("fraud_scoring", "Running fraud intelligence checks"),
    ("parts_matching", "Matching parts to pricing catalogue"),
    ("estimate_ready", "Survey estimate ready"),
]

HALTING_STAGES = {
    "quality_gate",
    "deepfake_check",
    "vehicle_forensics",
    "duplicate_check",
}

RESOLVED_LABELS: dict[str, dict[str, str]] = {
    "deepfake_check": {
        "passed": "Image cleared",
        "failed": "Deepfake identified",
    },
    "vehicle_forensics": {
        "passed": "Forensic check passed",
        "failed": "Forensic anomaly detected",
    },
}

_running_claims: set[int] = set()
_running_lock = asyncio.Lock()


@dataclass
class StageResult:
    status: PipelineEventStatus
    detail: str | None = None
    halt_message: str | None = None


StageFn = Callable[[Session, Claim], Awaitable[StageResult]]


def _paths(db: Session, claim: Claim):
    return claim_image_paths(db, claim)


async def stage_intake(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    if not images:
        return StageResult(
            status=PipelineEventStatus.failed,
            detail="No images were available to render.",
            halt_message="No claim images were found. Please resubmit the photos.",
        )
    return StageResult(
        status=PipelineEventStatus.passed,
        detail=f"{len(images)} image(s) ready for assessment.",
    )


async def stage_quality_gate(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    paths = [path for _, path in images]
    passed, detail, results = await asyncio.to_thread(quality_gate.check_claim_images, paths)

    for (image_row, _), result in zip(images, results):
        image_row.quality_gate_passed = result.passed
    db.commit()

    if not passed:
        return StageResult(
            status=PipelineEventStatus.failed,
            detail=detail,
            halt_message=(
                f"{detail} Please retake the photo in better light and focus, "
                "or send the claim for manual review."
            ),
        )
    return StageResult(status=PipelineEventStatus.passed, detail=detail)


async def stage_deepfake_check(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    paths = [path for _, path in images]
    passed, detail, results = await asyncio.to_thread(
        deepfake_detector.classify_paths, paths
    )

    for (image_row, _), result in zip(images, results):
        if result.is_fake:
            image_row.authenticity_verdict = AuthenticityVerdict.flagged
            image_row.authenticity_reason = result.detail
        elif result.model_available:
            image_row.authenticity_verdict = AuthenticityVerdict.clear
            image_row.authenticity_reason = result.detail
        else:
            image_row.authenticity_verdict = AuthenticityVerdict.pending
            image_row.authenticity_reason = result.detail
    db.commit()

    if not passed:
        return StageResult(
            status=PipelineEventStatus.failed,
            detail=detail,
            halt_message=(
                f"{detail} The submission has been paused so a surveyor can "
                "review authenticity before any estimate is produced."
            ),
        )

    status = (
        PipelineEventStatus.warning
        if any(not r.model_available for r in results)
        else PipelineEventStatus.passed
    )
    return StageResult(status=status, detail=detail)


async def stage_vehicle_forensics(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    paths = [path for _, path in images]

    ela_ok, ela_detail = await asyncio.to_thread(ela.run_ela_on_paths, paths)
    meta_ok, meta_detail = await asyncio.to_thread(
        metadata_forensics.inspect_paths, paths
    )

    if not ela_ok or not meta_ok:
        detail = ela_detail if not ela_ok else meta_detail
        for image_row, _ in images:
            image_row.authenticity_verdict = AuthenticityVerdict.flagged
            image_row.authenticity_reason = detail
        db.commit()
        return StageResult(
            status=PipelineEventStatus.failed,
            detail=detail,
            halt_message=(
                f"{detail} Forensic checks found something unusual. "
                "A surveyor should review this claim before it continues."
            ),
        )

    return StageResult(
        status=PipelineEventStatus.passed,
        detail=f"{ela_detail} {meta_detail}",
    )


async def stage_duplicate_check(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    if not images:
        return StageResult(
            status=PipelineEventStatus.passed,
            detail="No images for duplicate checks.",
        )

    # Hash in a worker thread; query Postgres on this thread only.
    for image_row, path in images:
        phash = await asyncio.to_thread(phash_reuse.compute_phash, path)
        image_row.phash = phash
        result = phash_reuse.check_reuse(
            db, claim_id=claim.id, image_id=image_row.id, path=path
        )
        # check_reuse recomputes phash; keep the stored value explicit.
        image_row.phash = result.phash
        if result.reused:
            db.commit()
            return StageResult(
                status=PipelineEventStatus.failed,
                detail=result.detail,
                halt_message=(
                    f"{result.detail} Reused photos are a common fraud signal, so this "
                    "claim is paused for manual review."
                ),
            )

    db.commit()
    return StageResult(
        status=PipelineEventStatus.passed,
        detail="No reused images found in prior claims.",
    )


async def stage_vehicle_id(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    paths = [path for _, path in images]
    result = await asyncio.to_thread(vmmr_classifier.classify_claim_images, paths)

    identity_confirmed = (
        result.model_available
        and result.label not in {"stub_fixture", "unavailable", "none"}
        and bool(result.make)
        and result.make != "Unknown"
        and bool(result.model)
        and result.model != "Unknown"
    )

    existing = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim.id))
    if existing:
        existing.make = result.make
        existing.model = result.model
        existing.year = result.year
        existing.identity_confirmed = identity_confirmed
    else:
        db.add(
            Vehicle(
                make=result.make,
                model=result.model,
                year=result.year,
                identity_confirmed=identity_confirmed,
                source_claim_id=claim.id,
            )
        )
    db.commit()

    status = (
        PipelineEventStatus.warning
        if not result.model_available
        else PipelineEventStatus.passed
    )
    return StageResult(status=status, detail=result.detail)


async def stage_consistency_check(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    if len(images) <= 1:
        return StageResult(
            status=PipelineEventStatus.passed,
            detail="Single-image claim; consistency check not required.",
        )

    # Ensure phashes exist (duplicate stage usually wrote them).
    hashes: list[str] = []
    for image_row, path in images:
        if not image_row.phash:
            image_row.phash = await asyncio.to_thread(phash_reuse.compute_phash, path)
        hashes.append(image_row.phash)
    db.commit()

    import imagehash

    max_distance = 0
    for i, left in enumerate(hashes):
        for right in hashes[i + 1 :]:
            try:
                distance = imagehash.hex_to_hash(left) - imagehash.hex_to_hash(right)
            except Exception:
                distance = 64
            max_distance = max(max_distance, distance)

    # Same vehicle photos from different angles can differ; only flag extremes.
    if max_distance > 28:
        return StageResult(
            status=PipelineEventStatus.warning,
            detail=(
                f"Images differ substantially (phash distance {max_distance}). "
                "They may not show the same vehicle."
            ),
        )

    return StageResult(
        status=PipelineEventStatus.passed,
        detail="All images appear to show the same vehicle.",
    )


async def stage_damage_detection(db: Session, claim: Claim) -> StageResult:
    images = _paths(db, claim)
    paths = [path for _, path in images]
    predictions = await asyncio.to_thread(damage_segmenter.classify_paths, paths)

    # Replace prior detections if the pipeline is re-run.
    prior = db.scalars(
        select(DamageDetection).where(DamageDetection.claim_id == claim.id)
    ).all()
    for old in prior:
        db.delete(old)

    details: list[str] = []
    for (image_row, _), prediction in zip(images, predictions):
        graded = severity_service.grade_prediction(prediction)
        db.add(
            DamageDetection(
                claim_id=claim.id,
                claim_image_id=image_row.id,
                part_name=prediction.part_name,
                damage_type=prediction.damage_type,
                severity=graded.severity,
                repair_or_replace=graded.repair_or_replace,
                confidence_score=prediction.confidence,
            )
        )
        details.append(prediction.detail)
    db.commit()

    if not predictions:
        return StageResult(
            status=PipelineEventStatus.warning,
            detail="No damage predictions were produced.",
        )

    status = (
        PipelineEventStatus.warning
        if any(not p.model_available for p in predictions)
        else PipelineEventStatus.passed
    )
    return StageResult(status=status, detail=details[0])


async def stage_severity_grading(db: Session, claim: Claim) -> StageResult:
    detections = db.scalars(
        select(DamageDetection).where(DamageDetection.claim_id == claim.id)
    ).all()
    if not detections:
        return StageResult(
            status=PipelineEventStatus.warning,
            detail="No damage detections available to grade.",
        )

    # Severity already written during damage_detection; summarise here.
    summary = ", ".join(
        f"{row.part_name} ({row.severity.value})" for row in detections[:3]
    )
    return StageResult(
        status=PipelineEventStatus.passed,
        detail=f"Severity graded: {summary}.",
    )


async def stage_fraud_scoring(db: Session, claim: Claim) -> StageResult:
    signals = rules_engine.evaluate_claim(db, claim)
    scored = risk_scorer.score_signals(signals)

    for signal in scored.signals:
        db.add(
            FraudSignal(
                claim_id=claim.id,
                signal_type=signal.signal_type,
                risk_score=signal.risk_score,
                reason_code=signal.reason_code,
            )
        )
    db.commit()
    return StageResult(status=PipelineEventStatus.passed, detail=scored.detail)


async def stage_parts_matching(db: Session, claim: Claim) -> StageResult:
    from app.services.parts import parts_matcher

    matched, total, detail = parts_matcher.match_summary(db, claim.id)
    if total == 0:
        return StageResult(
            status=PipelineEventStatus.warning,
            detail="No damage detections available for parts matching.",
        )
    if matched == 0:
        return StageResult(
            status=PipelineEventStatus.warning,
            detail=detail,
        )
    return StageResult(status=PipelineEventStatus.passed, detail=detail)


async def stage_estimate_ready(db: Session, claim: Claim) -> StageResult:
    from app.services.parts import estimate_builder

    estimate = estimate_builder.persist_estimate(db, claim.id)
    n = len(estimate.line_items or [])
    return StageResult(
        status=PipelineEventStatus.passed,
        detail=(
            f"Survey estimate ready — {n} line item(s), "
            f"total ₹{float(estimate.grand_total):,.2f}."
        ),
    )


STAGE_HANDLERS: dict[str, StageFn] = {
    "intake": stage_intake,
    "quality_gate": stage_quality_gate,
    "deepfake_check": stage_deepfake_check,
    "vehicle_forensics": stage_vehicle_forensics,
    "duplicate_check": stage_duplicate_check,
    "vehicle_id": stage_vehicle_id,
    "consistency_check": stage_consistency_check,
    "damage_detection": stage_damage_detection,
    "severity_grading": stage_severity_grading,
    "fraud_scoring": stage_fraud_scoring,
    "parts_matching": stage_parts_matching,
    "estimate_ready": stage_estimate_ready,
}


def event_to_dict(event: PipelineEvent, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": event.id,
        "claim_id": event.claim_id,
        "stage_key": event.stage_key,
        "stage_label": event.stage_label,
        "status": event.status.value
        if isinstance(event.status, PipelineEventStatus)
        else event.status,
        "detail": event.detail,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
    payload.update(extra)
    return payload


async def _emit(
    db: Session,
    *,
    claim_id: int,
    stage_key: str,
    stage_label: str,
    status: PipelineEventStatus,
    detail: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    event = PipelineEvent(
        claim_id=claim_id,
        stage_key=stage_key,
        stage_label=stage_label,
        status=status,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    payload = event_to_dict(event, **extra)
    await event_bus.publish(claim_id, payload)
    return payload


async def run_pipeline(claim_id: int) -> None:
    async with _running_lock:
        if claim_id in _running_claims:
            logger.info("Pipeline already running for claim %s", claim_id)
            return
        _running_claims.add(claim_id)

    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if not claim:
            logger.error("Claim %s not found for pipeline", claim_id)
            return

        if claim.status in {
            ClaimStatus.estimate_ready,
            ClaimStatus.authenticity_failed,
            ClaimStatus.review_required,
            ClaimStatus.closed,
        }:
            return

        existing = db.scalars(
            select(PipelineEvent).where(PipelineEvent.claim_id == claim_id)
        ).all()
        if existing and claim.status == ClaimStatus.processing:
            finished_keys = {
                e.stage_key
                for e in existing
                if e.status
                in {
                    PipelineEventStatus.passed,
                    PipelineEventStatus.failed,
                    PipelineEventStatus.warning,
                }
            }
            if "estimate_ready" in finished_keys:
                return

        claim.status = ClaimStatus.processing
        db.commit()

        for stage_key, stage_label in PIPELINE_STAGES:
            await _emit(
                db,
                claim_id=claim_id,
                stage_key=stage_key,
                stage_label=stage_label,
                status=PipelineEventStatus.started,
            )

            handler = STAGE_HANDLERS[stage_key]
            claim = db.get(Claim, claim_id)
            assert claim is not None
            result = await handler(db, claim)

            resolved_label = RESOLVED_LABELS.get(stage_key, {}).get(
                result.status.value, stage_label
            )
            # Warnings keep the in-process label unless a resolved label exists.
            if result.status == PipelineEventStatus.warning:
                label_out = stage_label
            else:
                label_out = resolved_label

            payload = await _emit(
                db,
                claim_id=claim_id,
                stage_key=stage_key,
                stage_label=label_out,
                status=result.status,
                detail=result.detail,
            )

            if result.status == PipelineEventStatus.failed and stage_key in HALTING_STAGES:
                claim.status = ClaimStatus.authenticity_failed
                db.commit()
                halt_message = result.halt_message or (
                    f"{result.detail or label_out}. "
                    "This claim has been paused so a surveyor can review it manually."
                )
                await event_bus.publish(
                    claim_id,
                    {
                        **payload,
                        "pipeline_complete": True,
                        "halted": True,
                        "claim_status": claim.status.value,
                        "halt_message": halt_message,
                    },
                )
                return

        claim.status = ClaimStatus.estimate_ready
        db.commit()
        done_at = datetime.now(timezone.utc)
        await event_bus.publish(
            claim_id,
            {
                "claim_id": claim_id,
                "stage_key": "estimate_ready",
                "stage_label": "Survey estimate ready",
                "status": PipelineEventStatus.passed.value,
                "detail": "Survey estimate is ready to review.",
                "created_at": done_at.isoformat(),
                "pipeline_complete": True,
                "halted": False,
                "claim_status": claim.status.value,
                "redirect": f"/claims/{claim_id}/estimate",
            },
        )
    except Exception:
        logger.exception("Pipeline failed for claim %s", claim_id)
        try:
            claim = db.get(Claim, claim_id)
            if claim:
                claim.status = ClaimStatus.review_required
                db.commit()
            await event_bus.publish(
                claim_id,
                {
                    "claim_id": claim_id,
                    "stage_key": "pipeline_error",
                    "stage_label": "Assessment interrupted",
                    "status": PipelineEventStatus.failed.value,
                    "detail": "An unexpected error paused this assessment.",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "pipeline_complete": True,
                    "halted": True,
                    "claim_status": ClaimStatus.review_required.value,
                    "halt_message": (
                        "Something went wrong while assessing this claim. "
                        "It has been sent for manual review."
                    ),
                },
            )
        except Exception:
            logger.exception("Failed to publish pipeline error for claim %s", claim_id)
    finally:
        db.close()
        async with _running_lock:
            _running_claims.discard(claim_id)


async def ensure_pipeline_started(claim_id: int) -> None:
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if not claim:
            return
        if claim.status in {
            ClaimStatus.estimate_ready,
            ClaimStatus.authenticity_failed,
            ClaimStatus.review_required,
            ClaimStatus.closed,
        }:
            return
        if claim.status == ClaimStatus.processing:
            async with _running_lock:
                if claim_id in _running_claims:
                    return
            has_events = db.scalar(
                select(PipelineEvent.id)
                .where(PipelineEvent.claim_id == claim_id)
                .limit(1)
            )
            if has_events:
                return
    finally:
        db.close()

    await run_pipeline(claim_id)
