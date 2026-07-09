"""Pipeline LLM assist — optional second opinions with full disclosure logging."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import DamageDetection, LlmAssistLog, Vehicle
from app.services.llm import providers
from app.services.llm.constants import (
    DEEPFAKE_AMBIGUOUS_FAKE_MAX,
    DEEPFAKE_AMBIGUOUS_FAKE_MIN,
    DEEPFAKE_AMBIGUOUS_MARGIN,
    PRICE_DIVERGENCE_RATIO,
    TOGGLE_DEEPFAKE,
    TOGGLE_ESTIMATION,
    TOGGLE_FRAUD,
    TOGGLE_VMMR,
)
from app.services.llm.settings import get_active_api_key, toggle_enabled

logger = logging.getLogger("ai_tribe.llm.assist")

_CATALOG_HINT = (
    "Maruti Swift, Maruti Baleno, Hyundai i20, Hyundai Creta, Tata Nexon, "
    "Honda City, Mahindra XUV700, Mahindra XUV500, Kia Seltos, Toyota Innova"
)


def is_deepfake_ambiguous(fake_score: float, real_score: float) -> bool:
    """True when internal deepfake scores fall in the documented ambiguous band."""
    if fake_score < DEEPFAKE_AMBIGUOUS_FAKE_MIN or fake_score > DEEPFAKE_AMBIGUOUS_FAKE_MAX:
        return False
    return abs(fake_score - real_score) < DEEPFAKE_AMBIGUOUS_MARGIN


def log_assist(
    db: Session,
    *,
    claim_id: int,
    user_id: int,
    stage: str,
    provider: str,
    agreed: bool | None,
    summary: str,
) -> None:
    row = LlmAssistLog(
        claim_id=claim_id,
        user_id=user_id,
        stage=stage,
        provider=provider,
        agreed_with_internal=agreed,
        summary=summary[:4000],
    )
    db.add(row)
    db.commit()


def get_llm_context(db: Session, user_id: int, toggle_name: str) -> tuple[str, str] | None:
    """Return (provider, api_key) when the toggle is on and a valid key exists."""
    if not toggle_enabled(db, user_id, toggle_name):
        return None
    ctx = get_active_api_key(db, user_id)
    if not ctx:
        return None
    return ctx


def _provider_label(provider: str) -> str:
    return provider.replace("_", " ").title()


def assist_deepfake(
    db: Session,
    *,
    claim_id: int,
    user_id: int,
    image_path: Path,
    internal_fake: bool,
    internal_detail: str,
    fake_score: float,
    real_score: float,
) -> str | None:
    """Return an optional detail suffix when LLM assist adds a second opinion."""
    if not is_deepfake_ambiguous(fake_score, real_score):
        return None

    ctx = get_llm_context(db, user_id, TOGGLE_DEEPFAKE)
    if not ctx:
        return None

    provider, api_key = ctx
    path = Path(image_path)
    if not path.is_file():
        return None

    prompt = (
        "You are assisting an insurance claim image authenticity review. "
        "Assess whether this vehicle damage photo shows signs of AI generation, "
        "synthetic manipulation, or heavy editing. "
        "Reply in 1-2 short sentences. State clearly if you believe the image "
        "looks authentic, suspicious, or likely AI-generated/manipulated."
    )
    reply = providers.chat_vision(provider, api_key, prompt, [path], max_tokens=200)
    if not reply:
        return None

    reply_l = reply.lower()
    llm_fake = any(
        token in reply_l
        for token in ("ai-generated", "ai generated", "synthetic", "manipulated", "deepfake", "fake")
    )
    llm_real = any(
        token in reply_l
        for token in ("authentic", "genuine", "real photo", "looks real", "not ai")
    )
    if llm_fake and not llm_real:
        llm_verdict_fake = True
    elif llm_real and not llm_fake:
        llm_verdict_fake = False
    else:
        llm_verdict_fake = None

    agreed = llm_verdict_fake is None or llm_verdict_fake == internal_fake
    log_assist(
        db,
        claim_id=claim_id,
        user_id=user_id,
        stage="deepfake_check",
        provider=provider,
        agreed=agreed,
        summary=(
            f"Internal: {'fake' if internal_fake else 'clear'} ({internal_detail}). "
            f"LLM: {reply.strip()}"
        ),
    )

    label = _provider_label(provider)
    if llm_verdict_fake is None:
        return f" {_label_opinion(label)}: {reply.strip()}"
    if agreed:
        return f" {_label_opinion(label)} agrees with the internal model: {reply.strip()}"
    internal_word = "likely fake/manipulated" if internal_fake else "likely authentic"
    llm_word = "likely fake/manipulated" if llm_verdict_fake else "likely authentic"
    return (
        f" Internal model: {internal_word}. {_label_opinion(label)}: {llm_word}. "
        f"{reply.strip()}"
    )


def _label_opinion(provider_label: str) -> str:
    return f"LLM assist ({provider_label}) opinion"


def assist_vmmr(
    db: Session,
    *,
    claim_id: int,
    user_id: int,
    image_path: Path,
    internal_unreliable: bool,
) -> dict[str, str] | None:
    """Return make/model suggestion when internal VMMR is unreliable."""
    if not internal_unreliable:
        return None

    ctx = get_llm_context(db, user_id, TOGGLE_VMMR)
    if not ctx:
        return None

    provider, api_key = ctx
    path = Path(image_path)
    if not path.is_file():
        return None

    prompt = (
        "Identify the passenger vehicle make and model in this damaged-car photo. "
        "Prefer Indian-market models when plausible. "
        f"Common catalog targets: {_CATALOG_HINT}. "
        "Reply with JSON only: "
        '{"make":"...","model":"...","confidence":0.0,"detail":"one short sentence"} '
        "confidence is 0-1."
    )
    reply = providers.chat_vision(provider, api_key, prompt, [path], max_tokens=300)
    if not reply:
        return None

    try:
        data = providers.parse_json_block(reply)
    except (ValueError, TypeError) as exc:
        logger.warning("VMMR LLM assist JSON parse failed: %s", type(exc).__name__)
        return None

    make = str(data.get("make") or "").strip()
    model = str(data.get("model") or "").strip()
    if not make or not model or make.lower() == "unknown":
        return None

    confidence = float(data.get("confidence") or 0.0)
    detail = str(data.get("detail") or reply).strip()
    log_assist(
        db,
        claim_id=claim_id,
        user_id=user_id,
        stage="vehicle_id",
        provider=provider,
        agreed=None,
        summary=f"LLM suggested {make} {model} (confidence {confidence:.0%}). {detail}",
    )
    return {
        "make": make,
        "model": model,
        "provider": provider,
        "detail": detail,
    }


def _detection_summary(detections: list[DamageDetection]) -> str:
    if not detections:
        return "No internal damage detections."
    lines = []
    for det in detections:
        lines.append(
            f"- {det.part_name}: {det.damage_type.value} ({det.severity.value}), "
            f"{det.repair_or_replace}, confidence {det.confidence_score:.0%}"
        )
    return "\n".join(lines)


def _vehicle_summary(vehicle: Vehicle | None) -> str:
    if vehicle is None:
        return "Vehicle identity unknown."
    parts = [p for p in (vehicle.make, vehicle.model, vehicle.variant) if p]
    label = " ".join(parts) if parts else "unknown vehicle"
    return f"Vehicle: {label} (pricing_basis={vehicle.pricing_basis})."


def assist_estimation(
    db: Session,
    *,
    claim_id: int,
    user_id: int,
    image_paths: list[Path],
    vehicle: Vehicle | None,
    detections: list[DamageDetection],
) -> tuple[list[dict[str, Any]], str] | None:
    """Return optional LLM line suggestions and disclosure text."""
    ctx = get_llm_context(db, user_id, TOGGLE_ESTIMATION)
    if not ctx:
        return None

    provider, api_key = ctx
    paths = [Path(p) for p in image_paths if Path(p).is_file()][:4]
    if not paths:
        return None

    prompt = (
        "You are assisting an insurance repair estimate review for India (INR pricing). "
        f"{_vehicle_summary(vehicle)}\n"
        "Internal damage detections:\n"
        f"{_detection_summary(detections)}\n"
        "From the photos, suggest additional damaged parts the internal model may have missed "
        "and indicative unit prices in INR where you can justify them. "
        "Reply with JSON only:\n"
        '{"lines":[{"part_name":"...","damage_type":"scratch|dent|crack|glass_shatter|lamp_broken|tire_flat",'
        '"severity":"minor|moderate|severe","repair_or_replace":"repair|replace","unit_price_inr":0.0,'
        '"labor_hours":0.0,"notes":"..."}],"summary":"one sentence"}'
    )
    reply = providers.chat_vision(provider, api_key, prompt, paths, max_tokens=1200)
    if not reply:
        return None

    try:
        data = providers.parse_json_block(reply)
    except (ValueError, TypeError) as exc:
        logger.warning("Estimation LLM assist JSON parse failed: %s", type(exc).__name__)
        return None

    raw_lines = data.get("lines") or []
    if not isinstance(raw_lines, list):
        return None

    suggestions: list[dict[str, Any]] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        part_name = str(item.get("part_name") or "").strip()
        if not part_name:
            continue
        suggestions.append(
            {
                "part_name": part_name,
                "damage_type": str(item.get("damage_type") or "scratch").strip(),
                "severity": str(item.get("severity") or "moderate").strip(),
                "repair_or_replace": str(item.get("repair_or_replace") or "repair").strip(),
                "unit_price_inr": float(item.get("unit_price_inr") or 0.0),
                "labor_hours": float(item.get("labor_hours") or 0.0),
                "notes": str(item.get("notes") or "").strip(),
                "price_source": "llm",
                "llm_provider": provider,
            }
        )

    summary = str(data.get("summary") or "LLM supplied an independent repair estimate.").strip()
    log_assist(
        db,
        claim_id=claim_id,
        user_id=user_id,
        stage="estimate_ready",
        provider=provider,
        agreed=None,
        summary=f"{summary} ({len(suggestions)} line suggestion(s)).",
    )

    label = _provider_label(provider)
    disclosure = (
        f"Independent LLM assist ({label}) cross-checked this estimate. "
        f"{summary} "
        f"Where catalog and LLM prices diverge by more than "
        f"{int(PRICE_DIVERGENCE_RATIO * 100)}%, both figures are shown. "
        "LLM-sourced prices are suggestions only, not verified catalogue rates."
    )
    return suggestions, disclosure


def assist_fraud(
    db: Session,
    *,
    claim_id: int,
    user_id: int,
    graph_summary: str,
    flagged: bool,
) -> str | None:
    """Return optional interpretation text when the fraud graph is non-trivial."""
    if not flagged:
        return None

    ctx = get_llm_context(db, user_id, TOGGLE_FRAUD)
    if not ctx:
        return None

    provider, api_key = ctx
    prompt = (
        "You are assisting an insurance fraud analyst reviewing a claimant/garage/surveyor "
        "network graph. The graph summary below lists nodes, edges, and flagged patterns. "
        "In 2-4 calm sentences, explain what might be unusual and what a human reviewer "
        "should check. Do not assert fraud as fact.\n\n"
        f"{graph_summary}"
    )
    reply = providers.chat_text(provider, api_key, prompt, max_tokens=400)
    if not reply:
        return None

    log_assist(
        db,
        claim_id=claim_id,
        user_id=user_id,
        stage="fraud_scoring",
        provider=provider,
        agreed=None,
        summary=reply.strip()[:1000],
    )
    label = _provider_label(provider)
    return f"LLM assist ({label}): {reply.strip()}"
