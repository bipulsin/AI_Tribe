"""LLM assist constants and deepfake ambiguity thresholds."""

from __future__ import annotations

PROVIDERS = ("openai", "anthropic", "gemini", "grok")

TOGGLE_DEEPFAKE = "toggle_deepfake"
TOGGLE_VMMR = "toggle_vmmr"
TOGGLE_ESTIMATION = "toggle_estimation"
TOGGLE_FRAUD = "toggle_fraud"

TOGGLE_LABELS: dict[str, str] = {
    TOGGLE_DEEPFAKE: (
        "Image Deepfake Identification — When the internal deepfake model is "
        "uncertain, ask your configured LLM for a second opinion on whether an "
        "image looks AI-generated or manipulated. Called only when needed."
    ),
    TOGGLE_VMMR: (
        "Vehicle Make & Model Identification — When the internal model can't "
        "confidently identify the vehicle, ask your configured LLM to suggest "
        "a make and model from the photos. Called only when needed."
    ),
    TOGGLE_ESTIMATION: (
        "Damage Assessment & Estimation — Every claim's repair estimate is "
        "cross-checked against your configured LLM's independent estimate. "
        "This runs on every claim, not just uncertain ones, and will use more "
        "of your API quota than the other options."
    ),
    TOGGLE_FRAUD: (
        "Organised Fraud Network Identification — When reviewing a claim's "
        "garage/surveyor network, ask your configured LLM to help interpret "
        "unusual patterns. Called only when needed."
    ),
}

# Internal deepfake halt uses fake_score >= 0.70. Ambiguous band triggers LLM assist.
DEEPFAKE_AMBIGUOUS_FAKE_MIN = 0.35
DEEPFAKE_AMBIGUOUS_FAKE_MAX = 0.69
DEEPFAKE_AMBIGUOUS_MARGIN = 0.15  # |fake - real| below this is ambiguous

LLM_TIMEOUT_SECONDS = 25.0
PRICE_DIVERGENCE_RATIO = 0.20  # surface both catalog and LLM if >20% apart
