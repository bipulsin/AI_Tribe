"""Cross-image sensor-noise consistency within a single claim.

This is NOT full PRNU device attribution (that needs a reference fingerprint
built from many known photos of one camera). It only answers: do this claim's
images share a similar high-frequency noise residual, or does one look like it
came from a different source than the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

# Resize residuals to a fixed grid so correlations are comparable.
RESIDUAL_SIZE = (256, 256)
# Leave-one-out correlation more than this many stds below the claim mean → outlier.
OUTLIER_STD_THRESHOLD = 2.0
# For two-image claims, std is undefined; use an absolute correlation floor.
PAIR_CORRELATION_MIN = 0.12
# Minimum images required for a meaningful check.
MIN_IMAGES = 2


@dataclass
class ImageSensorScore:
    path: Path
    correlation: float
    is_outlier: bool


@dataclass
class SensorConsistencyResult:
    consistent: bool
    scores: list[ImageSensorScore]
    mean_correlation: float | None
    std_correlation: float | None
    detail: str


def _load_gray(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        # Fallback for paths OpenCV cannot imdecode via buffer
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return img


def noise_residual(path: Path) -> np.ndarray | None:
    """High-pass noise residual: image minus Gaussian-smoothed image."""
    img = _load_gray(path)
    if img is None or img.size == 0:
        return None
    img = cv2.resize(img, RESIDUAL_SIZE, interpolation=cv2.INTER_AREA)
    img_f = img.astype(np.float32) / 255.0
    blur = cv2.GaussianBlur(img_f, (0, 0), sigmaX=1.0)
    residual = img_f - blur
    residual = residual - float(residual.mean())
    norm = float(np.linalg.norm(residual))
    if norm < 1e-8:
        return None
    return (residual / norm).reshape(-1)


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a0 = a - a.mean()
    b0 = b - b.mean()
    denom = float(np.linalg.norm(a0) * np.linalg.norm(b0))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a0, b0) / denom)


def check_paths(paths: list[Path]) -> SensorConsistencyResult:
    """Compare each image residual to the leave-one-out claim average."""
    usable = [path for path in paths if path.exists() and not _is_video(path)]
    if len(usable) < MIN_IMAGES:
        return SensorConsistencyResult(
            consistent=True,
            scores=[],
            mean_correlation=None,
            std_correlation=None,
            detail=(
                "Sensor consistency not assessed — needs at least two still photos. "
                "This is a within-claim noise-residual check, not full PRNU device attribution."
            ),
        )

    residuals: list[tuple[Path, np.ndarray]] = []
    for path in usable:
        residual = noise_residual(path)
        if residual is not None:
            residuals.append((path, residual))

    if len(residuals) < MIN_IMAGES:
        return SensorConsistencyResult(
            consistent=True,
            scores=[],
            mean_correlation=None,
            std_correlation=None,
            detail=(
                "Sensor consistency not assessed — could not extract noise residuals "
                "from enough photos. This is not full PRNU device attribution."
            ),
        )

    correlations: list[float] = []
    for index, (path, residual) in enumerate(residuals):
        others = [r for j, (_p, r) in enumerate(residuals) if j != index]
        average = np.mean(np.stack(others, axis=0), axis=0)
        correlations.append(_pearson(residual, average))

    mean_corr = float(np.mean(correlations))
    std_corr = float(np.std(correlations, ddof=1)) if len(correlations) >= 3 else None

    scores: list[ImageSensorScore] = []
    outliers: list[str] = []

    if len(correlations) == 2:
        # Pairwise leave-one-out correlations are identical; use absolute floor.
        pair_corr = correlations[0]
        is_outlier = pair_corr < PAIR_CORRELATION_MIN
        for (path, _residual), corr in zip(residuals, correlations):
            scores.append(
                ImageSensorScore(
                    path=path, correlation=corr, is_outlier=is_outlier
                )
            )
        if is_outlier:
            outliers = [residuals[0][0].name, residuals[1][0].name]
    else:
        # Compare each score to the mean/std of the *other* scores so a single
        # low outlier cannot inflate the spread and hide itself.
        for index, ((path, _residual), corr) in enumerate(
            zip(residuals, correlations)
        ):
            peers = [c for j, c in enumerate(correlations) if j != index]
            peer_mean = float(np.mean(peers))
            peer_std = (
                float(np.std(peers, ddof=1)) if len(peers) >= 2 else 0.0
            )
            if peer_std < 1e-6:
                flagged = corr < peer_mean - 0.25
            else:
                flagged = corr < peer_mean - OUTLIER_STD_THRESHOLD * peer_std
            scores.append(
                ImageSensorScore(path=path, correlation=corr, is_outlier=flagged)
            )
            if flagged:
                outliers.append(path.name)

    if outliers:
        corr_bits = ", ".join(
            f"{score.path.name}={score.correlation:.2f}" for score in scores
        )
        detail = (
            f"Inconsistent, review recommended — noise residuals diverge within this claim "
            f"(outlier(s): {', '.join(outliers)}; leave-one-out correlations: {corr_bits}). "
            "This is a within-claim sensor-noise consistency check, not full PRNU "
            "device attribution against a known camera fingerprint."
        )
        return SensorConsistencyResult(
            consistent=False,
            scores=scores,
            mean_correlation=mean_corr,
            std_correlation=std_corr,
            detail=detail,
        )

    corr_bits = ", ".join(f"{score.correlation:.2f}" for score in scores)
    detail = (
        f"Consistent — noise residuals align across {len(scores)} photos "
        f"(leave-one-out correlations: {corr_bits}; mean={mean_corr:.2f}). "
        "Within-claim check only; not full PRNU device attribution."
    )
    return SensorConsistencyResult(
        consistent=True,
        scores=scores,
        mean_correlation=mean_corr,
        std_correlation=std_corr,
        detail=detail,
    )


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".webm", ".mov", ".m4v"}
