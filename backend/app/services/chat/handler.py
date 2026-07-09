"""Chat message handling orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.config import get_settings
from app.models import Garage
from app.services.chat.draft import (
    ClaimDraft,
    UploadedFile,
    clear_draft,
    get_draft,
    parse_accident_date,
    parse_details_from_text,
    start_draft,
)
from app.services.chat.intent import classify_intent, extract_claim_reference, llm_classify_intent
from app.services.chat.lookup import format_claim_summary, format_search_hit_list
from app.services.claim_search import is_claim_reference_like, search_claims
from app.services.claim_service import ClaimValidationError, create_claim_with_uploads
from app.services.llm.settings import get_active_api_key
from app.services.pipeline_orchestrator import ensure_pipeline_started
from app.services.vmmr.vehicle_confirmation import catalog_makes_models

_settings = get_settings()

_lookup_awaiting: dict[int, bool] = {}
_lookup_hits: dict[int, list] = {}


@dataclass
class ChatReply:
    role: str = "assistant"
    text: str = ""
    widgets: list[dict[str, Any]] = field(default_factory=list)


def _display_name(full_name: str | None, username: str | None) -> str:
    return (full_name or username or "there").strip() or "there"


def _bytes_upload(blob) -> UploadFile:
    return UploadFile(
        file=BytesIO(blob.data),
        filename=blob.filename,
        headers=Headers({"content-type": blob.content_type or "application/octet-stream"}),
    )


def _llm_classifier(db: Session, user_id: int):
    ctx = get_active_api_key(db, user_id)
    if not ctx:
        return None

    provider, api_key = ctx

    def _classify(text: str):
        return llm_classify_intent(provider, api_key, text)

    return _classify


def _resolve_lookup_query(text: str, entities: dict) -> str:
    ref = entities.get("claim_reference") or extract_claim_reference(text)
    if ref:
        return ref
    stripped = (text or "").strip()
    if re.fullmatch(r"\d{1,2}", stripped):
        return stripped
    return stripped


_VAGUE_LOOKUP_PHRASES = (
    "find my claim",
    "get details",
    "claim status",
    "look up a claim",
    "lookup a claim",
    "details of a claim",
    "about a claim",
    "existing claim",
)


def _is_vague_lookup(query: str, *, ref: str | None) -> bool:
    if ref:
        return False
    q = (query or "").strip().lower()
    if not q or is_claim_reference_like(q):
        return False
    if q in _VAGUE_LOOKUP_PHRASES:
        return True
    if "claim" in q and any(word in q for word in ("detail", "status", "find", "look")):
        tokens = [t for t in re.split(r"\W+", q) if t]
        if len(tokens) <= 5 and not any(t.isdigit() for t in tokens):
            return True
    return False


def handle_lookup(
    db: Session,
    user_id: int,
    text: str,
    entities: dict,
    *,
    force: bool = False,
) -> ChatReply:
    query = _resolve_lookup_query(text, entities)
    ref_only = entities.get("claim_reference") or extract_claim_reference(text)

    if not force and _is_vague_lookup(query, ref=ref_only):
        _lookup_awaiting[user_id] = True
        return ChatReply(
            text=(
                "I can look that up — please share the claim reference (e.g. CLM-2026-000017), "
                "garage name, or surveyor name."
            )
        )

    if not force and not query and not _lookup_awaiting.get(user_id):
        _lookup_awaiting[user_id] = True
        return ChatReply(
            text=(
                "I can look that up — please share the claim reference (e.g. CLM-2026-000017), "
                "garage name, or surveyor name."
            )
        )

    if not query:
        _lookup_awaiting[user_id] = True
        return ChatReply(
            text="Please provide a claim reference, garage name, or surveyor name to search."
        )

    _lookup_awaiting[user_id] = False

    if re.fullmatch(r"\d{1,2}", query):
        pending = _lookup_hits.get(user_id) or []
        idx = int(query) - 1
        if 0 <= idx < len(pending):
            summary = format_claim_summary(db, pending[idx].claim_id, user_id)
            _lookup_hits.pop(user_id, None)
            if summary:
                return ChatReply(text=summary)
        return ChatReply(text="That list number isn't valid — try the claim reference instead.")

    hits = search_claims(db, query, user_id=user_id)
    if not hits:
        return ChatReply(
            text=(
                f"I couldn't find a claim matching “{query}”. "
                "Try a different reference, garage, or surveyor name."
            )
        )

    if ref_only or len(hits) == 1:
        summary = format_claim_summary(db, hits[0].claim_id, user_id)
        _lookup_hits.pop(user_id, None)
        return ChatReply(text=summary or "Claim found but details are unavailable.")

    if hits[0].score >= hits[1].score + 15:
        summary = format_claim_summary(db, hits[0].claim_id, user_id)
        _lookup_hits.pop(user_id, None)
        return ChatReply(text=summary or "Claim found but details are unavailable.")

    _lookup_hits[user_id] = hits
    return ChatReply(text=format_search_hit_list(hits))


def _draft_status_line(draft: ClaimDraft) -> str:
    parts: list[str] = []
    if draft.image_count():
        parts.append(f"{draft.image_count()} photo(s)")
    if draft.video:
        parts.append("1 video")
    if draft.garage_name:
        parts.append(f"garage: {draft.garage_name}")
    if draft.accident_date:
        parts.append(f"accident date: {draft.accident_date}")
    if draft.surveyor_name:
        parts.append(f"surveyor: {draft.surveyor_name}")
    return ", ".join(parts) if parts else "nothing collected yet"


async def submit_draft(
    db: Session,
    user_id: int,
    draft: ClaimDraft,
    *,
    full_name: str | None,
    username: str | None,
    background_tasks: BackgroundTasks,
) -> tuple[ChatReply | None, dict | None]:
    missing = draft.missing_required(user_display_name=_display_name(full_name, username))
    if missing:
        return (
            ChatReply(
                text=(
                    f"I still need {' and '.join(missing)} before I can submit. "
                    "Upload photos and tell me the garage name when you're ready."
                )
            ),
            None,
        )

    garage_name = (draft.garage_name or "").strip()
    garage_id = None
    if garage_name:
        garage = db.scalar(select(Garage).where(Garage.name.ilike(garage_name)))
        if garage is None:
            garage = Garage(name=garage_name)
            db.add(garage)
            db.flush()
        garage_id = garage.id

    images = [_bytes_upload(blob) for blob in draft.images]
    video = _bytes_upload(draft.video) if draft.video else None
    claimant_name = _display_name(full_name, username)

    try:
        claim = await create_claim_with_uploads(
            db,
            user_id=user_id,
            images=images,
            video=video,
            garage_id=garage_id,
            surveyor_name=(draft.surveyor_name or "").strip() or None,
            claimant_name=claimant_name,
            accident_date=parse_accident_date(draft.accident_date),
        )
    except ClaimValidationError as exc:
        return ChatReply(text=str(exc)), None

    clear_draft(user_id)
    background_tasks.add_task(ensure_pipeline_started, claim.id)

    catalog = catalog_makes_models(db)
    reply = ChatReply(
        text=(
            f"Thanks — I've submitted **{claim.claim_reference}**. "
            "Running the assessment pipeline now…"
        ),
        widgets=[
            {
                "type": "pipeline",
                "claim_id": claim.id,
                "claim_reference": claim.claim_reference,
                "catalog_makes": catalog,
            }
        ],
    )
    return reply, {"claim_id": claim.id, "claim_reference": claim.claim_reference}


def begin_submit_flow(full_name: str | None, username: str | None) -> ChatReply:
    name = _display_name(full_name, username)
    return ChatReply(
        text=(
            f"Sure {name}, please upload the damage pictures (max {_settings.max_images_per_claim}) "
            "and/or video. Also let me know the garage name, the accident date, and the surveyor "
            "name if you're not the surveyor yourself."
        ),
        widgets=[{"type": "file_upload"}],
    )


async def handle_message(
    db: Session,
    user_id: int,
    text: str,
    *,
    full_name: str | None,
    username: str | None,
    background_tasks: BackgroundTasks,
) -> ChatReply:
    raw = (text or "").strip()
    draft = get_draft(user_id)
    llm_fn = _llm_classifier(db, user_id)

    if _lookup_awaiting.get(user_id) and raw and not draft.active:
        _, entities = classify_intent(raw, draft_active=False, llm_classify=llm_fn)
        return handle_lookup(db, user_id, raw, entities, force=True)

    intent, entities = classify_intent(
        raw,
        draft_active=draft.active,
        llm_classify=llm_fn,
    )

    if intent == "lookup_claim":
        clear_draft(user_id)
        draft.active = False
        return handle_lookup(db, user_id, raw, entities)

    if intent == "submit_claim" and not draft.active:
        start_draft(user_id)
        return begin_submit_flow(full_name, username)

    if draft.active or intent in {"submit_claim", "done"}:
        draft = get_draft(user_id)
        if not draft.active:
            draft.active = True
        if raw:
            parse_details_from_text(draft, raw)

        if intent == "done" or any(
            phrase in raw.lower()
            for phrase in ("submit now", "go ahead", "that's all", "thats all", "done")
        ):
            reply, _meta = await submit_draft(
                db,
                user_id,
                draft,
                full_name=full_name,
                username=username,
                background_tasks=background_tasks,
            )
            return reply

        status = _draft_status_line(draft)
        missing = draft.missing_required(user_display_name=_display_name(full_name, username))
        if missing:
            return ChatReply(
                text=(
                    f"Got it — so far I have: {status}. "
                    f"I still need {' and '.join(missing)}. "
                    "Say “done” when you're ready to submit."
                ),
                widgets=[{"type": "file_upload"}] if "photo" in " ".join(missing) else [],
            )

        return ChatReply(
            text=(
                f"Got it — I have: {status}. "
                "Say “done” when you want me to submit the claim."
            ),
            widgets=[{"type": "file_upload"}],
        )

    if intent == "general":
        return ChatReply(
            text=(
                "I can help you submit a new claim or look up an existing one. "
                "Try “Submit a claim” or “Find my claim”."
            )
        )

    return handle_lookup(db, user_id, raw, entities, force=True)


def append_uploads(
    user_id: int,
    *,
    images: list[tuple[str, bytes, str]],
    video: tuple[str, bytes, str] | None,
) -> ChatReply:
    draft = get_draft(user_id)
    if not draft.active:
        start_draft(user_id)

    max_images = _settings.max_images_per_claim
    for filename, data, content_type in images:
        if len(draft.images) >= max_images:
            break
        draft.images.append(
            UploadedFile(
                filename=filename,
                data=data,
                content_type=content_type,
                is_video=False,
            )
        )

    if video and draft.video is None:
        draft.video = UploadedFile(
            filename=video[0],
            data=video[1],
            content_type=video[2],
            is_video=True,
        )

    count = draft.image_count()
    video_note = " and 1 video" if draft.video else ""
    return ChatReply(
        text=f"Received {count} photo(s){video_note}. {_draft_status_line(draft)}.",
        widgets=[{"type": "file_upload"}],
    )
