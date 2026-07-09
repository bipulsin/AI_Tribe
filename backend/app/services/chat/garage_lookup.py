"""Garage discovery helpers for contextual chat lookup."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Claim, Garage

_KOCHI_PATTERNS = ("%kochi%", "%cochi%", "%cochin%")


def _city_patterns(city_key: str) -> tuple[str, ...]:
    if city_key == "kochi":
        return _KOCHI_PATTERNS
    return (f"%{city_key}%",)


def find_garages_for_city(
    db: Session, city_key: str, *, user_id: int | None = None
) -> list[str]:
    """Return distinct garage names tied to the user's claims in/near a city."""
    patterns = _city_patterns(city_key)
    garage_filters = [Garage.name.ilike(p) for p in patterns]

    stmt = (
        select(Garage.name)
        .join(Claim, Claim.garage_id == Garage.id)
        .where(or_(*garage_filters))
        .distinct()
        .order_by(Garage.name)
    )
    if user_id is not None:
        stmt = stmt.where(Claim.created_by == user_id)

    return [row for row in db.scalars(stmt).all() if row]


def format_garage_pick_list(garages: list[str], city_label: str) -> str:
    city_title = city_label.title()
    if city_label == "kochi":
        city_title = "Kochi"
    lines = [
        f"I found these garages related to **{city_title}**:",
        "",
    ]
    for idx, name in enumerate(garages[:12], start=1):
        lines.append(f"{idx}. {name}")
    lines.extend(
        [
            "",
            "Reply with the garage name (or list number) to see matching claims.",
        ]
    )
    return "\n".join(lines)


def resolve_garage_choice(text: str, options: list[str]) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    lower = raw.lower()
    for name in options:
        if name.lower() == lower:
            return name
    for name in options:
        if lower in name.lower() or name.lower() in lower:
            return name
    return raw
