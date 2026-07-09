"""Outbound email for admin user provisioning."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("ai_tribe.mail")

DEFAULT_FROM = "webnetin@gmail.com"


def _smtp_config() -> tuple[str, int, str, str, str] | None:
    user = os.environ.get("SMTP_USER", DEFAULT_FROM).strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not password:
        return None
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("SMTP_FROM", user or DEFAULT_FROM).strip()
    return host, port, user, password, from_addr


def send_new_user_credentials(*, to_email: str, password: str, login_url: str) -> None:
    """Email a one-time generated password to a new user."""
    cfg = _smtp_config()
    if not cfg:
        raise RuntimeError(
            "SMTP_PASSWORD is not configured on the server; cannot send welcome email."
        )

    host, port, user, smtp_password, from_addr = cfg
    msg = EmailMessage()
    msg["Subject"] = "Your AI Tribe account"
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(
        "Welcome to AI Tribe: Motor Damage Assessment.\n\n"
        f"Login URL: {login_url}\n"
        f"Email / username: {to_email}\n"
        f"Temporary password: {password}\n\n"
        "Please sign in and change your password from Profile after your first login.\n"
        "This password is stored encrypted on the server and is not visible to administrators.\n"
    )

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, smtp_password)
        smtp.send_message(msg)

    logger.info("Sent welcome email to %s", to_email)
