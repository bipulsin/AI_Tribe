"""Label normalization for CarDD / VehiDE evaluation vs app DamageType enum."""

from __future__ import annotations

# CarDD + beingamit99 six-class set
CARDD_CLASS_NAMES = (
    "dent",
    "scratch",
    "crack",
    "glass shatter",
    "lamp broken",
    "tire flat",
)

# VehiDE adds categories beyond CarDD; map to nearest app class or None to skip.
VEHIDE_TO_APP: dict[str, str | None] = {
    "dent": "dent",
    "scratch": "scratch",
    "crack": "crack",
    "glass shatter": "glass_shatter",
    "glass_shatter": "glass_shatter",
    "broken glass": "glass_shatter",
    "lamp broken": "lamp_broken",
    "broken lamp": "lamp_broken",
    "broken_lamp": "lamp_broken",
    "tire flat": "tire_flat",
    "flat tire": "tire_flat",
    "flat_tire": "tire_flat",
    # VehiDE-specific extras — no direct app enum; skip in strict accuracy or map loosely:
    "broken side mirror": None,
    "broken_side_mirror": None,
    "broken mirror": None,
    "severe deform": "dent",
    "severe_deform": "dent",
    "tear": "scratch",
}


def normalize_label(raw: str) -> str | None:
    key = raw.strip().lower().replace("_", " ")
    key = " ".join(key.split())
    if key in {"glass shatter", "glass shatter"}:
        return "glass_shatter"
    mapping = {
        "dent": "dent",
        "scratch": "scratch",
        "crack": "crack",
        "glass shatter": "glass_shatter",
        "lamp broken": "lamp_broken",
        "tire flat": "tire_flat",
    }
    if key in mapping:
        return mapping[key]
    if key in VEHIDE_TO_APP:
        return VEHIDE_TO_APP[key]
    for token, value in VEHIDE_TO_APP.items():
        if token in key:
            return value
    for token, value in mapping.items():
        if token in key:
            return value
    return None
