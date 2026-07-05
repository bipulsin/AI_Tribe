"""Merge per-image damage detections and assess extensive-damage escalation."""

from __future__ import annotations

from app.models.damage_detection import DamageDetection
from app.models.enums import Severity

PRICING_EXTENSIVE_DAMAGE = "extensive_damage_manual_review"

_SEVERITY_RANK = {
    Severity.minor.value: 0,
    Severity.moderate.value: 1,
    Severity.severe.value: 2,
}


def _severity_value(detection: DamageDetection) -> str:
    if hasattr(detection.severity, "value"):
        return detection.severity.value
    return str(detection.severity)


def aggregate_detections(detections: list[DamageDetection]) -> list[DamageDetection]:
    """Collapse duplicate part+damage pairs photographed from multiple angles."""
    merged: dict[tuple[str, str], DamageDetection] = {}
    for detection in detections:
        damage_key = (
            detection.damage_type.value
            if hasattr(detection.damage_type, "value")
            else str(detection.damage_type)
        )
        key = (detection.part_name, damage_key)
        existing = merged.get(key)
        if existing is None:
            merged[key] = detection
            continue

        if float(detection.confidence_score) > float(existing.confidence_score):
            existing.confidence_score = detection.confidence_score

        if _SEVERITY_RANK.get(_severity_value(detection), 0) > _SEVERITY_RANK.get(
            _severity_value(existing), 0
        ):
            existing.severity = detection.severity

        if (detection.repair_or_replace or "").lower() == "replace":
            existing.repair_or_replace = "replace"

    return list(merged.values())


def assess_extensive_damage(detections: list[DamageDetection]) -> tuple[bool, str]:
    """Explainable proxy for total-loss / extensive damage before itemized pricing."""
    severe_replace_count = sum(
        1
        for detection in detections
        if _severity_value(detection) == Severity.severe.value
        and (detection.repair_or_replace or "").lower() == "replace"
    )
    distinct_parts = {detection.part_name for detection in detections}

    if severe_replace_count >= 3:
        return (
            True,
            f"{severe_replace_count} images independently graded severe/replace — "
            "possible extensive or total damage.",
        )
    if len(distinct_parts) >= 3:
        parts_list = ", ".join(sorted(distinct_parts))
        return (
            True,
            f"Damage spans {len(distinct_parts)} distinct parts ({parts_list}) — "
            "possible extensive collision pattern.",
        )
    return False, ""
