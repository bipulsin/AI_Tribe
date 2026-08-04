"""Aggregate usage_events into per-user-per-day Usability Report rows."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.usage_event import UsageEvent


def _as_utc_day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    # Inclusive end date → start of next day exclusive
    end_exclusive = datetime.combine(end, time.max, tzinfo=timezone.utc)
    return start_dt, end_exclusive


def build_usage_report(
    db: Session,
    *,
    start: date,
    end: date,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return one row per user per UTC day with feature areas and counts."""
    if end < start:
        start, end = end, start
    start_dt, end_dt = _as_utc_day_bounds(start, end)

    day_col = cast(UsageEvent.occurred_at, Date).label("day")

    stmt = (
        select(
            UsageEvent.user_id,
            UsageEvent.username_snapshot,
            day_col,
            func.min(UsageEvent.occurred_at).label("first_seen"),
            func.max(UsageEvent.occurred_at).label("last_seen"),
            func.count(UsageEvent.id).label("total_events"),
        )
        .where(UsageEvent.occurred_at >= start_dt)
        .where(UsageEvent.occurred_at <= end_dt)
        .where(UsageEvent.user_id.is_not(None))
        .group_by(UsageEvent.user_id, UsageEvent.username_snapshot, day_col)
        .order_by(day_col.desc(), UsageEvent.user_id.asc())
    )
    if user_id is not None:
        stmt = stmt.where(UsageEvent.user_id == user_id)

    aggregates = db.execute(stmt).all()
    if not aggregates:
        return []

    # Feature-area counts per (user_id, day)
    area_stmt = (
        select(
            UsageEvent.user_id,
            day_col,
            UsageEvent.feature_area,
            func.count(UsageEvent.id).label("cnt"),
        )
        .where(UsageEvent.occurred_at >= start_dt)
        .where(UsageEvent.occurred_at <= end_dt)
        .where(UsageEvent.user_id.is_not(None))
        .group_by(UsageEvent.user_id, day_col, UsageEvent.feature_area)
    )
    if user_id is not None:
        area_stmt = area_stmt.where(UsageEvent.user_id == user_id)

    area_rows = db.execute(area_stmt).all()
    area_map: dict[tuple[int, date], dict[str, int]] = {}
    for uid, day, area, cnt in area_rows:
        key = (int(uid), day)
        area_map.setdefault(key, {})[str(area)] = int(cnt)

    # Resolve display usernames from users table when possible
    user_ids = {int(r.user_id) for r in aggregates if r.user_id is not None}
    users = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    }

    rows: list[dict[str, Any]] = []
    for row in aggregates:
        uid = int(row.user_id)
        day = row.day
        user = users.get(uid)
        username = (
            (user.email or user.username)
            if user
            else (row.username_snapshot or f"user:{uid}")
        )
        counts = area_map.get((uid, day), {})
        features = sorted(counts.keys())
        rows.append(
            {
                "user": {
                    "id": uid,
                    "username": username,
                    "full_name": (user.full_name if user else None),
                },
                "date": day.isoformat() if hasattr(day, "isoformat") else str(day),
                "first_seen": row.first_seen.isoformat() if row.first_seen else None,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                "features_used": features,
                "event_counts": counts,
                "total_events": int(row.total_events),
            }
        )
    return rows


def usage_event_detail(
    db: Session,
    *,
    user_id: int,
    day: date,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Event-level detail for one user on one UTC day."""
    start_dt, end_dt = _as_utc_day_bounds(day, day)
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


def list_report_users(db: Session) -> list[dict[str, Any]]:
    """Users that appear in usage_events (for filter dropdown)."""
    ids = db.scalars(
        select(UsageEvent.user_id)
        .where(UsageEvent.user_id.is_not(None))
        .distinct()
        .order_by(UsageEvent.user_id.asc())
    ).all()
    if not ids:
        return []
    users = db.scalars(select(User).where(User.id.in_(list(ids))).order_by(User.username)).all()
    return [
        {
            "id": u.id,
            "username": u.email or u.username,
            "full_name": u.full_name,
        }
        for u in users
    ]
