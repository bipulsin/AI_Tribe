"""Claim creation and reference generation."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Claim, ClaimImage
from app.models.enums import AuthenticityVerdict, ClaimStatus
from app.services.storage import StorageBackend, get_storage

IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}
VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
}


class ClaimValidationError(ValueError):
    pass


def _is_image(upload: UploadFile) -> bool:
    content_type = (upload.content_type or "").lower()
    if content_type in IMAGE_CONTENT_TYPES:
        return True
    name = (upload.filename or "").lower()
    return name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))


def _is_video(upload: UploadFile) -> bool:
    content_type = (upload.content_type or "").lower()
    if content_type in VIDEO_CONTENT_TYPES:
        return True
    name = (upload.filename or "").lower()
    return name.endswith((".mp4", ".webm", ".mov", ".avi"))


async def _read_validated(
    upload: UploadFile,
    *,
    kind: str,
    max_bytes: int,
    max_upload_mb: int,
) -> tuple[str, bytes]:
    filename = upload.filename or (f"upload.{'mp4' if kind == 'video' else 'jpg'}")
    data = await upload.read()
    if not data:
        raise ClaimValidationError(f"'{filename}' is empty.")
    if len(data) > max_bytes:
        raise ClaimValidationError(
            f"'{filename}' exceeds the {max_upload_mb} MB limit."
        )
    return filename, data


async def create_claim_with_uploads(
    db: Session,
    *,
    user_id: int,
    images: list[UploadFile],
    video: UploadFile | None = None,
    garage_id: int | None = None,
    surveyor_name: str | None = None,
    claimant_name: str | None = None,
    accident_date: date | None = None,
    storage: StorageBackend | None = None,
) -> Claim:
    settings = get_settings()
    storage = storage or get_storage()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    image_files = [f for f in images if f and f.filename]
    if not image_files:
        raise ClaimValidationError("Add at least one image to submit a claim.")
    if len(image_files) > settings.max_images_per_claim:
        raise ClaimValidationError(
            f"A claim can include at most {settings.max_images_per_claim} images."
        )

    for upload in image_files:
        if not _is_image(upload):
            raise ClaimValidationError(
                f"'{upload.filename}' is not a supported image type."
            )

    video_file = video if video and video.filename else None
    if video_file and not _is_video(video_file):
        raise ClaimValidationError(
            f"'{video_file.filename}' is not a supported video type."
        )

    # Read and validate all payloads before touching the database or disk.
    image_payloads: list[tuple[str, bytes]] = []
    for upload in image_files:
        image_payloads.append(
            await _read_validated(
                upload,
                kind="image",
                max_bytes=max_bytes,
                max_upload_mb=settings.max_upload_mb,
            )
        )

    video_payload: tuple[str, bytes] | None = None
    if video_file:
        video_payload = await _read_validated(
            video_file,
            kind="video",
            max_bytes=max_bytes,
            max_upload_mb=settings.max_upload_mb,
        )

    claim = Claim(
        claim_reference="PENDING",
        created_by=user_id,
        garage_id=garage_id,
        surveyor_name=(surveyor_name or "").strip() or None,
        claimant_name=(claimant_name or "").strip() or None,
        accident_date=accident_date,
        status=ClaimStatus.submitted,
    )
    db.add(claim)
    db.flush()

    year = datetime.now(timezone.utc).year
    claim.claim_reference = f"CLM-{year}-{claim.id:06d}"

    order = 1
    for filename, data in image_payloads:
        relative = storage.save_bytes(data, claim.id, filename)
        db.add(
            ClaimImage(
                claim_id=claim.id,
                file_path=relative,
                image_order=order,
                is_video=False,
                authenticity_verdict=AuthenticityVerdict.pending,
            )
        )
        order += 1

    if video_payload:
        filename, data = video_payload
        relative = storage.save_bytes(data, claim.id, filename)
        db.add(
            ClaimImage(
                claim_id=claim.id,
                file_path=relative,
                image_order=order,
                is_video=True,
                authenticity_verdict=AuthenticityVerdict.pending,
            )
        )

    db.commit()
    db.refresh(claim)
    return claim
