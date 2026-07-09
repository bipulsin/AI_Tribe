"""Deepfake / AI-generated image screening.

Primary live model (ML playbook): prithivMLmods/Deep-Fake-Detector-v2-Model

When ML_MODE=stub (default), returns deterministic fixtures and never imports
torch or transformers. Live inference loads the HF pipeline lazily.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.core.config import get_settings

logger = logging.getLogger("ai_tribe.deepfake")

MODEL_ID = "prithivMLmods/Deep-Fake-Detector-v2-Model"
FAKE_LABEL_TOKENS = ("deepfake", "fake", "artificial", "generated")
REAL_LABEL_TOKENS = ("real", "realism", "authentic")

_pipeline = None
_load_error: str | None = None
_lock = Lock()


@dataclass
class DeepfakeResult:
    is_fake: bool
    label: str
    score: float
    detail: str
    model_available: bool
    fake_score: float = 0.0
    real_score: float = 0.0


def _stub_result(_path: Path) -> DeepfakeResult:
    # Shape verified during Milestone 5 live runs (cleared, not halted).
    return DeepfakeResult(
        is_fake=False,
        label="Realism",
        score=0.92,
        detail="Image cleared (realism 92%, deepfake 8%).",
        model_available=True,
        fake_score=0.08,
        real_score=0.92,
    )


def _get_pipeline():
    """Load the HF pipeline only when ML_MODE=live."""
    global _pipeline, _load_error
    with _lock:
        if _pipeline is not None or _load_error is not None:
            return _pipeline
        try:
            from transformers import pipeline  # noqa: PLC0415 — live-only import

            _pipeline = pipeline(
                "image-classification",
                model=MODEL_ID,
                device=-1,
            )
            logger.info("Loaded deepfake model %s", MODEL_ID)
        except Exception as exc:
            _load_error = str(exc)
            logger.exception("Failed to load deepfake model %s", MODEL_ID)
        return _pipeline


def _classify_live(path: Path) -> DeepfakeResult:
    from PIL import Image  # noqa: PLC0415

    detector = _get_pipeline()
    if detector is None:
        return DeepfakeResult(
            is_fake=False,
            label="unavailable",
            score=0.0,
            detail=(
                "Deepfake model unavailable; stage passed with warning. "
                f"Load error: {_load_error}"
            ),
            model_available=False,
        )

    with Image.open(path) as img:
        rgb = img.convert("RGB")

    predictions = detector(rgb)
    if not predictions:
        return DeepfakeResult(
            is_fake=False,
            label="unknown",
            score=0.0,
            detail="Deepfake model returned no prediction.",
            model_available=True,
        )

    top = max(predictions, key=lambda item: item.get("score", 0.0))
    label = str(top.get("label", "unknown"))
    score = float(top.get("score", 0.0))

    fake_score = max(
        (
            float(item.get("score", 0.0))
            for item in predictions
            if any(token in str(item.get("label", "")).lower() for token in FAKE_LABEL_TOKENS)
        ),
        default=0.0,
    )
    real_score = max(
        (
            float(item.get("score", 0.0))
            for item in predictions
            if any(token in str(item.get("label", "")).lower() for token in REAL_LABEL_TOKENS)
        ),
        default=0.0,
    )

    is_fake = fake_score >= 0.70 and fake_score > real_score
    if is_fake:
        detail = f"Deepfake identified (score {fake_score:.0%})."
    else:
        detail = f"Image cleared (realism {real_score:.0%}, deepfake {fake_score:.0%})."

    return DeepfakeResult(
        is_fake=is_fake,
        label=label,
        score=score,
        detail=detail,
        model_available=True,
        fake_score=fake_score,
        real_score=real_score,
    )


def classify_image(path: Path) -> DeepfakeResult:
    if not get_settings().ml_live:
        return _stub_result(path)
    return _classify_live(path)


def classify_paths(paths: list[Path]) -> tuple[bool, str, list[DeepfakeResult]]:
    if not paths:
        return True, "No images for deepfake screening.", []

    results = [classify_image(path) for path in paths]
    fakes = [r for r in results if r.is_fake]
    if fakes:
        return False, fakes[0].detail, results

    if any(not r.model_available for r in results):
        return True, results[0].detail, results

    return True, results[0].detail, results
