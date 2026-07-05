"""Vehicle make/model recognition.

ML_MODE=stub: deterministic fixture (never imports torch).

ML_MODE=live:
  1. Fine-tuned FGVD-7 classifier when checkpoint is present under
     backend/app/ml_weights/vmmr/ (independent of /mnt/ml-scratch).
  2. Margin gate: top-1 − top-2 probability must exceed margin_threshold
     (settled at ~0.39 from held-out correct-prediction margins).
  3. Class-reliability tier on top of the margin gate:
       - reliable (Swift, Innova, i20): margin OK → identity_confirmed,
         pricing_basis=confirmed (auto-finalize).
       - low_confidence (Creta, Baleno, City, Kwid): margin OK still keeps
         the specific guess but pricing_basis=needs_confirmation (surveyor
         must confirm; not auto-trusted).
  4. Below margin: ImageNet-transfer ResNet50,
     pricing_basis=provisional_fallback.

Catalog coverage (10 models in india_parts_seed.csv):

  Real (uneven) FGVD training data:
    reliable: Maruti Swift, Toyota Innova, Hyundai i20
    low_confidence: Hyundai Creta, Maruti Baleno, Honda City, Renault Kwid,
      Mahindra XUV500 (forced low_confidence; ~64 images, no exact catalogue)

  Provisional only — zero usable training images (no class in head):
    Tata Nexon, Mahindra XUV700, Kia Seltos.

Known residual risk: a real City (or other low_confidence class) misclassified
as Swift/Innova/i20 still auto-finalizes, because the predicted class is
reliable-tier. Tier gating does not fix that reverse confusion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.core.config import REPO_ROOT, get_settings

logger = logging.getLogger("ai_tribe.vmmr")

MODEL_NAME = "resnet50"
VMMR_DIR = REPO_ROOT / "backend" / "app" / "ml_weights" / "vmmr"
CHECKPOINT_PATH = VMMR_DIR / "vmmr_resnet50_fgvd8.pt"
# Prefer fgvd8; fall back to fgvd7 if only the prior checkpoint is present.
LEGACY_CHECKPOINT_PATH = VMMR_DIR / "vmmr_resnet50_fgvd7.pt"
META_PATH = VMMR_DIR / "meta.json"

PRICING_CONFIRMED = "confirmed"
PRICING_NEEDS_CONFIRMATION = "needs_confirmation"
PRICING_PROVISIONAL = "provisional_fallback"

TIER_RELIABLE = "reliable"
TIER_LOW_CONFIDENCE = "low_confidence"

# Held-out top-1 roughly ≥65% with usable source counts.
RELIABLE_CLASSES = {
    "Maruti_Swift",
    "Toyota_Innova",
    "Hyundai_i20",
}

# Small source sets / weak top-1 — prone to being confused *with* by reliable
# classes, and not trustworthy enough to auto-finalize even at high margin.
# XUV500 is forced low_confidence regardless of held-out accuracy (n≈64).
LOW_CONFIDENCE_CLASSES = {
    "Hyundai_Creta",
    "Maruti_Baleno",
    "Honda_City",
    "Renault_Kwid",
    "Mahindra_XUV500",
}

CLASS_RELIABILITY_TIER: dict[str, str] = {
    **{name: TIER_RELIABLE for name in RELIABLE_CLASSES},
    **{name: TIER_LOW_CONFIDENCE for name in LOW_CONFIDENCE_CLASSES},
}

# Catalog models with real (uneven) FGVD training data.
TRAINED_CATALOG_MODELS = RELIABLE_CLASSES | LOW_CONFIDENCE_CLASSES

# Catalog models with zero FGVD training images — always provisional.
PROVISIONAL_ONLY_MODELS = {
    "Tata_Nexon",
    "Mahindra_XUV700",
    "Kia_Seltos",
}

# Settled at 0.39 from FGVD-7 held-out correct-prediction margin p25; 0.4 was the start.
DEFAULT_MARGIN_THRESHOLD = 0.39

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
    pricing_basis: str = PRICING_PROVISIONAL
    reliability_tier: str | None = None


@dataclass
class VmmrTopGuess:
    make: str
    model: str
    confidence: float
    class_key: str


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
        pricing_basis=PRICING_PROVISIONAL,
        reliability_tier=None,
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
        ckpt_path = CHECKPOINT_PATH if CHECKPOINT_PATH.exists() else LEGACY_CHECKPOINT_PATH
        if not ckpt_path.exists():
            logger.warning("Fine-tuned VMMR checkpoint missing at %s", CHECKPOINT_PATH)
            return None, None
        try:
            import torch  # noqa: PLC0415
            from torchvision.models import resnet50  # noqa: PLC0415

            ckpt = torch.load(ckpt_path, map_location="cpu")
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
                ckpt_path,
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
    tier = CLASS_RELIABILITY_TIER.get(class_key)

    if margin < _finetuned_margin:
        return VmmrResult(
            make=make,
            model=model_name,
            year=None,
            confidence=top_score,
            label=class_key,
            detail=(
                f"Fine-tuned VMMR top guess {make} {model_name} "
                f"({top_score:.0%}, margin {margin:.2f} < {_finetuned_margin:.2f}, "
                f"tier={tier or 'unknown'}); "
                "falling through to provisional ImageNet transfer."
            ),
            model_available=True,
            identity_confirmed=False,
            margin=margin,
            pricing_basis=PRICING_PROVISIONAL,
            reliability_tier=tier,
        )

    if tier == TIER_LOW_CONFIDENCE:
        return VmmrResult(
            make=make,
            model=model_name,
            year=None,
            confidence=top_score,
            label=class_key,
            detail=(
                f"Model guess: {make} {model_name} "
                f"({top_score:.0%}, margin {margin:.2f} via FGVD-7 fine-tune, "
                f"tier=low_confidence). Requires surveyor confirmation before "
                "pricing is treated as final."
            ),
            model_available=True,
            identity_confirmed=False,
            margin=margin,
            pricing_basis=PRICING_NEEDS_CONFIRMATION,
            reliability_tier=TIER_LOW_CONFIDENCE,
        )

    # reliable tier (or unknown trained class treated as reliable only if listed)
    if tier != TIER_RELIABLE:
        # Should not happen for FGVD-7 labels; treat as needs_confirmation.
        return VmmrResult(
            make=make,
            model=model_name,
            year=None,
            confidence=top_score,
            label=class_key,
            detail=(
                f"Model guess: {make} {model_name} "
                f"({top_score:.0%}, margin {margin:.2f}); unlisted tier — "
                "needs surveyor confirmation."
            ),
            model_available=True,
            identity_confirmed=False,
            margin=margin,
            pricing_basis=PRICING_NEEDS_CONFIRMATION,
            reliability_tier=tier,
        )

    return VmmrResult(
        make=make,
        model=model_name,
        year=None,
        confidence=top_score,
        label=class_key,
        detail=(
            f"Identity: {make} {model_name} "
            f"({top_score:.0%}, margin {margin:.2f} via FGVD-7 fine-tune, "
            f"tier=reliable)."
        ),
        model_available=True,
        identity_confirmed=True,
        margin=margin,
        pricing_basis=PRICING_CONFIRMED,
        reliability_tier=TIER_RELIABLE,
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
            pricing_basis=PRICING_PROVISIONAL,
            reliability_tier=None,
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
    if prior is not None and prior.label:
        prior_note = (
            f" Fine-tuned head was inconclusive ({prior.label}, "
            f"margin {prior.margin:.2f}, tier={prior.reliability_tier})."
        )

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
        pricing_basis=PRICING_PROVISIONAL,
        reliability_tier=None,
    )


def _classify_live(path: Path) -> VmmrResult:
    finetuned = _classify_finetuned(path)
    if finetuned is None:
        return _classify_imagenet_fallback(path)
    # Auto-finalize only for reliable tier + margin.
    if finetuned.identity_confirmed:
        return finetuned
    # Low-confidence tier with margin OK: keep specific guess, surveyor confirm.
    if finetuned.pricing_basis == PRICING_NEEDS_CONFIRMATION:
        return finetuned
    # Low margin (any tier): ImageNet provisional path.
    return _classify_imagenet_fallback(path, prior=finetuned)


def classify_image(path: Path) -> VmmrResult:
    if not get_settings().ml_live:
        return _stub_result()
    return _classify_live(path)


def guess_top_k(path: Path, k: int = 5) -> list[VmmrTopGuess]:
    """Top-k FGVD class probabilities for lab labeling / overlap scans."""
    if not get_settings().ml_live:
        return [
            VmmrTopGuess("Maruti", "Swift", 0.55, "Maruti_Swift"),
            VmmrTopGuess("Hyundai", "i20", 0.22, "Hyundai_i20"),
        ][:k]

    import torch  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    model, labels = _load_finetuned()
    if model is None or labels is None or _preprocess is None:
        return []

    with Image.open(path) as img:
        tensor = _preprocess(img.convert("RGB")).unsqueeze(0)

    with torch.no_grad():
        probs = torch.softmax(model(tensor)[0], dim=0)

    k = min(k, probs.numel())
    topk = torch.topk(probs, k=k)
    out: list[VmmrTopGuess] = []
    for idx, score in zip(topk.indices.tolist(), topk.values.tolist(), strict=False):
        class_key = labels[int(idx)]
        make, model_name = _split_class_key(class_key)
        out.append(
            VmmrTopGuess(
                make=make,
                model=model_name,
                confidence=float(score),
                class_key=class_key,
            )
        )
    return out


def detect_identity_inconsistency(results: list[VmmrResult]) -> str | None:
    """Flag when multiple images disagree on a specific catalogue identity."""
    confident: dict[str, int] = {}
    for result in results:
        if result.pricing_basis not in {PRICING_CONFIRMED, PRICING_NEEDS_CONFIRMATION}:
            continue
        if not result.make or result.make == "Unknown":
            continue
        label = result.label or f"{result.make}_{result.model}"
        confident[label] = confident.get(label, 0) + 1

    if len(confident) < 2:
        return None

    parts = [
        f"{label.replace('_', ' ')} ({count} image{'s' if count != 1 else ''})"
        for label, count in sorted(confident.items(), key=lambda item: -item[1])
    ]
    return (
        "Per-image vehicle identities are inconsistent across this claim "
        f"({'; '.join(parts)}). Surveyor must confirm the vehicle before "
        "pricing is treated as final."
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
            identity_confirmed=False,
            margin=0.0,
            pricing_basis=PRICING_PROVISIONAL,
            reliability_tier=None,
        )

    if not get_settings().ml_live:
        return _stub_result()

    results = [classify_image(path) for path in paths]
    confirmed = [r for r in results if r.identity_confirmed]
    if confirmed:
        return max(confirmed, key=lambda item: item.confidence)
    needs = [r for r in results if r.pricing_basis == PRICING_NEEDS_CONFIRMATION]
    if needs:
        return max(needs, key=lambda item: item.confidence)
    return max(results, key=lambda item: item.confidence)


def classify_claim_images_audited(
    paths: list[Path],
) -> tuple[VmmrResult, list[VmmrResult], str | None]:
    """Return claim aggregate, per-image results, and optional inconsistency note."""
    if not paths:
        empty = classify_claim_images(paths)
        return empty, [], None
    if not get_settings().ml_live:
        stub = _stub_result()
        return stub, [stub], None

    results = [classify_image(path) for path in paths]
    aggregate = classify_claim_images(paths)
    inconsistency = detect_identity_inconsistency(results)
    return aggregate, results, inconsistency
