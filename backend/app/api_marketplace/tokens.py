"""API token lifecycle: generate, reveal, auth lookup, expiry reminders."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_marketplace.catalog import DEFAULT_VALIDITY_DAYS, VALIDITY_DAYS
from app.api_marketplace.crypto import (
    TokenCryptoError,
    decrypt_token,
    encrypt_token,
    generate_live_token,
    hash_token,
    token_prefix,
)
from app.api_marketplace.models import ApiToken, ApiTokenRevealLog
from app.models import User
from app.services.mail import MailDeliveryError

logger = logging.getLogger("ai_tribe.api_marketplace")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def current_token(db: Session, user_id: int) -> ApiToken | None:
    return db.scalar(
        select(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.is_current.is_(True))
        .order_by(ApiToken.issued_at.desc())
    )


def issue_token(
    db: Session,
    *,
    user_id: int,
    validity_days: int = DEFAULT_VALIDITY_DAYS,
    ip_address: str | None = None,
) -> tuple[ApiToken, str]:
    if validity_days not in VALIDITY_DAYS:
        raise ValueError(f"validity_days must be one of {VALIDITY_DAYS}")

    now = _utcnow()
    previous = (
        db.scalars(
            select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.is_current.is_(True))
        ).all()
    )
    for row in previous:
        row.is_current = False
        row.revoked_at = now

    plain = generate_live_token()
    row = ApiToken(
        user_id=user_id,
        token_hash=hash_token(plain),
        token_prefix=token_prefix(plain),
        token_encrypted=encrypt_token(plain),
        validity_days=validity_days,
        issued_at=now,
        expires_at=now + timedelta(days=validity_days),
        is_current=True,
        created_by_ip=ip_address,
        reminder_sent_7d=False,
        reminder_sent_1d=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plain


def reveal_token(
    db: Session,
    *,
    user_id: int,
    ip_address: str | None = None,
) -> tuple[ApiToken, str]:
    row = current_token(db, user_id)
    if not row:
        raise ValueError("No current API token. Generate one first.")
    plain = decrypt_token(row.token_encrypted)
    db.add(
        ApiTokenRevealLog(
            user_id=user_id,
            token_prefix=row.token_prefix,
            ip_address=ip_address,
        )
    )
    db.commit()
    return row, plain


def authenticate_bearer(db: Session, bearer: str) -> tuple[User, ApiToken] | tuple[None, str]:
    """Hash-compare bearer token. Returns (user, token) or (None, error_code)."""
    plain = (bearer or "").strip()
    if not plain:
        return None, "TOKEN_MISSING"
    digest = hash_token(plain)
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
    if not row or not row.is_current:
        return None, "TOKEN_INVALID"
    now = _utcnow()
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        return None, "TOKEN_EXPIRED"
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        return None, "TOKEN_INVALID"
    return user, row


def token_public_view(row: ApiToken | None) -> dict | None:
    if not row:
        return None
    now = _utcnow()
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    days_left = max(0, (expires.date() - now.date()).days)
    return {
        "token_prefix": row.token_prefix,
        "validity_days": row.validity_days,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "expires_at": expires.isoformat(),
        "days_remaining": days_left,
        "expiring_soon": days_left <= 14,
        "is_expired": expires < now,
    }


def send_token_expiry_email(*, to_email: str, expires_at: datetime, days_left: int) -> None:
    """Reuse SMTP stack; dedicated subject via EmailMessage."""
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr, formatdate, make_msgid

    from app.services.mail import DEFAULT_FROM, DEFAULT_FROM_NAME, _smtp_config

    cfg = _smtp_config()
    if not cfg:
        raise MailDeliveryError("SMTP is not configured")
    host, port, user, smtp_password, from_addr, from_name = cfg
    domain = from_addr.rsplit("@", 1)[-1] if "@" in from_addr else "localhost"
    login_url = (
        os.environ.get("APP_PUBLIC_URL", "https://tribe.tradentical.com").rstrip("/")
        + "/settings/api-marketplace"
    )
    when = expires_at.date().isoformat()
    msg = EmailMessage()
    msg["Subject"] = f"AI Tribe API token expires in {days_left} day{'s' if days_left != 1 else ''}"
    msg["From"] = formataddr((from_name or DEFAULT_FROM_NAME, from_addr or DEFAULT_FROM))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(
        "Your AI Tribe API Marketplace token will expire soon.\n\n"
        f"Expires on: {when}\n"
        f"Days remaining: {days_left}\n\n"
        f"Renew it here: {login_url}\n\n"
        "After expiry, external API calls will return TOKEN_EXPIRED until you generate a new token.\n"
    )
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, smtp_password)
        smtp.send_message(msg)


def process_token_expiry_reminders(db: Session) -> dict:
    """Daily job: email 7d and 1d reminders for current tokens."""
    now = _utcnow()
    rows = db.scalars(
        select(ApiToken).where(ApiToken.is_current.is_(True), ApiToken.revoked_at.is_(None))
    ).all()
    sent_7d = sent_1d = 0
    for row in rows:
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            continue
        days_left = (expires.date() - now.date()).days
        user = db.get(User, row.user_id)
        email = (user.email or user.username) if user else None
        if not email or "@" not in email:
            continue
        try:
            if days_left <= 7 and not row.reminder_sent_7d:
                send_token_expiry_email(to_email=email, expires_at=expires, days_left=days_left)
                row.reminder_sent_7d = True
                sent_7d += 1
            if days_left <= 1 and not row.reminder_sent_1d:
                send_token_expiry_email(to_email=email, expires_at=expires, days_left=max(days_left, 1))
                row.reminder_sent_1d = True
                sent_1d += 1
        except (MailDeliveryError, TokenCryptoError, OSError) as exc:
            logger.warning("Token reminder failed for user %s: %s", row.user_id, exc)
    db.commit()
    return {"sent_7d": sent_7d, "sent_1d": sent_1d}
