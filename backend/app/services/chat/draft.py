"""In-memory new-claim draft state per user (chat flow)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime

from app.services.chat.intent import extract_claim_reference

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


@dataclass
class UploadedFile:
    filename: str
    data: bytes
    content_type: str
    is_video: bool


@dataclass
class ClaimDraft:
    images: list[UploadedFile] = field(default_factory=list)
    video: UploadedFile | None = None
    garage_name: str | None = None
    accident_date: str | None = None
    surveyor_name: str | None = None
    active: bool = False

    def image_count(self) -> int:
        return len(self.images)

    def missing_required(self, *, user_display_name: str) -> list[str]:
        missing: list[str] = []
        if not self.images:
            missing.append("at least one damage photo")
        if not (self.garage_name or "").strip():
            missing.append("garage name")
        return missing


_lock = threading.Lock()
_drafts: dict[int, ClaimDraft] = {}


def get_draft(user_id: int) -> ClaimDraft:
    with _lock:
        draft = _drafts.get(user_id)
        if draft is None:
            draft = ClaimDraft()
            _drafts[user_id] = draft
        return draft


def clear_draft(user_id: int) -> None:
    with _lock:
        _drafts.pop(user_id, None)


def start_draft(user_id: int) -> ClaimDraft:
    with _lock:
        draft = ClaimDraft(active=True)
        _drafts[user_id] = draft
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


def parse_details_from_text(draft: ClaimDraft, text: str) -> None:
    raw = (text or "").strip()
    if not raw or extract_claim_reference(raw):
        return

    for pattern in _GARAGE_PATTERNS:
        match = pattern.search(raw)
        if match and not draft.garage_name:
            draft.garage_name = _clean_tail(match.group(1))[:128]
            break

    if not draft.garage_name and "garage" not in raw.lower():
        if (
            len(raw) < 80
            and not draft.surveyor_name
            and "surveyor" not in raw.lower()
            and draft.image_count() > 0
            and "@" not in raw
        ):
            draft.garage_name = raw[:128]

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
