"""Shared helpers for loading claim images from storage."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, ClaimImage
from app.services.storage import get_storage


def claim_image_paths(db: Session, claim: Claim) -> list[tuple[ClaimImage, Path]]:
    storage = get_storage()
    rows = db.scalars(
        select(ClaimImage)
        .where(ClaimImage.claim_id == claim.id, ClaimImage.is_video.is_(False))
        .order_by(ClaimImage.image_order.asc())
    ).all()
    results: list[tuple[ClaimImage, Path]] = []
    for row in rows:
        path = storage.resolve(row.file_path)
        if path.exists():
            results.append((row, path))
    return results


def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert("RGB")
