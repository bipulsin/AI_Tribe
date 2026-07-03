"""Vehicle damage classification via Hugging Face transformers.

Primary POC model (ML playbook): beingamit99/car_damage_detection
(BEiT classifier — damage type, not pixel segmentation). CarDD segmentation
can replace this behind the same interface later.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from PIL import Image

from app.models.enums import DamageType

logger = logging.getLogger("ai_tribe.damage")

MODEL_ID = "beingamit99/car_damage_detection"

LABEL_MAP: dict[str, DamageType] = {
    "dent": DamageType.dent,
    "scratch": DamageType.scratch,
    "crack": DamageType.crack,
    "glass shatter": DamageType.glass_shatter,
    "glass_shatter": DamageType.glass_shatter,
    "lamp broken": DamageType.lamp_broken,
    "lamp_broken": DamageType.lamp_broken,
    "tire flat": DamageType.tire_flat,
    "tire_flat": DamageType.tire_flat,
    "broken lamp": DamageType.lamp_broken,
    "flat tire": DamageType.tire_flat,
}

# Rough part assignment from damage type for estimate matching.
PART_FOR_DAMAGE: dict[DamageType, str] = {
    DamageType.dent: "Front Bumper",
    DamageType.scratch: "Front Door",
    DamageType.crack: "Rear Bumper",
    DamageType.glass_shatter: "Windshield",
    DamageType.lamp_broken: "Headlamp",
    DamageType.tire_flat: "Tire",
}

_pipeline = None
_load_error: str | None = None
_lock = Lock()


@dataclass
class DamagePrediction:
    damage_type: DamageType
    part_name: str
    confidence: float
    label: str
    detail: str
    model_available: bool


def _get_pipeline():
    global _pipeline, _load_error
    with _lock:
        if _pipeline is not None or _load_error is not None:
            return _pipeline
        try:
            from transformers import pipeline

            _pipeline = pipeline(
                "image-classification",
                model=MODEL_ID,
                device=-1,
            )
            logger.info("Loaded damage model %s", MODEL_ID)
        except Exception as exc:
            _load_error = str(exc)
            logger.exception("Failed to load damage model %s", MODEL_ID)
        return _pipeline


def _map_label(label: str) -> DamageType:
    lowered = label.lower().strip()
    lowered = re.sub(r"[_-]+", " ", lowered)
    if lowered in LABEL_MAP:
        return LABEL_MAP[lowered]
    for key, value in LABEL_MAP.items():
        if key in lowered:
            return value
    return DamageType.dent


def classify_image(path: Path) -> DamagePrediction:
    classifier = _get_pipeline()
    if classifier is None:
        return DamagePrediction(
            damage_type=DamageType.dent,
            part_name=PART_FOR_DAMAGE[DamageType.dent],
            confidence=0.35,
            label="unavailable",
            detail=(
                "Damage model unavailable; using provisional dent/front-bumper. "
                f"{_load_error}"
            ),
            model_available=False,
        )

    with Image.open(path) as img:
        rgb = img.convert("RGB")

    predictions = classifier(rgb)
    top = max(predictions, key=lambda item: item.get("score", 0.0))
    label = str(top.get("label", "dent"))
    score = float(top.get("score", 0.0))
    damage_type = _map_label(label)
    part_name = PART_FOR_DAMAGE[damage_type]

    return DamagePrediction(
        damage_type=damage_type,
        part_name=part_name,
        confidence=score,
        label=label,
        detail=f"{part_name}: {damage_type.value} ({score:.0%}).",
        model_available=True,
    )


def classify_paths(paths: list[Path]) -> list[DamagePrediction]:
    return [classify_image(path) for path in paths]
