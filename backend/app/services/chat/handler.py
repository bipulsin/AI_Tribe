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
    INTERRUPTED_MESSAGE,
    ClaimDraft,
    activate_draft,
    append_files,
    clear_draft,
    ensure_blob_data,
    get_draft,
    parse_accident_date,
    parse_details_from_text,
    persist_draft,
)
from app.services.chat.intent import (
    classify_intent,
    extract_city_from_text,
    extract_claim_reference,
    extract_search_term,
    extract_search_tokens,
    extract_short_claim_number,
    is_fresh_submit_intent,
    llm_classify_intent,
    pad_claim_number_suffix,
)
from app.services.chat.garage_lookup import (
    find_garages_for_city,
    find_garages_in_city,
    format_garage_pick_list,
    format_submit_garage_pick_list,
    resolve_garage_choice,
)
from app.services.chat.lookup import (
    build_claim_detail,
    format_no_match,
    format_search_hit_list,
    format_suffix_miss,
)
from app.services.claim_search import (
    is_claim_reference_like,
    search_claims,
    search_claims_by_reference_suffix,
    search_claims_with_tokens,
)
from app.services.claim_service import ClaimValidationError, create_claim_with_uploads
from app.services.llm.settings import get_active_api_key
from app.services.pipeline_orchestrator import ensure_pipeline_started
from app.services.vmmr.vehicle_confirmation import catalog_makes_models

_settings = get_settings()

# Enterprise chat lookup: any signed-in user can search and view all claims.
_CHAT_LOOKUP_SCOPE_USER_ID = None

_lookup_sessions: dict[int, "LookupSession"] = {}
_submit_sessions: dict[int, "SubmitSession"] = {}


@dataclass
class LookupSession:
    mode: str = "none"  # none | awaiting_garage_name | awaiting_list_pick | awaiting_query
    garage_options: list[str] = field(default_factory=list)
    city_label: str = ""
    hits: list = field(default_factory=list)


@dataclass
class SubmitSession:
    mode: str = "none"  # none | await_city | await_garage_pick
    garage_options: list[str] = field(default_factory=list)
    city_label: str = ""


def _clear_lookup_session(user_id: int) -> None:
    _lookup_sessions.pop(user_id, None)


def _clear_submit_session(user_id: int) -> None:
    _submit_sessions.pop(user_id, None)


def _lookup_awaiting_query(user_id: int) -> bool:
    session = _lookup_sessions.get(user_id)
    return bool(session and session.mode == "awaiting_query")


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

    suffix = entities.get("claim_suffix")
    if not suffix:
        short = extract_short_claim_number(text)
        if short is not None:
            suffix = pad_claim_number_suffix(short)
    if suffix:
        return f"__suffix__:{suffix}"

    term = entities.get("search_term") or extract_search_term(text)
    if term:
        return term

    tokens = entities.get("search_tokens") or extract_search_tokens(text)
    if tokens:
        return f"__tokens__:{'|'.join(tokens)}"

    city = entities.get("city_query")
    if city:
        return f"__city__:{city}"

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


def _is_vague_lookup(query: str, *, ref: str | None, entities: dict | None = None) -> bool:
    entities = entities or {}
    if ref or entities.get("claim_suffix") or entities.get("city_query"):
        return False
    if entities.get("search_term") or entities.get("search_tokens"):
        return False
    if query.startswith("__suffix__:") or query.startswith("__city__:") or query.startswith(
        "__tokens__:"
    ):
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


def _interrupted_reply(db: Session, user_id: int) -> ChatReply:
    clear_draft(db, user_id)
    _clear_submit_session(user_id)
    return ChatReply(text=INTERRUPTED_MESSAGE)


def _claim_detail_reply(db: Session, claim_id: int) -> ChatReply:
    detail = build_claim_detail(db, claim_id)
    if not detail:
        return ChatReply(text="Claim found but details are unavailable.")
    text, widgets = detail
    return ChatReply(text=text, widgets=widgets)


def _finish_lookup_hits(
    db: Session, user_id: int, hits: list, *, ref_only: bool
) -> ChatReply:
    if not hits:
        return ChatReply(text="No matching claims found.")

    if len(hits) == 1:
        _clear_lookup_session(user_id)
        return _claim_detail_reply(db, hits[0].claim_id)

    session = LookupSession(mode="awaiting_list_pick", hits=hits)
    _lookup_sessions[user_id] = session
    return ChatReply(text=format_search_hit_list(hits))


def handle_garage_name_lookup(
    db: Session,
    user_id: int,
    text: str,
    session: LookupSession,
) -> ChatReply:
    garage_query = resolve_garage_choice(text, session.garage_options)
    if not garage_query:
        return ChatReply(text="Please type the garage name from the list.")

    _clear_lookup_session(user_id)
    hits = search_claims(db, garage_query, user_id=_CHAT_LOOKUP_SCOPE_USER_ID)
    if not hits:
        city = session.city_label.title() if session.city_label else "that area"
        return ChatReply(
            text=(
                f"I couldn't find claims for “{garage_query}”. "
                f"Try another garage name from the {city} list."
            )
        )
    return _finish_lookup_hits(db, user_id, hits, ref_only=False)


def handle_lookup(
    db: Session,
    user_id: int,
    text: str,
    entities: dict,
    *,
    force: bool = False,
) -> ChatReply:
    query = _resolve_lookup_query(text, entities)
    ref_only = bool(entities.get("claim_reference") or extract_claim_reference(text))

    if not force and _is_vague_lookup(query, ref=ref_only, entities=entities):
        _lookup_sessions[user_id] = LookupSession(mode="awaiting_query")
        return ChatReply(
            text=(
                "I can look that up — please share the claim reference (e.g. CLM-2026-000017), "
                "garage name, or surveyor name."
            )
        )

    if not force and not query and not _lookup_awaiting_query(user_id):
        _lookup_sessions[user_id] = LookupSession(mode="awaiting_query")
        return ChatReply(
            text=(
                "I can look that up — please share the claim reference (e.g. CLM-2026-000017), "
                "garage name, or surveyor name."
            )
        )

    if not query:
        _lookup_sessions[user_id] = LookupSession(mode="awaiting_query")
        return ChatReply(
            text="Please provide a claim reference, garage name, or surveyor name to search."
        )

    if re.fullmatch(r"\d{1,2}", query):
        session = _lookup_sessions.get(user_id)
        pending = session.hits if session and session.mode == "awaiting_list_pick" else []
        idx = int(query) - 1
        if 0 <= idx < len(pending):
            _clear_lookup_session(user_id)
            return _claim_detail_reply(db, pending[idx].claim_id)
        return ChatReply(text="That list number isn't valid — try the claim reference instead.")

    _clear_lookup_session(user_id)

    if query.startswith("__suffix__:"):
        suffix = query.split(":", 1)[1]
        hits = search_claims_by_reference_suffix(
            db, suffix, user_id=_CHAT_LOOKUP_SCOPE_USER_ID
        )
        if not hits:
            return ChatReply(text=format_suffix_miss(suffix))
        return _finish_lookup_hits(db, user_id, hits, ref_only=True)

    if query.startswith("__city__:"):
        city_key = query.split(":", 1)[1]
        garages = find_garages_for_city(db, city_key, user_id=_CHAT_LOOKUP_SCOPE_USER_ID)
        if not garages:
            hits = search_claims(db, city_key, user_id=_CHAT_LOOKUP_SCOPE_USER_ID)
            if hits:
                return _finish_lookup_hits(db, user_id, hits, ref_only=False)
            label = city_key.title()
            if city_key == "kochi":
                label = "Kochi / Cochin"
            return ChatReply(
                text=(
                    f"I couldn't find any of your claims at garages in **{label}**. "
                    "Try another city or a garage name directly."
                )
            )
        _lookup_sessions[user_id] = LookupSession(
            mode="awaiting_garage_name",
            garage_options=garages,
            city_label=city_key,
        )
        return ChatReply(text=format_garage_pick_list(garages, city_key))

    if query.startswith("__tokens__:"):
        token_blob = query.split(":", 1)[1]
        tokens = [t for t in token_blob.split("|") if t]
        hits = search_claims_with_tokens(db, tokens, user_id=_CHAT_LOOKUP_SCOPE_USER_ID)
        if not hits:
            return ChatReply(text=format_no_match(" ".join(tokens)))
        return _finish_lookup_hits(db, user_id, hits, ref_only=False)

    hits = search_claims(db, query, user_id=_CHAT_LOOKUP_SCOPE_USER_ID)
    if not hits:
        tokens = extract_search_tokens(text)
        if tokens:
            hits = search_claims_with_tokens(
                db, tokens, user_id=_CHAT_LOOKUP_SCOPE_USER_ID
            )
    if not hits:
        return ChatReply(text=format_no_match(query))

    return _finish_lookup_hits(db, user_id, hits, ref_only=ref_only)


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
    if draft.surveyor_name and draft.surveyor_name != "__self__":
        parts.append(f"surveyor: {draft.surveyor_name}")
    elif draft.surveyor_name == "__self__":
        parts.append("surveyor: you")
    return ", ".join(parts) if parts else "nothing collected yet"


def _resolve_surveyor_name(
    draft: ClaimDraft, *, full_name: str | None, username: str | None
) -> str:
    raw = (draft.surveyor_name or "").strip()
    if not raw or raw == "__self__":
        return _display_name(full_name, username)
    return raw


def _city_prompt(name: str) -> ChatReply:
    return ChatReply(
        text=(
            f"Sure {name} — let's submit a new claim.\n\n"
            "Which city is the car being repaired in? "
            "(e.g. Pune, Kochi, Ahmedabad)"
        )
    )


def _surveyor_prompt() -> ChatReply:
    return ChatReply(
        text=(
            "Who is the surveyor for this claim?\n\n"
            "Reply with their name, or say **me** if you are the surveyor."
        )
    )


def _date_prompt() -> ChatReply:
    return ChatReply(
        text=(
            "What is the date of the accident?\n\n"
            "Use a format like **2026-03-15** or **15/03/2026**."
        )
    )


def _photos_prompt() -> ChatReply:
    return ChatReply(
        text=(
            f"Please upload the damage pictures "
            f"(max {_settings.max_images_per_claim}) and/or a short video."
        ),
        widgets=[{"type": "file_upload"}],
    )


def _garage_pick_reply(db: Session, user_id: int, city_key: str) -> ChatReply:
    garages = find_garages_in_city(db, city_key) or find_garages_for_city(
        db, city_key, user_id=_CHAT_LOOKUP_SCOPE_USER_ID
    )
    city_title = "Kochi" if city_key == "kochi" else city_key.title()
    if garages:
        _submit_sessions[user_id] = SubmitSession(
            mode="await_garage_pick",
            garage_options=garages,
            city_label=city_key,
        )
        return ChatReply(text=format_submit_garage_pick_list(garages, city_key))
    _submit_sessions[user_id] = SubmitSession(
        mode="await_garage_pick",
        garage_options=[],
        city_label=city_key,
    )
    return ChatReply(
        text=(
            f"I don't have listed garages for **{city_title}** yet.\n\n"
            "Please type the garage / workshop name where the car is being repaired."
        )
    )


def _prompt_for_step(
    db: Session,
    user_id: int,
    draft: ClaimDraft,
    *,
    full_name: str | None,
    username: str | None,
) -> ChatReply:
    step = draft.next_step()
    if step == "await_city":
        draft.flow = "await_city"
        persist_draft(db, user_id, draft)
        return _city_prompt(_display_name(full_name, username))
    if step == "await_garage":
        draft.flow = "await_garage"
        persist_draft(db, user_id, draft)
        session = _submit_sessions.get(user_id)
        if session and session.mode == "await_garage_pick" and session.city_label:
            return _garage_pick_reply(db, user_id, session.city_label)
        return ChatReply(
            text="Please type the garage / workshop name where the car is being repaired."
        )
    if step == "await_surveyor":
        draft.flow = "await_surveyor"
        persist_draft(db, user_id, draft)
        _clear_submit_session(user_id)
        return _surveyor_prompt()
    if step == "await_date":
        draft.flow = "await_date"
        persist_draft(db, user_id, draft)
        return _date_prompt()
    if step == "await_photos":
        draft.flow = "await_photos"
        persist_draft(db, user_id, draft)
        return _photos_prompt()
    return ChatReply(
        text=f"I have everything I need ({_draft_status_line(draft)}). Submitting shortly…"
    )


async def submit_draft(
    db: Session,
    user_id: int,
    draft: ClaimDraft,
    *,
    full_name: str | None,
    username: str | None,
    background_tasks: BackgroundTasks,
) -> tuple[ChatReply | None, dict | None]:
    draft = ensure_blob_data(draft)
    if draft.interrupted or draft.blobs_missing():
        return _interrupted_reply(db, user_id), None

    # Default surveyor to signed-in user when not provided.
    if not (draft.surveyor_name or "").strip():
        draft.surveyor_name = "__self__"
        persist_draft(db, user_id, draft)

    missing = draft.missing_required(user_display_name=_display_name(full_name, username))
    if missing:
        return (
            ChatReply(
                text=(
                    f"I still need {' and '.join(missing)} before I can submit. "
                    f"So far: {_draft_status_line(draft)}."
                ),
                widgets=[{"type": "file_upload"}] if "photo" in " ".join(missing) else [],
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

    images = [_bytes_upload(blob) for blob in draft.loadable_images()]
    video = _bytes_upload(draft.video) if draft.video and draft.video.blob_available() else None
    claimant_name = _display_name(full_name, username)
    surveyor_name = _resolve_surveyor_name(draft, full_name=full_name, username=username)

    try:
        claim = await create_claim_with_uploads(
            db,
            user_id=user_id,
            images=images,
            video=video,
            garage_id=garage_id,
            surveyor_name=surveyor_name,
            claimant_name=claimant_name,
            accident_date=parse_accident_date(draft.accident_date),
        )
    except ClaimValidationError as exc:
        return ChatReply(text=str(exc)), None

    clear_draft(db, user_id)
    _clear_submit_session(user_id)
    background_tasks.add_task(ensure_pipeline_started, claim.id)

    catalog = catalog_makes_models(db)
    reply = ChatReply(
        text=(
            f"**Submitting & Assessing the claim**\n\n"
            f"Claim **{claim.claim_reference}** created. "
            "Running the 12-stage assessment pipeline now — results will appear below."
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


def begin_submit_flow(
    db: Session,
    user_id: int,
    *,
    full_name: str | None,
    username: str | None,
    city_hint: str | None = None,
) -> ChatReply:
    """Start or resume guided claim submission without wiping existing uploads."""
    _clear_lookup_session(user_id)
    draft = activate_draft(db, user_id)
    if city_hint and not draft.garage_name:
        draft.flow = "await_garage"
        persist_draft(db, user_id, draft)
        return _garage_pick_reply(db, user_id, city_hint)
    return _prompt_for_step(
        db, user_id, draft, full_name=full_name, username=username
    )


async def _continue_submit_flow(
    db: Session,
    user_id: int,
    text: str,
    draft: ClaimDraft,
    *,
    full_name: str | None,
    username: str | None,
    background_tasks: BackgroundTasks,
    force_submit: bool = False,
) -> ChatReply:
    raw = (text or "").strip()
    lower = raw.lower()
    session = _submit_sessions.get(user_id)

    # City selection while awaiting city (or early in flow without garage).
    if not draft.garage_name and draft.next_step() == "await_city" and raw:
        city = extract_city_from_text(raw)
        if city:
            draft.flow = "await_garage"
            persist_draft(db, user_id, draft)
            return _garage_pick_reply(db, user_id, city)
        # Allow labelled "garage is …" to skip the city step.
        if "garage" not in lower:
            return ChatReply(
                text=(
                    "Please tell me the city where the car is being repaired "
                    "(e.g. Pune, Kochi, Ahmedabad)."
                )
            )

    # Garage pick from list — only for short / list-number replies.
    awaiting_garage = not draft.garage_name and (
        (session and session.mode == "await_garage_pick")
        or draft.next_step() == "await_garage"
        or draft.flow == "await_garage"
    )
    multi_field = any(
        token in lower for token in ("accident", "surveyor", "date", ",")
    ) or bool(re.search(r"garage(?:\s+name)?\s*(?:is|:|-)", lower))

    if awaiting_garage and raw and not multi_field:
        options = session.garage_options if session else []
        chosen = resolve_garage_choice(raw, options) if options else raw.strip()
        if chosen:
            draft.garage_name = chosen[:128]
            draft.flow = "await_surveyor"
            persist_draft(db, user_id, draft)
            _clear_submit_session(user_id)
            return _surveyor_prompt()
        return _prompt_for_step(
            db, user_id, draft, full_name=full_name, username=username
        )

    if raw:
        draft = parse_details_from_text(db, user_id, draft, raw)
        if draft.garage_name:
            _clear_submit_session(user_id)

    # Default surveyor to self when user skips with done/go-ahead and photos+garage+date exist.
    if force_submit and not (draft.surveyor_name or "").strip():
        draft.surveyor_name = "__self__"
        persist_draft(db, user_id, draft)

    if force_submit or draft.next_step() == "ready":
        reply, _meta = await submit_draft(
            db,
            user_id,
            draft,
            full_name=full_name,
            username=username,
            background_tasks=background_tasks,
        )
        return reply

    return _prompt_for_step(
        db, user_id, draft, full_name=full_name, username=username
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
    draft = get_draft(db, user_id)
    if draft.interrupted:
        return _interrupted_reply(db, user_id)

    llm_fn = _llm_classifier(db, user_id)

    session = _lookup_sessions.get(user_id)
    if session and session.mode == "awaiting_garage_name" and raw and not draft.active:
        if is_fresh_submit_intent(raw):
            _clear_lookup_session(user_id)
        else:
            return handle_garage_name_lookup(db, user_id, raw, session)

    if session and session.mode == "awaiting_list_pick" and raw and re.fullmatch(r"\d{1,2}", raw):
        return handle_lookup(db, user_id, raw, {}, force=True)

    if _lookup_awaiting_query(user_id) and raw and not draft.active:
        _, entities = classify_intent(raw, draft_active=False, llm_classify=llm_fn)
        return handle_lookup(db, user_id, raw, entities, force=True)

    intent, entities = classify_intent(
        raw,
        draft_active=draft.active,
        llm_classify=llm_fn,
    )

    if intent == "lookup_claim":
        clear_draft(db, user_id)
        _clear_submit_session(user_id)
        return handle_lookup(db, user_id, raw, entities)

    # Fresh submit phrasing — preserve any photos already uploaded in this turn.
    if intent == "submit_claim" and is_fresh_submit_intent(raw):
        city_hint = entities.get("city_query") or extract_city_from_text(raw)
        return begin_submit_flow(
            db,
            user_id,
            full_name=full_name,
            username=username,
            city_hint=city_hint,
        )

    if draft.active or intent in {"submit_claim", "done"}:
        draft = get_draft(db, user_id)
        if draft.interrupted:
            return _interrupted_reply(db, user_id)
        if not draft.active:
            draft = activate_draft(db, user_id)

        force_submit = intent == "done" or any(
            phrase in raw.lower()
            for phrase in ("submit now", "go ahead", "that's all", "thats all", "done")
        )
        return await _continue_submit_flow(
            db,
            user_id,
            raw,
            draft,
            full_name=full_name,
            username=username,
            background_tasks=background_tasks,
            force_submit=force_submit,
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
    db: Session,
    user_id: int,
    *,
    images: list[tuple[str, bytes, str]],
    video: tuple[str, bytes, str] | None,
) -> ChatReply:
    draft = get_draft(db, user_id)
    if draft.interrupted:
        return _interrupted_reply(db, user_id)
    if not draft.active:
        draft = activate_draft(db, user_id)

    draft = append_files(db, user_id, draft, images=images, video=video)
    if draft.interrupted:
        return _interrupted_reply(db, user_id)

    # Guided next question — do not ask the user to say “done”.
    step = draft.next_step()
    if step == "ready":
        return ChatReply(
            text=(
                f"Photos saved — I have: {_draft_status_line(draft)}. "
                "Say **go ahead** if you want me to submit now, or add any missing details."
            )
        )
    if step == "await_city":
        return ChatReply(
            text=(
                f"Photos saved ({draft.image_count()}). "
                "Which city is the car being repaired in?"
            )
        )
    if step == "await_garage":
        session = _submit_sessions.get(user_id)
        if session and session.city_label:
            return _garage_pick_reply(db, user_id, session.city_label)
        return ChatReply(
            text=(
                f"Photos saved ({draft.image_count()}). "
                "Please type the garage name, or tell me the city first."
            )
        )
    if step == "await_surveyor":
        return ChatReply(
            text=(
                f"Photos saved ({draft.image_count()}). "
                "Who is the surveyor? Reply with a name, or say **me**."
            )
        )
    if step == "await_date":
        return ChatReply(
            text=(
                f"Photos saved ({draft.image_count()}). "
                "What is the date of the accident? (e.g. 2026-03-15)"
            )
        )
    return _photos_prompt()
