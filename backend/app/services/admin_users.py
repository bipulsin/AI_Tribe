"""Admin user provisioning and lifecycle."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import User
from app.services.mail import send_new_user_credentials

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def list_users(db: Session) -> list[dict]:
    rows = db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())).all()
    return [
        {
            "id": row.id,
            "email": row.email or row.username,
            "username": row.username,
            "full_name": row.full_name,
            "role": row.role,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def create_user_with_email(
    db: Session,
    *,
    email: str,
    login_url: str,
) -> dict:
    normalized = _normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise ValueError("A valid email address is required")

    existing = db.scalar(
        select(User).where((User.email == normalized) | (User.username == normalized))
    )
    if existing:
        raise ValueError("A user with this email already exists")

    plain_password = secrets.token_urlsafe(12)
    local_part = normalized.split("@", 1)[0]
    user = User(
        username=normalized,
        email=normalized,
        password_hash=hash_password(plain_password),
        full_name=local_part.replace(".", " ").title()[:128],
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    send_new_user_credentials(
        to_email=normalized,
        password=plain_password,
        login_url=login_url,
    )

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "email_sent": True,
    }


def deactivate_user(db: Session, *, user_id: int, acting_admin_id: int) -> None:
    if user_id == acting_admin_id:
        raise ValueError("You cannot delete your own account")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise ValueError("User not found")

    if user.role == "admin":
        admin_count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
        if admin_count is not None and admin_count <= 1:
            raise ValueError("Cannot delete the last active admin")

    user.is_active = False
    db.commit()
