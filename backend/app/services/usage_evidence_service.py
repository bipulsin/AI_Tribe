"""Discover historical user activity from claims and related tables.

Complements live ``usage_events`` (middleware) with traces from operational data
entered before route logging existed: claims, LLM assists, VMMR labels, partner
API request logs, and chat drafts.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_marketplace.models import ApiRequestLog
from app.models import Claim, ChatDraftState, LlmAssistLog, User, VmmrCorrectionQueue, VmmrLabLabel
from app.models.usage_event import UsageEvent

LEGACY_PREFIX = "LEGACY|"


def _as_utc_day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_inclusive = datetime.combine(end, time.max, tzinfo=timezone.utc)
    return start_dt, end_inclusive


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _legacy_route(table: str, origin_id: int | str) -> str:
    return f"{LEGACY_PREFIX}{table}|{origin_id}"


def _event_dict(
    *,
    user_id: int,
    event_type: str,
    feature_area: str,
    endpoint_or_route: str,
    occurred_at: datetime | None,
    metadata: dict[str, Any] | None = None,
    source: str,
) -> dict[str, Any] | None:
    at = _ensure_aware(occurred_at)
    if at is None:
        return None
    return {
        "id": endpoint_or_route,
        "user_id": user_id,
        "event_type": event_type,
        "feature_area": feature_area,
        "endpoint_or_route": endpoint_or_route,
        "occurred_at": at,
        "ip_address": None,
        "metadata": {**(metadata or {}), "source": source},
        "source": source,
    }


def collect_usage_evidence(
    db: Session,
    *,
    user_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
    limit_per_source: int = 5000,
) -> list[dict[str, Any]]:
    """Return synthetic event-shaped traces from operational tables.

    When ``start``/``end`` are set, only events inside that UTC range are
    returned. When omitted, all matching rows (capped per source) are returned.
    """
    if not user_ids and user_ids is not None:
        return []

    start_dt = end_dt = None
    if start is not None and end is not None:
        if end < start:
            start, end = end, start
        start_dt, end_dt = _as_utc_day_bounds(start, end)

    events: list[dict[str, Any]] = []

    # --- Claims created by user ---
    claim_stmt = select(Claim).order_by(Claim.created_at.asc()).limit(limit_per_source)
    if user_ids is not None:
        claim_stmt = claim_stmt.where(Claim.created_by.in_(user_ids))
    if start_dt is not None:
        claim_stmt = claim_stmt.where(Claim.created_at >= start_dt, Claim.created_at <= end_dt)
    for c in db.scalars(claim_stmt).all():
        ev = _event_dict(
            user_id=c.created_by,
            event_type="legacy_claim_create",
            feature_area="form_ui",
            endpoint_or_route=_legacy_route("claims", c.id),
            occurred_at=c.created_at,
            metadata={
                "claim_id": c.id,
                "claim_reference": c.claim_reference,
                "status": str(c.status.value if hasattr(c.status, "value") else c.status),
            },
            source="claims",
        )
        if ev:
            events.append(ev)

    # --- LLM assist on assessments ---
    llm_stmt = select(LlmAssistLog).order_by(LlmAssistLog.created_at.asc()).limit(limit_per_source)
    if user_ids is not None:
        llm_stmt = llm_stmt.where(LlmAssistLog.user_id.in_(user_ids))
    if start_dt is not None:
        llm_stmt = llm_stmt.where(
            LlmAssistLog.created_at >= start_dt, LlmAssistLog.created_at <= end_dt
        )
    for row in db.scalars(llm_stmt).all():
        ev = _event_dict(
            user_id=row.user_id,
            event_type="legacy_llm_assist",
            feature_area="form_ui",
            endpoint_or_route=_legacy_route("llm_assist_logs", row.id),
            occurred_at=row.created_at,
            metadata={"claim_id": row.claim_id, "stage": row.stage, "provider": row.provider},
            source="llm_assist_logs",
        )
        if ev:
            events.append(ev)

    # --- VMMR corrections on live claims ---
    vmmr_stmt = (
        select(VmmrCorrectionQueue)
        .order_by(VmmrCorrectionQueue.created_at.asc())
        .limit(limit_per_source)
    )
    if user_ids is not None:
        vmmr_stmt = vmmr_stmt.where(VmmrCorrectionQueue.submitted_by.in_(user_ids))
    if start_dt is not None:
        vmmr_stmt = vmmr_stmt.where(
            VmmrCorrectionQueue.created_at >= start_dt,
            VmmrCorrectionQueue.created_at <= end_dt,
        )
    for row in db.scalars(vmmr_stmt).all():
        ev = _event_dict(
            user_id=row.submitted_by,
            event_type="legacy_vmmr_confirm",
            feature_area="form_ui",
            endpoint_or_route=_legacy_route("vmmr_correction_queue", row.id),
            occurred_at=row.created_at,
            metadata={
                "claim_id": row.claim_id,
                "make": row.confirmed_make,
                "model": row.confirmed_model,
            },
            source="vmmr_correction_queue",
        )
        if ev:
            events.append(ev)

    # --- Lab VMMR labeling ---
    lab_stmt = (
        select(VmmrLabLabel)
        .where(VmmrLabLabel.labeled_by.is_not(None), VmmrLabLabel.labeled_at.is_not(None))
        .order_by(VmmrLabLabel.labeled_at.asc())
        .limit(limit_per_source)
    )
    if user_ids is not None:
        lab_stmt = lab_stmt.where(VmmrLabLabel.labeled_by.in_(user_ids))
    if start_dt is not None:
        lab_stmt = lab_stmt.where(
            VmmrLabLabel.labeled_at >= start_dt, VmmrLabLabel.labeled_at <= end_dt
        )
    for row in db.scalars(lab_stmt).all():
        if row.labeled_by is None:
            continue
        ev = _event_dict(
            user_id=int(row.labeled_by),
            event_type="legacy_vmmr_label",
            feature_area="lab_vmmr",
            endpoint_or_route=_legacy_route("vmmr_lab_labels", row.id),
            occurred_at=row.labeled_at,
            metadata={"status": row.status, "source_dataset": row.source_dataset},
            source="vmmr_lab_labels",
        )
        if ev:
            events.append(ev)

    # --- Partner API request log ---
    api_stmt = (
        select(ApiRequestLog)
        .where(ApiRequestLog.user_id.is_not(None))
        .order_by(ApiRequestLog.created_at.asc())
        .limit(limit_per_source)
    )
    if user_ids is not None:
        api_stmt = api_stmt.where(ApiRequestLog.user_id.in_(user_ids))
    if start_dt is not None:
        api_stmt = api_stmt.where(
            ApiRequestLog.created_at >= start_dt, ApiRequestLog.created_at <= end_dt
        )
    for row in db.scalars(api_stmt).all():
        if row.user_id is None:
            continue
        ev = _event_dict(
            user_id=int(row.user_id),
            event_type="legacy_api_call",
            feature_area="api_marketplace",
            endpoint_or_route=_legacy_route("api_request_log", row.id),
            occurred_at=row.created_at,
            metadata={
                "api_name": row.api_name,
                "claim_no": row.claim_no,
                "status_code": row.status_code,
            },
            source="api_request_log",
        )
        if ev:
            events.append(ev)

    # --- Chat draft (incomplete sessions still prove access) ---
    draft_stmt = select(ChatDraftState).order_by(ChatDraftState.updated_at.asc()).limit(limit_per_source)
    if user_ids is not None:
        draft_stmt = draft_stmt.where(ChatDraftState.user_id.in_(user_ids))
    if start_dt is not None:
        draft_stmt = draft_stmt.where(
            ChatDraftState.updated_at >= start_dt, ChatDraftState.updated_at <= end_dt
        )
    for row in db.scalars(draft_stmt).all():
        ev = _event_dict(
            user_id=row.user_id,
            event_type="legacy_chat_draft",
            feature_area="chat",
            endpoint_or_route=_legacy_route("chat_draft_states", row.user_id),
            occurred_at=row.updated_at,
            metadata={},
            source="chat_draft_states",
        )
        if ev:
            events.append(ev)

    events.sort(key=lambda e: e["occurred_at"])
    return events


def user_ids_with_any_evidence(db: Session, user_ids: list[int]) -> set[int]:
    """Users who appear in any historical evidence source (any time)."""
    if not user_ids:
        return set()
    found: set[int] = set()

    for uid in db.scalars(
        select(Claim.created_by).where(Claim.created_by.in_(user_ids)).distinct()
    ).all():
        found.add(int(uid))

    for uid in db.scalars(
        select(LlmAssistLog.user_id).where(LlmAssistLog.user_id.in_(user_ids)).distinct()
    ).all():
        found.add(int(uid))

    for uid in db.scalars(
        select(VmmrCorrectionQueue.submitted_by)
        .where(VmmrCorrectionQueue.submitted_by.in_(user_ids))
        .distinct()
    ).all():
        found.add(int(uid))

    for uid in db.scalars(
        select(VmmrLabLabel.labeled_by)
        .where(VmmrLabLabel.labeled_by.in_(user_ids), VmmrLabLabel.labeled_by.is_not(None))
        .distinct()
    ).all():
        if uid is not None:
            found.add(int(uid))

    for uid in db.scalars(
        select(ApiRequestLog.user_id)
        .where(ApiRequestLog.user_id.in_(user_ids), ApiRequestLog.user_id.is_not(None))
        .distinct()
    ).all():
        if uid is not None:
            found.add(int(uid))

    for uid in db.scalars(
        select(ChatDraftState.user_id).where(ChatDraftState.user_id.in_(user_ids)).distinct()
    ).all():
        found.add(int(uid))

    return found


def backfill_usage_events_from_evidence(db: Session, *, limit_per_source: int = 10000) -> dict[str, int]:
    """Idempotently insert legacy evidence into ``usage_events``.

    Dedupes on ``endpoint_or_route`` values starting with ``LEGACY|``.
    """
    existing = set(
        db.scalars(
            select(UsageEvent.endpoint_or_route).where(
                UsageEvent.endpoint_or_route.startswith(LEGACY_PREFIX)
            )
        ).all()
    )

    users = {
        u.id: u
        for u in db.scalars(select(User)).all()
    }

    evidence = collect_usage_evidence(db, user_ids=None, start=None, end=None, limit_per_source=limit_per_source)
    inserted = 0
    skipped = 0
    for ev in evidence:
        route = ev["endpoint_or_route"]
        if route in existing:
            skipped += 1
            continue
        user = users.get(ev["user_id"])
        username = None
        if user is not None:
            username = (user.email or user.username or f"user:{user.id}")[:128]
        db.add(
            UsageEvent(
                user_id=ev["user_id"],
                username_snapshot=username,
                event_type=ev["event_type"],
                feature_area=ev["feature_area"],
                endpoint_or_route=route[:256],
                occurred_at=ev["occurred_at"],
                session_id=None,
                ip_address=None,
                metadata_json=ev.get("metadata"),
            )
        )
        existing.add(route)
        inserted += 1

    if inserted:
        db.commit()
    return {"inserted": inserted, "skipped": skipped, "scanned": len(evidence)}
