"""Image quality gate: blur, glare, and minimum resolution checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MIN_WIDTH = 480
MIN_HEIGHT = 360
BLUR_VARIANCE_MIN = 60.0
GLARE_RATIO_MAX = 0.22


@dataclass
class QualityResult:
    passed: bool
    reasons: list[str]
    blur_score: float
    glare_ratio: float
    width: int
    height: int

    @property
    def detail(self) -> str:
        if self.passed:
            return (
                f"Quality OK ({self.width}×{self.height}, "
                f"sharpness {self.blur_score:.0f})."
            )
        return "; ".join(self.reasons)


def check_image_quality(path: Path) -> QualityResult:
    image = cv2.imread(str(path))
    if image is None:
        return QualityResult(
            passed=False,
            reasons=["Image could not be decoded."],
            blur_score=0.0,
            glare_ratio=0.0,
            width=0,
            height=0,
        )

    height, width = image.shape[:2]
    reasons: list[str] = []

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        reasons.append(
            f"Resolution {width}×{height} is below the {MIN_WIDTH}×{MIN_HEIGHT} minimum."
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < BLUR_VARIANCE_MIN:
        reasons.append("Image appears too blurry for reliable assessment.")

    # Glare: fraction of near-saturated pixels.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    glare_mask = (hsv[:, :, 2] >= 245) & (hsv[:, :, 1] <= 40)
    glare_ratio = float(np.count_nonzero(glare_mask)) / float(gray.size)
    if glare_ratio > GLARE_RATIO_MAX:
        reasons.append("Strong glare or overexposure detected.")

    return QualityResult(
        passed=not reasons,
        reasons=reasons,
        blur_score=blur_score,
        glare_ratio=glare_ratio,
        width=width,
        height=height,
    )


def check_claim_images(paths: list[Path]) -> tuple[bool, str, list[QualityResult]]:
    if not paths:
        return False, "No images available for quality checks.", []

    results = [check_image_quality(path) for path in paths]
    failed = [r for r in results if not r.passed]
    if failed:
        return False, failed[0].detail, results
    return True, results[0].detail, results
