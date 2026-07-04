"""Rule-based fraud signal extraction for the POC."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, ClaimImage, PipelineEvent
from app.models.enums import AuthenticityVerdict, FraudSignalType, PipelineEventStatus


@dataclass
class FraudSignalDraft:
    signal_type: FraudSignalType
    risk_score: int
    reason_code: str


def evaluate_claim(db: Session, claim: Claim) -> list[FraudSignalDraft]:
    signals: list[FraudSignalDraft] = []

    images = db.scalars(
        select(ClaimImage).where(ClaimImage.claim_id == claim.id)
    ).all()

    flagged = [
        img
        for img in images
        if img.authenticity_verdict == AuthenticityVerdict.flagged
    ]
    if flagged:
        signals.append(
            FraudSignalDraft(
                signal_type=FraudSignalType.soft_fraud,
                risk_score=70,
                reason_code="AUTHENTICITY_FLAGGED",
            )
        )

    failed_quality = [img for img in images if img.quality_gate_passed is False]
    if failed_quality:
        signals.append(
            FraudSignalDraft(
                signal_type=FraudSignalType.transactional,
                risk_score=35,
                reason_code="QUALITY_GATE_FAILED",
            )
        )

    # Reused-image failures leave a failed duplicate_check event.
    duplicate_fail = db.scalar(
        select(PipelineEvent).where(
            PipelineEvent.claim_id == claim.id,
            PipelineEvent.stage_key == "duplicate_check",
            PipelineEvent.status == PipelineEventStatus.failed,
        )
    )
    if duplicate_fail:
        signals.append(
            FraudSignalDraft(
                signal_type=FraudSignalType.organised_fraud_graph,
                risk_score=85,
                reason_code="IMAGE_REUSE_DETECTED",
            )
        )

    if len(images) == 1:
        signals.append(
            FraudSignalDraft(
                signal_type=FraudSignalType.transactional,
                risk_score=15,
                reason_code="SINGLE_IMAGE_SUBMISSION",
            )
        )

    sensor_warn = db.scalar(
        select(PipelineEvent).where(
            PipelineEvent.claim_id == claim.id,
            PipelineEvent.stage_key == "sensor_consistency",
            PipelineEvent.status == PipelineEventStatus.warning,
        )
    )
    if sensor_warn:
        signals.append(
            FraudSignalDraft(
                signal_type=FraudSignalType.soft_fraud,
                risk_score=55,
                reason_code="SENSOR_RESIDUAL_OUTLIER",
            )
        )

    from app.services.fraud.fraud_graph import evaluate_claim_signals

    signals.extend(evaluate_claim_signals(db, claim))

    return signals
