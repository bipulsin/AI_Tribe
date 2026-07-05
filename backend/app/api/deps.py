"""Admin auth helper for lab routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models import User


def require_admin(request: Request, db: Session) -> User | JSONResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user = db.get(User, user_id)
    if not user or user.role != "admin":
        return JSONResponse({"detail": "Admin only"}, status_code=403)
    return user
