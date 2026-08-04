"""Aggregate usage_events + historical evidence into Usability Report rows."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.usage_event import UsageEvent
from app.services.usage_evidence_service import (
    collect_usage_evidence,
    user_ids_with_any_evidence,
)


def _as_utc_day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_inclusive = datetime.combine(end, time.max, tzinfo=timezone.utc)
    return start_dt, end_inclusive


def _user_label(user: User) -> str:
    return (user.email or user.username or f"user:{user.id}").strip()


def list_report_users(db: Session) -> list[dict[str, Any]]:
    """All system users for the filter dropdown."""
    users = db.scalars(
        select(User).order_by(User.is_active.desc(), User.username.asc(), User.id.asc())
    ).all()
    return [
        {
            "id": u.id,
            "username": _user_label(u),
            "full_name": u.full_name,
            "is_active": bool(u.is_active),
        }
        for u in users
    ]


def _merge_day(day_list: list[str], day: str) -> None:
    if day not in day_list:
        day_list.append(day)


def build_usage_report(
    db: Session,
    *,
    start: date,
    end: date,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return one row per user for the date range.

    Combines live ``usage_events`` with historical traces from claims, LLM
    assists, VMMR, partner API logs, and chat drafts.

    Status:
    - ``accessed`` — activity in the selected range (live or historical)
    - ``not_accessed`` — has older activity, none in this range
    - ``no_data`` — no live events and no historical evidence anywhere
    """
    if end < start:
        start, end = end, start
    start_dt, end_dt = _as_utc_day_bounds(start, end)

    user_stmt = select(User).order_by(
        User.is_active.desc(), User.username.asc(), User.id.asc()
    )
    if user_id is not None:
        user_stmt = user_stmt.where(User.id == user_id)
    users = list(db.scalars(user_stmt).all())
    if not users:
        return []

    user_ids = [u.id for u in users]

    ever_live = set(
        int(uid)
        for uid in db.scalars(
            select(UsageEvent.user_id)
            .where(UsageEvent.user_id.in_(user_ids))
            .distinct()
        ).all()
        if uid is not None
    )
    ever_evidence = user_ids_with_any_evidence(db, user_ids)
    ever_ids = ever_live | ever_evidence

    day_col = cast(UsageEvent.occurred_at, Date).label("day")

    agg_stmt = (
        select(
            UsageEvent.user_id,
            func.min(UsageEvent.occurred_at).label("first_seen"),
            func.max(UsageEvent.occurred_at).label("last_seen"),
            func.count(UsageEvent.id).label("total_events"),
        )
        .where(UsageEvent.occurred_at >= start_dt)
        .where(UsageEvent.occurred_at <= end_dt)
        .where(UsageEvent.user_id.in_(user_ids))
        .group_by(UsageEvent.user_id)
    )
    aggregates = {
        int(r.user_id): r for r in db.execute(agg_stmt).all() if r.user_id is not None
    }

    area_stmt = (
        select(
            UsageEvent.user_id,
            UsageEvent.feature_area,
            func.count(UsageEvent.id).label("cnt"),
        )
        .where(UsageEvent.occurred_at >= start_dt)
        .where(UsageEvent.occurred_at <= end_dt)
        .where(UsageEvent.user_id.in_(user_ids))
        .group_by(UsageEvent.user_id, UsageEvent.feature_area)
    )
    area_map: dict[int, dict[str, int]] = {}
    for uid, area, cnt in db.execute(area_stmt).all():
        if uid is None:
            continue
        area_map.setdefault(int(uid), {})[str(area)] = int(cnt)

    days_stmt = (
        select(UsageEvent.user_id, day_col)
        .where(UsageEvent.occurred_at >= start_dt)
        .where(UsageEvent.occurred_at <= end_dt)
        .where(UsageEvent.user_id.in_(user_ids))
        .group_by(UsageEvent.user_id, day_col)
        .order_by(UsageEvent.user_id.asc(), day_col.asc())
    )
    days_map: dict[int, list[str]] = {}
    for uid, day in db.execute(days_stmt).all():
        if uid is None:
            continue
        days_map.setdefault(int(uid), []).append(
            day.isoformat() if hasattr(day, "isoformat") else str(day)
        )

    # Historical evidence in range (skip rows already imported as LEGACY usage_events
    # to avoid double-counting after backfill).
    evidence = collect_usage_evidence(db, user_ids=user_ids, start=start, end=end)
    legacy_routes = set(
        db.scalars(
            select(UsageEvent.endpoint_or_route)
            .where(UsageEvent.user_id.in_(user_ids))
            .where(UsageEvent.endpoint_or_route.startswith("LEGACY|"))
        ).all()
    )

    evidence_first: dict[int, datetime] = {}
    evidence_last: dict[int, datetime] = {}
    evidence_counts: dict[int, dict[str, int]] = {}
    evidence_days: dict[int, list[str]] = {}
    evidence_totals: dict[int, int] = {}
    evidence_sources: dict[int, set[str]] = {}

    for ev in evidence:
        route = ev["endpoint_or_route"]
        if route in legacy_routes:
            continue
        uid = int(ev["user_id"])
        at: datetime = ev["occurred_at"]
        area = str(ev["feature_area"])
        evidence_totals[uid] = evidence_totals.get(uid, 0) + 1
        evidence_counts.setdefault(uid, {})
        evidence_counts[uid][area] = evidence_counts[uid].get(area, 0) + 1
        evidence_sources.setdefault(uid, set()).add(str(ev.get("source") or "history"))
        if uid not in evidence_first or at < evidence_first[uid]:
            evidence_first[uid] = at
        if uid not in evidence_last or at > evidence_last[uid]:
            evidence_last[uid] = at
        day_s = at.date().isoformat()
        _merge_day(evidence_days.setdefault(uid, []), day_s)

    rows: list[dict[str, Any]] = []
    for user in users:
        uid = user.id
        agg = aggregates.get(uid)
        counts = dict(area_map.get(uid, {}))
        active_days = list(days_map.get(uid, []))
        first_seen_dt = agg.first_seen if agg else None
        last_seen_dt = agg.last_seen if agg else None
        total = int(agg.total_events) if agg else 0
        sources: set[str] = set()
        if total > 0:
            sources.add("usage_events")

        # Merge evidence not already backfilled
        e_total = evidence_totals.get(uid, 0)
        if e_total:
            total += e_total
            sources |= evidence_sources.get(uid, set())
            for area, cnt in evidence_counts.get(uid, {}).items():
                counts[area] = counts.get(area, 0) + cnt
            for d in evidence_days.get(uid, []):
                _merge_day(active_days, d)
            ef = evidence_first.get(uid)
            el = evidence_last.get(uid)
            if ef and (first_seen_dt is None or ef < first_seen_dt):
                first_seen_dt = ef
            if el and (last_seen_dt is None or el > last_seen_dt):
                last_seen_dt = el

        active_days.sort()
        features = sorted(counts.keys())

        if total > 0:
            status = "accessed"
            status_label = "Accessed"
            date_label = (
                f"{active_days[0]} → {active_days[-1]}"
                if len(active_days) > 1
                else (active_days[0] if active_days else start.isoformat())
            )
            first_seen = first_seen_dt.isoformat() if first_seen_dt else None
            last_seen = last_seen_dt.isoformat() if last_seen_dt else None
        elif uid in ever_ids:
            status = "not_accessed"
            status_label = "Not accessed"
            date_label = "Not accessed"
            first_seen = None
            last_seen = None
            features = []
            counts = {}
            active_days = []
            sources = set()
        else:
            status = "no_data"
            status_label = "No data"
            date_label = "No data"
            first_seen = None
            last_seen = None
            features = []
            counts = {}
            active_days = []
            sources = set()

        rows.append(
            {
                "user": {
                    "id": uid,
                    "username": _user_label(user),
                    "full_name": user.full_name,
                    "is_active": bool(user.is_active),
                },
                "status": status,
                "status_label": status_label,
                "date": date_label,
                "active_days": active_days,
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "features_used": features,
                "event_counts": counts,
                "total_events": total,
                "evidence_sources": sorted(sources),
            }
        )

    order = {"accessed": 0, "not_accessed": 1, "no_data": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["user"]["username"].lower()))
    return rows


def usage_event_detail(
    db: Session,
    *,
    user_id: int,
    start: date,
    end: date,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Event-level detail: live usage_events plus non-imported historical traces."""
    if end < start:
        start, end = end, start
    start_dt, end_dt = _as_utc_day_bounds(start, end)
    rows = db.scalars(
        select(UsageEvent)
        .where(UsageEvent.user_id == user_id)
        .where(UsageEvent.occurred_at >= start_dt)
        .where(UsageEvent.occurred_at <= end_dt)
        .order_by(UsageEvent.occurred_at.asc())
        .limit(limit)
    ).all()
    live = [
        {
            "id": r.id,
            "event_type": r.event_type,
            "feature_area": r.feature_area,
            "endpoint_or_route": r.endpoint_or_route,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "ip_address": r.ip_address,
            "metadata": r.metadata_json,
            "source": (
                (r.metadata_json or {}).get("source")
                if isinstance(r.metadata_json, dict)
                else None
            )
            or ("legacy" if (r.endpoint_or_route or "").startswith("LEGACY|") else "usage_events"),
        }
        for r in rows
    ]
    legacy_routes = {r.endpoint_or_route for r in rows if (r.endpoint_or_route or "").startswith("LEGACY|")}
    # Also include any LEGACY routes for this user outside the limited live set
    legacy_routes |= set(
        db.scalars(
            select(UsageEvent.endpoint_or_route)
            .where(UsageEvent.user_id == user_id)
            .where(UsageEvent.endpoint_or_route.startswith("LEGACY|"))
        ).all()
    )

    evidence = collect_usage_evidence(db, user_ids=[user_id], start=start, end=end)
    hist = []
    for ev in evidence:
        if ev["endpoint_or_route"] in legacy_routes:
            continue
        hist.append(
            {
                "id": ev["id"],
                "event_type": ev["event_type"],
                "feature_area": ev["feature_area"],
                "endpoint_or_route": ev["endpoint_or_route"],
                "occurred_at": ev["occurred_at"].isoformat(),
                "ip_address": None,
                "metadata": ev.get("metadata"),
                "source": ev.get("source") or "history",
            }
        )

    combined = live + hist
    combined.sort(key=lambda e: e.get("occurred_at") or "")
    return combined[:limit]
