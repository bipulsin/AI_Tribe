"""Database-backed chat draft state for new-claim submission."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.chat_draft_state import ChatDraftState
from app.services.chat.intent import extract_claim_reference
from app.services.storage import get_storage

_DATE_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
]

_GARAGE_PATTERNS = [
    re.compile(r"garage(?:\s+name)?\s*(?:is|:|-)\s*(.+)", re.IGNORECASE),
    re.compile(r"at\s+(.+?)\s+garage", re.IGNORECASE),
]

_SURVEYOR_PATTERNS = [
    re.compile(r"surveyor(?:\s+name)?\s*(?:is|:|-)\s*(.+)", re.IGNORECASE),
    re.compile(r"surveyor\s+(.+)", re.IGNORECASE),
]

INTERRUPTED_MESSAGE = (
    "Your in-progress claim was interrupted, please start again."
)


@dataclass
class UploadedFile:
    filename: str
    content_type: str
    is_video: bool
    relative_path: str | None = None
    data: bytes | None = None

    def blob_available(self) -> bool:
        if self.data:
            return True
        if not self.relative_path:
            return False
        return _resolve_path(self.relative_path).is_file()


@dataclass
class ClaimDraft:
    images: list[UploadedFile] = field(default_factory=list)
    video: UploadedFile | None = None
    garage_name: str | None = None
    accident_date: str | None = None
    surveyor_name: str | None = None
    active: bool = False
    flow: str = "submit_claim"
    interrupted: bool = False

    def image_count(self) -> int:
        return len(self.images)

    def missing_required(self, *, user_display_name: str) -> list[str]:
        missing: list[str] = []
        if not self.loadable_images():
            missing.append("damage photos")
        if not (self.garage_name or "").strip():
            missing.append("garage name")
        if not (self.accident_date or "").strip():
            missing.append("accident date")
        if not (self.surveyor_name or "").strip():
            # Surveyor can default to the signed-in user later; still track as optional soft miss.
            pass
        return missing

    def next_step(self) -> str:
        """Guided submit step: city → garage → surveyor → date → photos → ready."""
        if not (self.garage_name or "").strip():
            if self.flow in {"await_garage", "await_city"}:
                return self.flow
            return "await_city"
        if not (self.surveyor_name or "").strip():
            return "await_surveyor"
        if not (self.accident_date or "").strip():
            return "await_date"
        if not self.loadable_images():
            return "await_photos"
        return "ready"

    def loadable_images(self) -> list[UploadedFile]:
        return [img for img in self.images if img.blob_available()]

    def blobs_missing(self) -> bool:
        if not self.images and not self.video:
            return False
        if self.images and not self.loadable_images():
            return True
        if self.video and not self.video.blob_available():
            return True
        return False


def _draft_dir(user_id: int) -> Path:
    root = get_settings().upload_path / "chat_drafts" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_path(relative_path: str) -> Path:
    return get_storage().resolve(relative_path)


def _save_blob(user_id: int, filename: str, data: bytes) -> str:
    safe_name = Path(filename).name
    unique = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    dest = _draft_dir(user_id) / unique
    dest.write_bytes(data)
    return f"chat_drafts/{user_id}/{unique}"


def _delete_blob(relative_path: str) -> None:
    path = _resolve_path(relative_path)
    if path.is_file():
        path.unlink(missing_ok=True)


def _clear_user_files(user_id: int) -> None:
    draft_dir = get_settings().upload_path / "chat_drafts" / str(user_id)
    if draft_dir.is_dir():
        for path in draft_dir.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
        try:
            draft_dir.rmdir()
        except OSError:
            pass


def _files_to_payload(draft: ClaimDraft) -> dict:
    images = [
        {
            "path": img.relative_path,
            "filename": img.filename,
            "content_type": img.content_type,
        }
        for img in draft.images
        if img.relative_path
    ]
    video = None
    if draft.video and draft.video.relative_path:
        video = {
            "path": draft.video.relative_path,
            "filename": draft.video.filename,
            "content_type": draft.video.content_type,
        }
    return {"images": images, "video": video}


def _load_uploaded_file(meta: dict, *, is_video: bool) -> UploadedFile:
    relative_path = meta.get("path")
    blob = UploadedFile(
        filename=str(meta.get("filename") or "upload.jpg"),
        content_type=str(meta.get("content_type") or "application/octet-stream"),
        is_video=is_video,
        relative_path=relative_path,
    )
    if relative_path and blob.blob_available():
        blob.data = _resolve_path(relative_path).read_bytes()
    return blob


def persist_draft(db: Session, user_id: int, draft: ClaimDraft) -> None:
    row = db.scalar(select(ChatDraftState).where(ChatDraftState.user_id == user_id))
    if not row:
        row = ChatDraftState(user_id=user_id)
        db.add(row)
    row.flow = draft.flow or "submit_claim"
    row.active = draft.active
    row.garage_name = (draft.garage_name or "").strip() or None
    row.accident_date = (draft.accident_date or "").strip() or None
    row.surveyor_name = (draft.surveyor_name or "").strip() or None
    row.uploaded_files = _files_to_payload(draft)
    db.commit()


def get_draft(db: Session, user_id: int) -> ClaimDraft:
    row = db.scalar(select(ChatDraftState).where(ChatDraftState.user_id == user_id))
    if not row or not row.active:
        return ClaimDraft(active=False)

    payload = row.uploaded_files or {}
    images = [
        _load_uploaded_file(meta, is_video=False)
        for meta in payload.get("images") or []
    ]
    video = None
    if payload.get("video"):
        video = _load_uploaded_file(payload["video"], is_video=True)

    draft = ClaimDraft(
        images=images,
        video=video,
        garage_name=row.garage_name,
        accident_date=row.accident_date,
        surveyor_name=row.surveyor_name,
        active=True,
        flow=row.flow or "submit_claim",
    )
    if draft.blobs_missing():
        draft.interrupted = True
    return draft


def clear_draft(db: Session, user_id: int) -> None:
    row = db.scalar(select(ChatDraftState).where(ChatDraftState.user_id == user_id))
    if row:
        payload = row.uploaded_files or {}
        for meta in payload.get("images") or []:
            if meta.get("path"):
                _delete_blob(meta["path"])
        if payload.get("video") and payload["video"].get("path"):
            _delete_blob(payload["video"]["path"])
        db.delete(row)
        db.commit()
    _clear_user_files(user_id)


def start_draft(db: Session, user_id: int) -> ClaimDraft:
    clear_draft(db, user_id)
    draft = ClaimDraft(active=True, flow="await_city")
    persist_draft(db, user_id, draft)
    return draft


def activate_draft(db: Session, user_id: int) -> ClaimDraft:
    """Ensure an active submit draft without wiping already-uploaded files."""
    draft = get_draft(db, user_id)
    if draft.interrupted:
        clear_draft(db, user_id)
        draft = ClaimDraft(active=False)
    if draft.active:
        if not draft.flow or draft.flow == "submit_claim":
            draft.flow = "await_city" if not (draft.garage_name or "").strip() else draft.flow
            persist_draft(db, user_id, draft)
        return draft
    draft = ClaimDraft(active=True, flow="await_city")
    persist_draft(db, user_id, draft)
    return draft


def _clean_tail(value: str) -> str:
    text = value.strip().strip(".,;")
    for stop in (" accident", " date", " surveyor", " and "):
        idx = text.lower().find(stop)
        if idx > 0:
            text = text[:idx]
    return text.strip().rstrip(",")


def parse_accident_date(raw: str | None) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_details_from_text(db: Session, user_id: int, draft: ClaimDraft, text: str) -> ClaimDraft:
    raw = (text or "").strip()
    if not raw or extract_claim_reference(raw):
        return draft

    step = draft.next_step()
    lower = raw.lower()

    # Explicit labelled fields always apply.
    for pattern in _GARAGE_PATTERNS:
        match = pattern.search(raw)
        if match:
            draft.garage_name = _clean_tail(match.group(1))[:128]
            draft.flow = "await_surveyor"
            break

    for pattern in _SURVEYOR_PATTERNS:
        match = pattern.search(raw)
        if match:
            draft.surveyor_name = _clean_tail(match.group(1))[:128]
            break

    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw)
        if match:
            draft.accident_date = match.group(1)
            break

    # Step-aware free-text capture.
    if step == "await_garage" and not draft.garage_name:
        draft.garage_name = raw[:128]
        draft.flow = "await_surveyor"
    elif step == "await_surveyor" and not draft.surveyor_name:
        if lower in {"me", "myself", "i am", "i'm the surveyor", "same"}:
            draft.surveyor_name = "__self__"
        else:
            draft.surveyor_name = raw[:128]
        draft.flow = "await_date"
    elif step == "await_date" and not draft.accident_date:
        # Accept free-form date strings; parse_accident_date validates later.
        draft.accident_date = raw[:32]
        draft.flow = "await_photos"
    elif step in {"await_city", "submit_claim"} and not draft.garage_name:
        # Heuristic garage only when clearly not a city-only reply.
        from app.services.chat.intent import extract_city_from_text

        if not extract_city_from_text(raw) and "garage" not in lower:
            looks_like_question = (
                "?" in raw
                or lower.startswith(("what ", "how ", "why ", "when ", "where ", "who "))
            )
            if (
                len(raw) < 80
                and "surveyor" not in lower
                and "@" not in raw
                and not looks_like_question
                and draft.image_count() > 0
            ):
                draft.garage_name = raw[:128]

    persist_draft(db, user_id, draft)
    return draft


def append_files(
    db: Session,
    user_id: int,
    draft: ClaimDraft,
    *,
    images: list[tuple[str, bytes, str]],
    video: tuple[str, bytes, str] | None,
) -> ClaimDraft:
    if not draft.active:
        draft.active = True
        draft.flow = "await_city"

    max_images = get_settings().max_images_per_claim
    for filename, data, content_type in images:
        if len(draft.images) >= max_images:
            break
        relative_path = _save_blob(user_id, filename, data)
        draft.images.append(
            UploadedFile(
                filename=filename,
                content_type=content_type,
                is_video=False,
                relative_path=relative_path,
                data=data,
            )
        )

    if video and draft.video is None:
        filename, data, content_type = video
        relative_path = _save_blob(user_id, filename, data)
        draft.video = UploadedFile(
            filename=filename,
            content_type=content_type,
            is_video=True,
            relative_path=relative_path,
            data=data,
        )

    persist_draft(db, user_id, draft)
    return draft


def ensure_blob_data(draft: ClaimDraft) -> ClaimDraft:
    for img in draft.images:
        if not img.data and img.relative_path and img.blob_available():
            img.data = _resolve_path(img.relative_path).read_bytes()
    if draft.video and not draft.video.data and draft.video.relative_path:
        if draft.video.blob_available():
            draft.video.data = _resolve_path(draft.video.relative_path).read_bytes()
    if draft.blobs_missing():
        draft.interrupted = True
    return draft
