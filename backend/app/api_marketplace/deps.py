"""Auth / subscription / audit helpers for external API routes."""

from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import Request
from sqlalchemy.orm import Session

from app.api_marketplace.envelope import fail, new_request_id
from app.api_marketplace.models import ApiRequestLog
from app.api_marketplace.rate_limit import check_rate_limit
from app.api_marketplace.subscriptions import is_subscribed
from app.api_marketplace.tokens import authenticate_bearer
from app.models import User


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return (request.client.host or "")[:64]
    return None


def log_request(
    db: Session,
    *,
    user_id: int | None,
    token_prefix: str | None,
    api_name: str,
    claim_no: str | None,
    status_code: int,
    error_code: str | None,
    request_id: uuid.UUID,
    latency_ms: int | None,
    ip_address: str | None,
) -> None:
    db.add(
        ApiRequestLog(
            user_id=user_id,
            token_prefix=token_prefix,
            api_name=api_name,
            claim_no=claim_no,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
            latency_ms=latency_ms,
            ip_address=ip_address,
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()


async def require_external_auth(
    request: Request,
    db: Session,
    *,
    api_name: str,
) -> tuple[User, str, uuid.UUID] | object:
    """
    Returns (user, token_prefix, request_id) or a JSONResponse error.
    """
    request_id = new_request_id()
    request.state.api_request_id = request_id
    request.state.api_started = time.perf_counter()
    auth = request.headers.get("authorization") or ""
    bearer = ""
    if auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()

    result = authenticate_bearer(db, bearer)
    if result[0] is None:
        code = result[1]
        ip = client_ip(request)
        if code == "TOKEN_EXPIRED":
            # Look up expired token for date if possible
            from app.api_marketplace.crypto import hash_token
            from app.api_marketplace.models import ApiToken
            from sqlalchemy import select

            row = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(bearer)))
            expired_at = row.expires_at.isoformat() if row and row.expires_at else None
            message = (
                f"Your API token expired on {expired_at or 'an earlier date'}. "
                "Generate a new one from Settings → API Marketplace."
            )
            resp = fail(
                code="TOKEN_EXPIRED",
                message=message,
                request_id=request_id,
                status_code=401,
                extra={"expired_at": expired_at} if expired_at else None,
            )
        elif code == "TOKEN_MISSING":
            resp = fail(
                code="TOKEN_MISSING",
                message="Authorization Bearer token is required.",
                request_id=request_id,
                status_code=401,
            )
        else:
            resp = fail(
                code="TOKEN_INVALID",
                message="API token is invalid or revoked.",
                request_id=request_id,
                status_code=401,
            )
        log_request(
            db,
            user_id=None,
            token_prefix=bearer[:12] if bearer else None,
            api_name=api_name,
            claim_no=None,
            status_code=resp.status_code,
            error_code=code,
            request_id=request_id,
            latency_ms=None,
            ip_address=ip,
        )
        return resp

    user, token_row = result
    allowed, retry_after = check_rate_limit(user.id)
    if not allowed:
        resp = fail(
            code="RATE_LIMITED",
            message="Rate limit exceeded. Slow down and retry.",
            request_id=request_id,
            status_code=429,
            headers={"Retry-After": str(retry_after or 60)},
        )
        log_request(
            db,
            user_id=user.id,
            token_prefix=token_row.token_prefix,
            api_name=api_name,
            claim_no=None,
            status_code=429,
            error_code="RATE_LIMITED",
            request_id=request_id,
            latency_ms=None,
            ip_address=client_ip(request),
        )
        return resp

    if not is_subscribed(db, user.id, api_name):
        resp = fail(
            code="NOT_SUBSCRIBED",
            message=f"Subscribe to '{api_name}' in API Marketplace before calling this endpoint.",
            request_id=request_id,
            status_code=403,
        )
        log_request(
            db,
            user_id=user.id,
            token_prefix=token_row.token_prefix,
            api_name=api_name,
            claim_no=None,
            status_code=403,
            error_code="NOT_SUBSCRIBED",
            request_id=request_id,
            latency_ms=None,
            ip_address=client_ip(request),
        )
        return resp

    request.state.api_user = user
    request.state.api_token_prefix = token_row.token_prefix
    return user, token_row.token_prefix, request_id


def finish_log(
    db: Session,
    request: Request,
    *,
    api_name: str,
    claim_no: str | None,
    status_code: int,
    error_code: str | None = None,
) -> None:
    started = getattr(request.state, "api_started", None)
    latency = int((time.perf_counter() - started) * 1000) if started else None
    user = getattr(request.state, "api_user", None)
    request_id = getattr(request.state, "api_request_id", None) or new_request_id()
    log_request(
        db,
        user_id=user.id if user else None,
        token_prefix=getattr(request.state, "api_token_prefix", None),
        api_name=api_name,
        claim_no=claim_no,
        status_code=status_code,
        error_code=error_code,
        request_id=request_id,
        latency_ms=latency,
        ip_address=client_ip(request),
    )
