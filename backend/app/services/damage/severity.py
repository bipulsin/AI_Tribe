"""Damage severity grading and repair-vs-replace recommendation."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import DamageType, Severity
from app.services.damage.damage_segmenter import DamagePrediction

# Damage types that usually mean replace rather than repair.
REPLACE_TYPES = {
    DamageType.glass_shatter,
    DamageType.lamp_broken,
    DamageType.tire_flat,
}


@dataclass
class SeverityResult:
    severity: Severity
    repair_or_replace: str
    detail: str


def grade_prediction(prediction: DamagePrediction) -> SeverityResult:
    if prediction.damage_type in REPLACE_TYPES:
        severity = Severity.severe if prediction.confidence >= 0.55 else Severity.moderate
        action = "replace"
    elif prediction.confidence >= 0.8:
        severity = Severity.severe
        action = "replace"
    elif prediction.confidence >= 0.55:
        severity = Severity.moderate
        action = "repair"
    else:
        severity = Severity.minor
        action = "repair"

    detail = (
        f"{prediction.part_name}: {severity.value} {prediction.damage_type.value}, "
        f"recommend {action}."
    )
    return SeverityResult(
        severity=severity,
        repair_or_replace=action,
        detail=detail,
    )


def grade_all(predictions: list[DamagePrediction]) -> list[SeverityResult]:
    return [grade_prediction(item) for item in predictions]
