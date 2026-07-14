"""Consistent response envelope helpers for the external API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.responses import JSONResponse


def new_request_id() -> uuid.UUID:
    return uuid.uuid4()


def ok(data: Any, *, request_id: uuid.UUID, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        {
            "success": True,
            "data": data,
            "error": None,
            "request_id": str(request_id),
        },
        status_code=status_code,
    )


def fail(
    *,
    code: str,
    message: str,
    request_id: uuid.UUID,
    status_code: int = 400,
    details: Any = None,
    extra: dict | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    if extra:
        error.update(extra)
    return JSONResponse(
        {
            "success": False,
            "data": None,
            "error": error,
            "request_id": str(request_id),
        },
        status_code=status_code,
        headers=headers,
    )
