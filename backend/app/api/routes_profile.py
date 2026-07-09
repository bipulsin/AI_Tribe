"""User profile and settings shell routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models import User
from app.services.user_profile import (
    delete_profile_photo,
    parse_date_of_birth,
    profile_photo_path,
    profile_to_dict,
    save_profile_photo,
)

router = APIRouter(tags=["profile"])


def _current_user(request: Request, db: Session) -> User | JSONResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user = db.get(User, user_id)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return user


@router.get("/api/user/profile")
async def get_profile(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    return profile_to_dict(user)


@router.patch("/api/user/profile/full-name")
async def update_full_name(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    body = await request.json()
    full_name = (body.get("full_name") or "").strip()
    if not full_name:
        return JSONResponse({"detail": "Full name is required"}, status_code=400)
    if len(full_name) > 128:
        return JSONResponse({"detail": "Full name is too long"}, status_code=400)
    user.full_name = full_name
    db.commit()
    request.session["full_name"] = full_name
    return {"full_name": full_name}


@router.patch("/api/user/profile/date-of-birth")
async def update_date_of_birth(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    body = await request.json()
    raw = body.get("date_of_birth")
    try:
        user.date_of_birth = parse_date_of_birth(raw)
    except ValueError:
        return JSONResponse({"detail": "Invalid date (use YYYY-MM-DD)"}, status_code=400)
    db.commit()
    return {"date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None}


@router.post("/api/user/profile/password")
async def change_password(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    body = await request.json()
    current = body.get("current_password") or ""
    new_password = body.get("new_password") or ""
    if not current or not new_password:
        return JSONResponse({"detail": "Current and new password are required"}, status_code=400)
    if len(new_password) < 8:
        return JSONResponse({"detail": "New password must be at least 8 characters"}, status_code=400)
    if not verify_password(current, user.password_hash):
        return JSONResponse({"detail": "Current password is incorrect"}, status_code=400)
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"detail": "Password updated"}


@router.post("/api/user/profile/photo")
async def upload_profile_photo(
    request: Request,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    if not photo.filename:
        return JSONResponse({"detail": "Photo file required"}, status_code=400)
    data = await photo.read()
    try:
        save_profile_photo(user.id, data, photo.filename)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"detail": "Could not process image"}, status_code=400)
    db.refresh(user)
    return profile_to_dict(user)


@router.delete("/api/user/profile/photo")
async def remove_profile_photo(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    delete_profile_photo(user.id)
    return {"has_photo": False, "photo_url": None}


@router.get("/api/user/profile/photo")
async def get_profile_photo(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    path = profile_photo_path(user.id)
    if not path:
        return JSONResponse({"detail": "No profile photo"}, status_code=404)
    return FileResponse(path, media_type="image/jpeg")
