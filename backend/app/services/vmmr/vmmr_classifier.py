"""Vehicle make/model recognition (best-effort for the POC).

No strong global VMMR checkpoint exists (see ML playbook). Live mode uses a
torchvision ImageNet-pretrained ResNet50. Stub mode returns a deterministic
fixture and never imports torch.

Full make/model fine-tuning on VMMRdb + local market photos is the follow-on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.core.config import get_settings

logger = logging.getLogger("ai_tribe.vmmr")

MODEL_NAME = "resnet50"
IMAGENET_VEHICLE_HINTS = (
    "car",
    "wagon",
    "van",
    "truck",
    "cab",
    "convertible",
    "limousine",
    "minivan",
    "jeep",
    "ambulance",
    "police",
    "racer",
    "beach wagon",
    "sports car",
    "passenger car",
)

_model = None
_labels: list[str] | None = None
_preprocess = None
_load_error: str | None = None
_lock = Lock()


@dataclass
class VmmrResult:
    make: str
    model: str
    year: int | None
    confidence: float
    label: str
    detail: str
    model_available: bool


def _stub_result() -> VmmrResult:
    # Deterministic fixture matching the live-mode detail shape.
    return VmmrResult(
        make="Maruti",
        model="Swift",
        year=2019,
        confidence=0.78,
        label="stub_fixture",
        detail=(
            "Provisional identity: Maruti Swift (78% stub fixture). "
            "Full make/model fine-tuning is pending."
        ),
        model_available=True,
    )


def _get_model():
    global _model, _labels, _preprocess, _load_error
    with _lock:
        if _model is not None or _load_error is not None:
            return _model, _labels
        try:
            from torchvision import transforms  # noqa: PLC0415 — live-only
            from torchvision.models import (  # noqa: PLC0415
                ResNet50_Weights,
                resnet50,
            )

            weights = ResNet50_Weights.DEFAULT
            model = resnet50(weights=weights)
            model.eval()
            _model = model
            _labels = list(weights.meta["categories"])
            _preprocess = transforms.Compose(
                [
                    transforms.Resize(256),
                    transforms.CenterCrop(224),
                    transforms.ToTensor(),
                    transforms.Normalize(
                        mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225],
                    ),
                ]
            )
            logger.info("Loaded VMMR backbone %s (ImageNet transfer)", MODEL_NAME)
        except Exception as exc:
            _load_error = str(exc)
            logger.exception("Failed to load VMMR backbone")
        return _model, _labels


def _parse_identity(label: str) -> tuple[str, str]:
    cleaned = label.replace("_", " ").strip()
    return "Unknown", cleaned.title()


def _classify_live(path: Path) -> VmmrResult:
    model, labels = _get_model()
    if model is None or labels is None or _preprocess is None:
        return VmmrResult(
            make="Unknown",
            model="Unknown",
            year=None,
            confidence=0.0,
            label="unavailable",
            detail=(
                "Vehicle recognition backbone unavailable; recorded as Unknown. "
                f"{_load_error}"
            ),
            model_available=False,
        )

    import torch  # noqa: PLC0415 — live-only import
    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as img:
        tensor = _preprocess(img.convert("RGB")).unsqueeze(0)

    with torch.no_grad():
        logits = model(tensor)
        probabilities = torch.nn.functional.softmax(logits[0], dim=0)

    topk = torch.topk(probabilities, k=10)
    chosen_idx = int(topk.indices[0])
    chosen_score = float(topk.values[0])
    for score, idx in zip(topk.values.tolist(), topk.indices.tolist()):
        label = labels[idx].lower()
        if any(hint in label for hint in IMAGENET_VEHICLE_HINTS):
            chosen_idx = int(idx)
            chosen_score = float(score)
            break

    label = labels[chosen_idx]
    make, model_name = _parse_identity(label)
    detail = (
        f"Provisional identity: {make} {model_name} "
        f"({chosen_score:.0%} via ImageNet transfer). "
        "Full make/model fine-tuning is pending."
    )
    return VmmrResult(
        make=make,
        model=model_name,
        year=None,
        confidence=chosen_score,
        label=label,
        detail=detail,
        model_available=True,
    )


def classify_image(path: Path) -> VmmrResult:
    if not get_settings().ml_live:
        return _stub_result()
    return _classify_live(path)


def classify_claim_images(paths: list[Path]) -> VmmrResult:
    if not paths:
        return VmmrResult(
            make="Unknown",
            model="Unknown",
            year=None,
            confidence=0.0,
            label="none",
            detail="No images available for vehicle identification.",
            model_available=False,
        )

    if not get_settings().ml_live:
        return _stub_result()

    results = [classify_image(path) for path in paths]
    return max(results, key=lambda item: item.confidence)
