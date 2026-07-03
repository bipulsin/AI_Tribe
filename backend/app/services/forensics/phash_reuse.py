"""Perceptual hash duplicate / reuse detection across historical claims."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClaimImage

# Hamming distance threshold for near-duplicate phash matches.
PHASH_DISTANCE_MAX = 6


@dataclass
class PhashResult:
    phash: str
    reused: bool
    matched_claim_id: int | None
    detail: str


def compute_phash(path: Path) -> str:
    with Image.open(path) as img:
        return str(imagehash.phash(img.convert("RGB")))


def _hamming(a: str, b: str) -> int:
    try:
        return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)
    except Exception:
        return 64


def check_reuse(
    db: Session,
    *,
    claim_id: int,
    image_id: int,
    path: Path,
) -> PhashResult:
    phash = compute_phash(path)

    prior = db.scalars(
        select(ClaimImage).where(
            ClaimImage.phash.is_not(None),
            ClaimImage.claim_id != claim_id,
            ClaimImage.is_video.is_(False),
        )
    ).all()

    for row in prior:
        if not row.phash:
            continue
        distance = _hamming(phash, row.phash)
        if distance <= PHASH_DISTANCE_MAX:
            return PhashResult(
                phash=phash,
                reused=True,
                matched_claim_id=row.claim_id,
                detail=(
                    f"Image closely matches a photo from claim #{row.claim_id} "
                    f"(perceptual distance {distance})."
                ),
            )

    return PhashResult(
        phash=phash,
        reused=False,
        matched_claim_id=None,
        detail="No reused images found in prior claims.",
    )


def check_claim_reuse(
    db: Session,
    *,
    claim_id: int,
    images: list[tuple[ClaimImage, Path]],
) -> tuple[bool, str]:
    if not images:
        return True, "No images for duplicate checks."

    details: list[str] = []
    for image_row, path in images:
        result = check_reuse(
            db, claim_id=claim_id, image_id=image_row.id, path=path
        )
        image_row.phash = result.phash
        if result.reused:
            db.commit()
            return False, result.detail
        details.append(result.detail)

    db.commit()
    return True, details[0]
