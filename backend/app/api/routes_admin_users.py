"""Admin user management API."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.roles import ROLE_ADMIN, ROLE_LABELS, VALID_ROLES
from app.models import User
from app.services.admin_users import (
    create_user_with_email,
    deactivate_user,
    list_users,
    update_user_role,
)
from app.services.mail import MailDeliveryError

router = APIRouter(tags=["admin-users"])


def _admin_user(request: Request, db: Session) -> User | JSONResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    if user.role != ROLE_ADMIN:
        return JSONResponse({"detail": "Admin only"}, status_code=403)
    return user


@router.get("/api/admin/users")
async def get_users(request: Request, db: Session = Depends(get_db)):
    admin = _admin_user(request, db)
    if isinstance(admin, JSONResponse):
        return admin
    return {
        "users": list_users(db),
        "roles": [{"value": key, "label": ROLE_LABELS[key]} for key in sorted(VALID_ROLES)],
    }


@router.post("/api/admin/users")
async def post_user(request: Request, db: Session = Depends(get_db)):
    admin = _admin_user(request, db)
    if isinstance(admin, JSONResponse):
        return admin

    body = await request.json()
    email = (body.get("email") or "").strip()
    role = (body.get("role") or "user").strip()
    if not email:
        return JSONResponse({"detail": "Email is required"}, status_code=400)

    login_url = os.environ.get("APP_PUBLIC_URL", "https://tribe.tradentical.com").rstrip("/") + "/login"

    try:
        row = create_user_with_email(db, email=email, login_url=login_url, role=role)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except MailDeliveryError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    return row


@router.patch("/api/admin/users/{user_id}/role")
async def patch_user_role(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = _admin_user(request, db)
    if isinstance(admin, JSONResponse):
        return admin

    body = await request.json()
    role = (body.get("role") or "").strip()
    if not role:
        return JSONResponse({"detail": "Role is required"}, status_code=400)

    try:
        row = update_user_role(
            db, user_id=user_id, role=role, acting_admin_id=admin.id
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    return row


@router.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _admin_user(request, db)
    if isinstance(admin, JSONResponse):
        return admin

    try:
        deactivate_user(db, user_id=user_id, acting_admin_id=admin.id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    return {"deleted": True, "user_id": user_id}
