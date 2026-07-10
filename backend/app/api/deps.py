"""Auth helpers for route handlers."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.roles import ROLE_ADMIN, can_view_all_claims
from app.models import Claim, User


def require_admin(request: Request, db: Session) -> User | JSONResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role != ROLE_ADMIN:
        return JSONResponse({"detail": "Admin only"}, status_code=403)
    return user


def session_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return None
    return user


def user_can_access_claim(user: User | None, claim: Claim | None) -> bool:
    if not user or not claim:
        return False
    if can_view_all_claims(user.role):
        return True
    return claim.created_by == user.id


def claim_for_session(db: Session, request: Request, claim_id: int) -> Claim | None:
    user = session_user(request, db)
    claim = db.get(Claim, claim_id)
    if not user_can_access_claim(user, claim):
        return None
    return claim
