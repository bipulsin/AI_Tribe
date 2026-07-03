"""Auth routes: login page, session cookie login/logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import verify_password
from app.models import User

router = APIRouter(tags=["auth"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/claims/new", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@router.post("/auth/login")
async def auth_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username.strip()))
    is_htmx = request.headers.get("HX-Request") == "true"

    if not user or not verify_password(password, user.password_hash):
        error = "Incorrect username or password."
        if is_htmx:
            # 200 so HTMX swaps the error partial into the card (no full reload).
            return templates.TemplateResponse(
                "partials/login_error.html",
                {"request": request, "error": error},
            )
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": error},
            status_code=401,
        )

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["full_name"] = user.full_name
    request.session["role"] = user.role

    if is_htmx:
        response = HTMLResponse(content="", status_code=200)
        response.headers["HX-Redirect"] = "/claims/new"
        return response

    return RedirectResponse(url="/claims/new", status_code=303)


@router.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/auth/logout")
async def auth_logout_get(request: Request):
    """Allow simple link-based logout for the POC."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
