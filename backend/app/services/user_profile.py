"""User profile photo storage (disk) and field helpers."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User

logger = logging.getLogger("ai_tribe.profile")

ALLOWED_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def profile_photo_dir() -> Path:
    path = get_settings().profile_photos_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_photo_path(user_id: int) -> Path | None:
    root = profile_photo_dir()
    for suffix in ALLOWED_PHOTO_SUFFIXES:
        candidate = root / f"{user_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def has_profile_photo(user_id: int) -> bool:
    return profile_photo_path(user_id) is not None


def delete_profile_photo(user_id: int) -> None:
    for suffix in ALLOWED_PHOTO_SUFFIXES:
        path = profile_photo_dir() / f"{user_id}{suffix}"
        if path.is_file():
            path.unlink()


def save_profile_photo(user_id: int, data: bytes, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_PHOTO_SUFFIXES:
        suffix = ".jpg"

    max_bytes = get_settings().max_profile_photo_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"Photo must be under {get_settings().max_profile_photo_mb} MB")

    delete_profile_photo(user_id)
    dest = profile_photo_dir() / f"{user_id}.jpg"

    # Normalize and strip metadata via Pillow re-encode.
    from io import BytesIO

    with Image.open(BytesIO(data)) as img:
        rgb = img.convert("RGB")
        rgb.save(dest, format="JPEG", quality=88, optimize=True)

    if dest.stat().st_size > max_bytes:
        dest.unlink(missing_ok=True)
        raise ValueError(f"Processed photo exceeds {get_settings().max_profile_photo_mb} MB")

    return dest


def profile_to_dict(user: User) -> dict:
    photo = profile_photo_path(user.id)
    return {
        "username": user.username,
        "full_name": user.full_name,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "has_photo": photo is not None,
        "photo_url": f"/api/user/profile/photo?v={int(photo.stat().st_mtime)}" if photo else None,
        "role": user.role,
    }


def parse_date_of_birth(value: str | None) -> date | None:
    if not value or not str(value).strip():
        return None
    return date.fromisoformat(str(value).strip())
