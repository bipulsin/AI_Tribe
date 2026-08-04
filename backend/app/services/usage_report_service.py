"""Aggregate usage_events into per-user Usability Report rows (all users)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.usage_event import UsageEvent


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


def build_usage_report(
    db: Session,
    *,
    start: date,
    end: date,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return one row per user for the date range.

    Status:
    - ``accessed`` — has events in the selected range
    - ``not_accessed`` — has historical usage events, but none in this range
    - ``no_data`` — never recorded in usage_events
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

    # Users who have any usage_events ever
    ever_ids = set(
        db.scalars(
            select(UsageEvent.user_id)
            .where(UsageEvent.user_id.in_(user_ids))
            .distinct()
        ).all()
    )

    day_col = cast(UsageEvent.occurred_at, Date).label("day")

    # Aggregate within range
    agg_stmt = (
        select(
            UsageEvent.user_id,
            func.min(UsageEvent.occurred_at).label("first_seen"),
            func.max(UsageEvent.occurred_at).label("last_seen"),
            func.count(UsageEvent.id).label("total_events"),
            func.count(func.distinct(day_col)).label("active_days"),
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

    # Active days list for display (optional compact)
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

    rows: list[dict[str, Any]] = []
    for user in users:
        uid = user.id
        agg = aggregates.get(uid)
        counts = area_map.get(uid, {})
        features = sorted(counts.keys())
        active_days = days_map.get(uid, [])

        if agg and int(agg.total_events) > 0:
            status = "accessed"
            status_label = "Accessed"
            date_label = (
                f"{active_days[0]} → {active_days[-1]}"
                if len(active_days) > 1
                else (active_days[0] if active_days else start.isoformat())
            )
            first_seen = agg.first_seen.isoformat() if agg.first_seen else None
            last_seen = agg.last_seen.isoformat() if agg.last_seen else None
            total = int(agg.total_events)
        elif uid in ever_ids:
            status = "not_accessed"
            status_label = "Not accessed"
            date_label = "Not accessed"
            first_seen = None
            last_seen = None
            total = 0
            features = []
            counts = {}
            active_days = []
        else:
            status = "no_data"
            status_label = "No data"
            date_label = "No data"
            first_seen = None
            last_seen = None
            total = 0
            features = []
            counts = {}
            active_days = []

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
            }
        )

    # Accessed users first, then not accessed, then no data; stable by username
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
    """Event-level detail for one user over a UTC date range."""
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
    return [
        {
            "id": r.id,
            "event_type": r.event_type,
            "feature_area": r.feature_area,
            "endpoint_or_route": r.endpoint_or_route,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "ip_address": r.ip_address,
            "metadata": r.metadata_json,
        }
        for r in rows
    ]
