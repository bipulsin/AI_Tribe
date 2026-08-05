"""Language cookie route and helpers."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.i18n.catalog import DEFAULT_LANG, LANG_COOKIE, SUPPORTED_LANGS, resolve_lang

router = APIRouter(tags=["i18n"])

_COOKIE_MAX_AGE = 365 * 24 * 3600


def _safe_next_path(raw: str | None, *, fallback: str = "/") -> str:
    if not raw:
        return fallback
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    path = parsed.path or fallback
    if not path.startswith("/"):
        return fallback
    if path.startswith("//"):
        return fallback
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


@router.get("/lang/{code}")
async def set_language(
    code: str,
    request: Request,
    next: str | None = Query(default=None, alias="next"),
):
    """Set ``atr_lang`` cookie and reload the current page."""
    lang = resolve_lang(code)
    target = _safe_next_path(next, fallback=request.url.path or "/")
    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie(
        LANG_COOKIE,
        lang,
        max_age=_COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/api/i18n/smoke")
async def i18n_smoke(request: Request):
    """Smoke check: effective language from cookie (defaults to en)."""
    from app.i18n.catalog import get_lang, translate

    lang = get_lang()
    return {
        "lang": lang,
        "cookie": request.cookies.get(LANG_COOKIE, DEFAULT_LANG),
        "sample": translate("app.name"),
        "supported": sorted(SUPPORTED_LANGS),
    }
