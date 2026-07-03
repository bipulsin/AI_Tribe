"""Error Level Analysis (ELA) for JPEG recompression artefacts."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

ELA_QUALITY = 90
# Mean residual is the primary signal; peak alone is noisy on textured photos.
ELA_MEAN_THRESHOLD = 18.0
ELA_MAX_THRESHOLD = 90.0


@dataclass
class ElaResult:
    mean_diff: float
    max_diff: float
    anomalous: bool
    detail: str


def run_ela(path: Path) -> ElaResult:
    with Image.open(path) as original:
        rgb = original.convert("RGB")

    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=ELA_QUALITY)
    buffer.seek(0)
    resaved = Image.open(buffer).convert("RGB")

    orig_arr = np.asarray(rgb, dtype=np.float32)
    resa_arr = np.asarray(resaved, dtype=np.float32)
    diff = np.abs(orig_arr - resa_arr)
    mean_diff = float(diff.mean())
    max_diff = float(diff.max())

    anomalous = mean_diff > ELA_MEAN_THRESHOLD and max_diff > ELA_MAX_THRESHOLD
    if anomalous:
        detail = (
            f"ELA highlighted uneven compression (mean {mean_diff:.1f}, "
            f"peak {max_diff:.1f})."
        )
    else:
        detail = f"ELA within expected range (mean {mean_diff:.1f})."

    return ElaResult(
        mean_diff=mean_diff,
        max_diff=max_diff,
        anomalous=anomalous,
        detail=detail,
    )


def run_ela_on_paths(paths: list[Path]) -> tuple[bool, str]:
    if not paths:
        return True, "No images for ELA."

    results = [run_ela(path) for path in paths]
    anomalous = [r for r in results if r.anomalous]
    if anomalous:
        return False, anomalous[0].detail
    return True, results[0].detail
