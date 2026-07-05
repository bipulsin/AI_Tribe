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

# VehiDE VIA JSON uses romanized Vietnamese region class codes (see KSE 2023 paper).
VEHIDE_VIETNAMESE_CODES: dict[str, str | None] = {
    "tray_son": "scratch",  # paint scratch / scuff
    "mop_lom": "dent",  # dent / deformation
    "rach": "scratch",  # tear — nearest app class
    "vo_kinh": "glass_shatter",  # broken glass
    "be_den": "lamp_broken",  # broken lamp
    "thung": "crack",  # puncture / perforation
    "mat_bo_phan": None,  # lost part — no app enum
}

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


def normalize_vehide_code(code: str) -> str | None:
    key = code.strip().lower().replace("-", "_")
    if key in VEHIDE_VIETNAMESE_CODES:
        return VEHIDE_VIETNAMESE_CODES[key]
    return normalize_label(key)


def normalize_label(raw: str) -> str | None:
    key = raw.strip().lower().replace("_", " ")
    key = " ".join(key.split())
    if key.replace(" ", "_") in VEHIDE_VIETNAMESE_CODES:
        return VEHIDE_VIETNAMESE_CODES[key.replace(" ", "_")]
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
