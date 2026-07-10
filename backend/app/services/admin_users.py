"""Admin user provisioning and lifecycle."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import ROLE_ADMIN, ROLE_USER, normalize_role, role_label
from app.core.security import hash_password
from app.models import User
from app.services.mail import MailDeliveryError, send_new_user_credentials

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
            "role_label": role_label(row.role),
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
    role: str = ROLE_USER,
    plain_password: str | None = None,
    send_email: bool = True,
) -> dict:
    normalized = _normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise ValueError("A valid email address is required")

    role_value = normalize_role(role)

    existing = db.scalar(
        select(User).where((User.email == normalized) | (User.username == normalized))
    )
    if existing and existing.is_active:
        raise ValueError("A user with this email already exists")

    password = plain_password or secrets.token_urlsafe(12)
    local_part = normalized.split("@", 1)[0]
    display_name = local_part.replace(".", " ").title()[:128]

    if existing and not existing.is_active:
        user = existing
        user.username = normalized
        user.email = normalized
        user.password_hash = hash_password(password)
        user.full_name = display_name
        user.role = role_value
        user.is_active = True
    else:
        user = User(
            username=normalized,
            email=normalized,
            password_hash=hash_password(password),
            full_name=display_name,
            role=role_value,
            is_active=True,
        )
        db.add(user)

    try:
        db.flush()
        if send_email:
            send_new_user_credentials(
                to_email=normalized,
                password=password,
                login_url=login_url,
            )
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "role_label": role_label(user.role),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "email_sent": bool(send_email),
    }


def update_user_role(
    db: Session,
    *,
    user_id: int,
    role: str,
    acting_admin_id: int,
) -> dict:
    role_value = normalize_role(role)
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise ValueError("User not found")

    if user.role == ROLE_ADMIN and role_value != ROLE_ADMIN:
        admin_count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == ROLE_ADMIN, User.is_active.is_(True))
        )
        if admin_count is not None and admin_count <= 1:
            raise ValueError("Cannot demote the last active admin")

    if user.id == acting_admin_id and role_value != ROLE_ADMIN:
        raise ValueError("You cannot remove your own admin role")

    user.role = role_value
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "email": user.email or user.username,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "role_label": role_label(user.role),
        "is_active": user.is_active,
    }


def deactivate_user(db: Session, *, user_id: int, acting_admin_id: int) -> None:
    if user_id == acting_admin_id:
        raise ValueError("You cannot delete your own account")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise ValueError("User not found")

    if user.role == ROLE_ADMIN:
        admin_count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == ROLE_ADMIN, User.is_active.is_(True))
        )
        if admin_count is not None and admin_count <= 1:
            raise ValueError("Cannot delete the last active admin")

    user.is_active = False
    db.commit()
