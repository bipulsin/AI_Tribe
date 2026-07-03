"""Vehicle make/model recognition (best-effort for the POC).

No strong global VMMR checkpoint exists (see ML playbook). This module uses a
timm ImageNet-pretrained backbone to detect vehicle-related classes and record
a provisional identity. Full make/model fine-tuning on VMMRdb + local market
photos is the intended follow-on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from PIL import Image

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


def _get_model():
    global _model, _labels, _preprocess, _load_error
    with _lock:
        if _model is not None or _load_error is not None:
            return _model, _labels
        try:
            from torchvision import transforms
            from torchvision.models import ResNet50_Weights, resnet50

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
    # ImageNet labels are generic (e.g. "sports car") — not OEM make/model.
    return "Unknown", cleaned.title()


def classify_image(path: Path) -> VmmrResult:
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

    import torch

    with Image.open(path) as img:
        tensor = _preprocess(img.convert("RGB")).unsqueeze(0)

    with torch.no_grad():
        logits = model(tensor)
        probabilities = torch.nn.functional.softmax(logits[0], dim=0)

    # Prefer vehicle-related ImageNet classes when present in the top-k.
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

    results = [classify_image(path) for path in paths]
    # Pick the highest-confidence vehicle-like prediction.
    return max(results, key=lambda item: item.confidence)
