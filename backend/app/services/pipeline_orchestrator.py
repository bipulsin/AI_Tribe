"""Pipeline orchestrator — stub stages (Milestone 4), real models in Milestone 5.

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
from app.models import Claim, PipelineEvent
from app.models.enums import ClaimStatus, PipelineEventStatus

logger = logging.getLogger("ai_tribe.pipeline")

# Stage sequence and user-facing labels (exact strings from the product brief).
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

# Stages that halt the pipeline on failure (authenticity / forensics).
HALTING_STAGES = {
    "quality_gate",
    "deepfake_check",
    "vehicle_forensics",
    "duplicate_check",
}

# Resolved labels for stages that change wording when they finish.
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

# In-process guard so a claim is not run twice concurrently.
_running_claims: set[int] = set()
_running_lock = asyncio.Lock()


@dataclass
class StageResult:
    status: PipelineEventStatus
    detail: str | None = None
    halt_message: str | None = None


StageFn = Callable[[Session, Claim], Awaitable[StageResult]]


async def _stub_pass(
    _db: Session,
    _claim: Claim,
    *,
    detail: str,
    delay: float = 0.45,
) -> StageResult:
    await asyncio.sleep(delay)
    return StageResult(status=PipelineEventStatus.passed, detail=detail)


async def stage_intake(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Images prepared for assessment.")


async def stage_quality_gate(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Image quality is sufficient for assessment.")


async def stage_deepfake_check(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Image cleared")


async def stage_vehicle_forensics(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Forensic check passed")


async def stage_duplicate_check(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="No reused images found in prior claims.")


async def stage_vehicle_id(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Vehicle identity recorded (stub).")


async def stage_consistency_check(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="All images appear to show the same vehicle.")


async def stage_damage_detection(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Damage regions mapped to vehicle parts (stub).")


async def stage_severity_grading(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Severity grades assigned (stub).")


async def stage_fraud_scoring(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="No elevated fraud signals (stub).")


async def stage_parts_matching(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Parts matched to pricing catalogue (stub).")


async def stage_estimate_ready(db: Session, claim: Claim) -> StageResult:
    return await _stub_pass(db, claim, detail="Survey estimate is ready to review.")


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
        "status": event.status.value if isinstance(event.status, PipelineEventStatus) else event.status,
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
    """Run the full assessment pipeline for a claim (stub stages)."""
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

        # Skip if already finished or in a terminal authenticity state.
        if claim.status in {
            ClaimStatus.estimate_ready,
            ClaimStatus.authenticity_failed,
            ClaimStatus.review_required,
            ClaimStatus.closed,
        }:
            return

        # Avoid re-running a partially completed pipeline on accidental re-entry.
        existing = db.scalars(
            select(PipelineEvent).where(PipelineEvent.claim_id == claim_id)
        ).all()
        if existing and claim.status == ClaimStatus.processing:
            # Resume is out of scope for the POC stubs — only start from clean state.
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
            # Re-load claim in case handlers write related rows later.
            claim = db.get(Claim, claim_id)
            assert claim is not None
            result = await handler(db, claim)

            resolved_label = RESOLVED_LABELS.get(stage_key, {}).get(
                result.status.value, stage_label
            )

            payload = await _emit(
                db,
                claim_id=claim_id,
                stage_key=stage_key,
                stage_label=resolved_label if result.status != PipelineEventStatus.started else stage_label,
                status=result.status,
                detail=result.detail,
            )

            if result.status == PipelineEventStatus.failed and stage_key in HALTING_STAGES:
                claim.status = ClaimStatus.authenticity_failed
                db.commit()
                halt_message = result.halt_message or (
                    f"{result.detail or resolved_label}. "
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
        await event_bus.publish(
            claim_id,
            {
                "claim_id": claim_id,
                "stage_key": "estimate_ready",
                "stage_label": "Survey estimate ready",
                "status": PipelineEventStatus.passed.value,
                "detail": "Survey estimate is ready to review.",
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
    """Kick off the pipeline if it is not already running or finished."""
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
            # Status says processing but no live task — allow restart only if no events.
            has_events = db.scalar(
                select(PipelineEvent.id).where(PipelineEvent.claim_id == claim_id).limit(1)
            )
            if has_events:
                return
    finally:
        db.close()

    await run_pipeline(claim_id)
