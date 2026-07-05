"""Vision-assisted make/model guess for lab labeling (optional OpenAI, else local VMMR)."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.services.vmmr import vmmr_classifier

logger = logging.getLogger("ai_tribe.vmmr.lab_labeling")

_CATALOG_HINT = (
    "Maruti Swift, Maruti Baleno, Hyundai i20, Hyundai Creta, Tata Nexon, "
    "Honda City, Mahindra XUV700, Mahindra XUV500, Kia Seltos, Toyota Innova, "
    "Renault Kwid"
)


@dataclass
class LabelGuess:
    suggested_make: str
    suggested_model: str
    suggested_confidence: float
    guess_source: str
    guess_detail: str
    alternatives: list[dict]


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _openai_vision_guess(path: Path) -> LabelGuess | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
    with path.open("rb") as fh:
        b64 = base64.standard_b64encode(fh.read()).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix

    prompt = (
        "Identify the passenger vehicle make and model in this damaged-car photo. "
        "Prefer Indian-market models when plausible. "
        f"Common catalog targets: {_CATALOG_HINT}. "
        "Reply with JSON only: "
        '{"make":"...","model":"...","confidence":0.0,"alternatives":[{"make":"...","model":"...","confidence":0.0}]} '
        "confidence is 0-1. alternatives may be empty."
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 300,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        data = _parse_json_object(content)
        alts = data.get("alternatives") or []
        return LabelGuess(
            suggested_make=str(data.get("make") or "Unknown").strip(),
            suggested_model=str(data.get("model") or "Unknown").strip(),
            suggested_confidence=float(data.get("confidence") or 0.5),
            guess_source="vision_api",
            guess_detail=f"OpenAI {model} vision guess (lab labeling assist only).",
            alternatives=[
                {
                    "make": str(a.get("make", "")).strip(),
                    "model": str(a.get("model", "")).strip(),
                    "confidence": float(a.get("confidence") or 0.0),
                }
                for a in alts
                if a.get("make")
            ],
        )
    except Exception as exc:
        logger.warning("OpenAI vision guess failed for %s: %s", path, exc)
        return None


def _local_vmmr_guess(path: Path) -> LabelGuess:
    guesses = vmmr_classifier.guess_top_k(path, k=5)
    if not guesses:
        return LabelGuess(
            suggested_make="Unknown",
            suggested_model="Unknown",
            suggested_confidence=0.0,
            guess_source="stub",
            guess_detail="No VMMR guess available (ML_MODE=stub or model load failed).",
            alternatives=[],
        )
    top = guesses[0]
    return LabelGuess(
        suggested_make=top.make,
        suggested_model=top.model,
        suggested_confidence=top.confidence,
        guess_source="vmmr_local" if get_settings().ml_live else "stub",
        guess_detail=(
            f"FGVD fine-tuned top-{len(guesses)} guess "
            f"(class {top.class_key}, lab assist only)."
        ),
        alternatives=[
            {
                "make": g.make,
                "model": g.model,
                "confidence": g.confidence,
                "class_key": g.class_key,
            }
            for g in guesses[1:]
        ],
    )


def suggest_make_model(path: Path) -> LabelGuess:
    if not path.is_file():
        raise FileNotFoundError(path)
    vision = _openai_vision_guess(path)
    if vision is not None:
        return vision
    return _local_vmmr_guess(path)
