"""Vehicle make/model recognition.

ML_MODE=stub: deterministic fixture (never imports torch).

ML_MODE=live:
  1. Fine-tuned FGVD-7 classifier when checkpoint is present under
     backend/app/ml_weights/vmmr/ (independent of /mnt/ml-scratch).
     Accept only if top-1 vs top-2 probability margin exceeds the
     checkpoint margin_threshold (settled at ~0.39 from held-out
     correct-prediction margins; default 0.4 if meta missing).
  2. Below that margin, fall through to ImageNet-transfer ResNet50 and
     mark identity_confirmed=false (pricing_basis=provisional_fallback).

Catalog coverage (10 models in india_parts_seed.csv):

  Real (uneven) FGVD training data — fine-tune can confirm when margin OK:
    Maruti Swift (~440), Toyota Innova (~467), Hyundai i20 (~122),
    Hyundai Creta (~107), Maruti Baleno (~91), Honda City (~82),
    Renault Kwid (~23). Baleno/City/Kwid held-out sets are too small to
    treat accuracy as reliable (Kwid n_test≈5 especially).

  Provisional only — zero usable training images, never confirmed by the
  fine-tuned head (no class; always ImageNet / provisional_fallback):
    Tata Nexon (2 images, unused), Mahindra XUV700 (0), Kia Seltos (0).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.core.config import REPO_ROOT, get_settings

logger = logging.getLogger("ai_tribe.vmmr")

MODEL_NAME = "resnet50"
VMMR_DIR = REPO_ROOT / "backend" / "app" / "ml_weights" / "vmmr"
CHECKPOINT_PATH = VMMR_DIR / "vmmr_resnet50_fgvd7.pt"
META_PATH = VMMR_DIR / "meta.json"

# Catalog models with real (uneven) FGVD training data.
TRAINED_CATALOG_MODELS = {
    "Maruti_Swift",
    "Maruti_Baleno",
    "Hyundai_i20",
    "Hyundai_Creta",
    "Honda_City",
    "Toyota_Innova",
    "Renault_Kwid",
}

# Catalog models with zero FGVD training images — always provisional.
PROVISIONAL_ONLY_MODELS = {
    "Tata_Nexon",
    "Mahindra_XUV700",
    "Kia_Seltos",
}

DEFAULT_MARGIN_THRESHOLD = 0.4

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

_finetuned = None
_finetuned_labels: list[str] | None = None
_finetuned_margin: float = DEFAULT_MARGIN_THRESHOLD
_imagenet = None
_imagenet_labels: list[str] | None = None
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
    identity_confirmed: bool = False
    margin: float = 0.0


def _stub_result() -> VmmrResult:
    return VmmrResult(
        make="Maruti",
        model="Swift",
        year=2019,
        confidence=0.78,
        label="stub_fixture",
        detail=(
            "Provisional identity: Maruti Swift (78% stub fixture). "
            "Fine-tuned VMMR is inactive in ML_MODE=stub."
        ),
        model_available=True,
        identity_confirmed=False,
        margin=0.0,
    )


def _ensure_preprocess():
    global _preprocess
    if _preprocess is not None:
        return _preprocess
    from torchvision import transforms  # noqa: PLC0415

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
    return _preprocess


def _load_finetuned():
    global _finetuned, _finetuned_labels, _finetuned_margin, _load_error
    with _lock:
        if _finetuned is not None or _load_error is not None:
            return _finetuned, _finetuned_labels
        if not CHECKPOINT_PATH.exists():
            logger.warning("Fine-tuned VMMR checkpoint missing at %s", CHECKPOINT_PATH)
            return None, None
        try:
            import torch  # noqa: PLC0415
            from torchvision.models import resnet50  # noqa: PLC0415

            ckpt = torch.load(CHECKPOINT_PATH, map_location="cpu")
            class_names = ckpt.get("class_names") or []
            margin = float(ckpt.get("margin_threshold", DEFAULT_MARGIN_THRESHOLD))
            model = resnet50(weights=None)
            model.fc = torch.nn.Linear(model.fc.in_features, len(class_names))
            model.load_state_dict(ckpt["model_state"])
            model.eval()
            _finetuned = model
            _finetuned_labels = list(class_names)
            _finetuned_margin = margin
            _ensure_preprocess()
            logger.info(
                "Loaded fine-tuned VMMR (%s classes, margin>=%.2f) from %s",
                len(class_names),
                margin,
                CHECKPOINT_PATH,
            )
        except Exception as exc:
            _load_error = str(exc)
            logger.exception("Failed to load fine-tuned VMMR checkpoint")
        return _finetuned, _finetuned_labels


def _load_imagenet():
    global _imagenet, _imagenet_labels, _load_error
    with _lock:
        if _imagenet is not None:
            return _imagenet, _imagenet_labels
        try:
            from torchvision.models import (  # noqa: PLC0415
                ResNet50_Weights,
                resnet50,
            )

            weights = ResNet50_Weights.DEFAULT
            model = resnet50(weights=weights)
            model.eval()
            _imagenet = model
            _imagenet_labels = list(weights.meta["categories"])
            _ensure_preprocess()
            logger.info("Loaded ImageNet-transfer VMMR fallback backbone")
        except Exception as exc:
            _load_error = str(exc)
            logger.exception("Failed to load ImageNet VMMR backbone")
        return _imagenet, _imagenet_labels


def _split_class_key(class_key: str) -> tuple[str, str]:
    # Maruti_Swift -> Maruti, Swift; Hyundai_i20 -> Hyundai, i20
    if "_" not in class_key:
        return "Unknown", class_key
    make, model = class_key.split("_", 1)
    return make, model


def _classify_finetuned(path: Path) -> VmmrResult | None:
    import torch  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    model, labels = _load_finetuned()
    if model is None or labels is None or _preprocess is None:
        return None

    with Image.open(path) as img:
        tensor = _preprocess(img.convert("RGB")).unsqueeze(0)

    with torch.no_grad():
        logits = model(tensor)
        probs = torch.softmax(logits[0], dim=0)

    top2 = torch.topk(probs, k=min(2, probs.numel()))
    top_idx = int(top2.indices[0])
    top_score = float(top2.values[0])
    second_score = float(top2.values[1]) if top2.values.numel() > 1 else 0.0
    margin = top_score - second_score
    class_key = labels[top_idx]
    make, model_name = _split_class_key(class_key)

    if margin < _finetuned_margin:
        return VmmrResult(
            make=make,
            model=model_name,
            year=None,
            confidence=top_score,
            label=class_key,
            detail=(
                f"Fine-tuned VMMR top guess {make} {model_name} "
                f"({top_score:.0%}, margin {margin:.2f} < {_finetuned_margin:.2f}); "
                "falling through to provisional ImageNet transfer."
            ),
            model_available=True,
            identity_confirmed=False,
            margin=margin,
        )

    return VmmrResult(
        make=make,
        model=model_name,
        year=None,
        confidence=top_score,
        label=class_key,
        detail=(
            f"Identity: {make} {model_name} "
            f"({top_score:.0%}, margin {margin:.2f} via FGVD-7 fine-tune)."
        ),
        model_available=True,
        identity_confirmed=True,
        margin=margin,
    )


def _classify_imagenet_fallback(path: Path, prior: VmmrResult | None = None) -> VmmrResult:
    import torch  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    model, labels = _load_imagenet()
    if model is None or labels is None or _preprocess is None:
        return VmmrResult(
            make="Unknown",
            model="Unknown",
            year=None,
            confidence=0.0,
            label="unavailable",
            detail=(
                "Vehicle recognition unavailable; recorded as Unknown. "
                f"{_load_error}"
            ),
            model_available=False,
            identity_confirmed=False,
            margin=0.0,
        )

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
    prior_note = ""
    if prior is not None and not prior.identity_confirmed and prior.label:
        prior_note = f" Fine-tuned head was inconclusive ({prior.label}, margin {prior.margin:.2f})."

    detail = (
        f"Provisional identity: Unknown {label.replace('_', ' ').title()} "
        f"({chosen_score:.0%} via ImageNet transfer).{prior_note} "
        "Catalog models without training coverage "
        f"({', '.join(sorted(PROVISIONAL_ONLY_MODELS))}) always stay provisional."
    )
    return VmmrResult(
        make="Unknown",
        model=label.replace("_", " ").title(),
        year=None,
        confidence=chosen_score,
        label=label,
        detail=detail,
        model_available=True,
        identity_confirmed=False,
        margin=0.0,
    )


def _classify_live(path: Path) -> VmmrResult:
    finetuned = _classify_finetuned(path)
    if finetuned is not None and finetuned.identity_confirmed:
        return finetuned
    return _classify_imagenet_fallback(path, prior=finetuned)


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
            identity_confirmed=False,
            margin=0.0,
        )

    if not get_settings().ml_live:
        return _stub_result()

    results = [classify_image(path) for path in paths]
    # Prefer any confirmed identity; otherwise highest confidence provisional.
    confirmed = [r for r in results if r.identity_confirmed]
    if confirmed:
        return max(confirmed, key=lambda item: item.confidence)
    return max(results, key=lambda item: item.confidence)
