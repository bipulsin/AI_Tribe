"""Admin Usability Report page and API."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.services.usage_report_service import (
    build_usage_report,
    list_report_users,
    usage_event_detail,
)

router = APIRouter(tags=["usage-report"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


def _parse_day(value: str | None, *, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return default


@router.get("/admin/usage-report", response_class=HTMLResponse)
async def usage_report_page(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        # HTML: redirect to login / claims
        from fastapi.responses import RedirectResponse

        if admin.status_code == 401:
            return RedirectResponse(url="/login", status_code=303)
        return RedirectResponse(url="/claims/new", status_code=303)

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=13)
    return templates.TemplateResponse(
        "usage_report.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", "") or "",
            "default_start": start.isoformat(),
            "default_end": today.isoformat(),
            "users": list_report_users(db),
        },
    )


@router.get("/api/admin/usage-report")
async def usage_report_api(
    request: Request,
    db: Session = Depends(get_db),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
):
    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        return admin

    today = datetime.now(timezone.utc).date()
    start_d = _parse_day(start, default=today - timedelta(days=13))
    end_d = _parse_day(end, default=today)
    rows = build_usage_report(db, start=start_d, end=end_d, user_id=user_id)
    return {
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "rows": rows,
        "users": list_report_users(db),
    }


@router.get("/api/admin/usage-report/detail")
async def usage_report_detail_api(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Query(...),
    day: str = Query(...),
):
    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        return admin
    try:
        day_d = date.fromisoformat(day.strip()[:10])
    except ValueError:
        return JSONResponse({"detail": "Invalid day"}, status_code=400)
    return {
        "user_id": user_id,
        "date": day_d.isoformat(),
        "events": usage_event_detail(db, user_id=user_id, day=day_d),
    }
