"""Outbound email for admin user provisioning."""

from __future__ import annotations

import logging
import os
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

logger = logging.getLogger("ai_tribe.mail")

DEFAULT_FROM = "webnetin@gmail.com"
DEFAULT_FROM_NAME = "AI Tribe"


def _smtp_config() -> tuple[str, int, str, str, str, str] | None:
    user = os.environ.get("SMTP_USER", DEFAULT_FROM).strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not password:
        return None
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("SMTP_FROM", user or DEFAULT_FROM).strip()
    from_name = os.environ.get("SMTP_FROM_NAME", DEFAULT_FROM_NAME).strip() or DEFAULT_FROM_NAME
    return host, port, user, password, from_addr, from_name


class MailDeliveryError(RuntimeError):
    """Raised when outbound mail cannot be delivered."""


def send_new_user_credentials(*, to_email: str, password: str, login_url: str) -> None:
    """Email a one-time generated password to a new user."""
    cfg = _smtp_config()
    if not cfg:
        raise MailDeliveryError(
            "SMTP_PASSWORD is not configured on the server; cannot send welcome email."
        )

    host, port, user, smtp_password, from_addr, from_name = cfg
    domain = from_addr.rsplit("@", 1)[-1] if "@" in from_addr else "localhost"

    msg = EmailMessage()
    msg["Subject"] = "Your AI Tribe account is ready"
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to_email
    msg["Reply-To"] = from_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain, idstring=uuid.uuid4().hex[:12])
    msg["X-Auto-Response-Suppress"] = "All"
    msg["Auto-Submitted"] = "auto-generated"

    text_body = (
        "Welcome to AI Tribe — Motor Damage Assessment.\n\n"
        "Your account has been created. Use these details to sign in:\n\n"
        f"  Sign-in page: {login_url}\n"
        f"  Username:     {to_email}\n"
        f"  Temp password: {password}\n\n"
        "After your first login, open Profile and change this password.\n"
        "If you did not expect this email, you can ignore it.\n"
    )
    html_body = f"""\
<html><body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #1a1a1a;">
  <p>Welcome to <strong>AI Tribe</strong> — Motor Damage Assessment.</p>
  <p>Your account has been created. Use these details to sign in:</p>
  <ul>
    <li>Sign-in page: <a href="{login_url}">{login_url}</a></li>
    <li>Username: <code>{to_email}</code></li>
    <li>Temporary password: <code>{password}</code></li>
  </ul>
  <p>After your first login, open <strong>Profile</strong> and change this password.</p>
  <p style="color:#666;font-size:12px;">If you did not expect this email, you can ignore it.</p>
</body></html>
"""
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, smtp_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailDeliveryError(
            "Gmail SMTP login failed. Set SMTP_PASSWORD to a Gmail App Password "
            "(Google Account → Security → App passwords), not your regular login password."
        ) from exc
    except smtplib.SMTPException as exc:
        raise MailDeliveryError(f"Could not send welcome email: {exc}") from exc

    logger.info("Sent welcome email to %s", to_email)
