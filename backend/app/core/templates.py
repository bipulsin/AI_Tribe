"""Shared Jinja2 templates with i18n globals."""

from __future__ import annotations

from functools import lru_cache

from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.i18n.catalog import setup_jinja_globals


@lru_cache
def get_templates() -> Jinja2Templates:
    settings = get_settings()
    tpl = Jinja2Templates(directory=str(settings.templates_dir))
    setup_jinja_globals(tpl.env)
    return tpl


templates = get_templates()
