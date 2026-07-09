"""Conversational chat routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.database import get_db
from app.services.chat.handler import append_uploads, handle_message
from app.services.chat.lookup import format_claim_summary
from app.services.claim_service import IMAGE_CONTENT_TYPES

router = APIRouter(tags=["chat"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


class ChatMessagePayload(BaseModel):
    text: str = Field(default="", max_length=4000)


def _reply_json(reply) -> dict:
    return {
        "role": reply.role,
        "text": reply.text,
        "widgets": reply.widgets,
    }


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", "") or "",
            "max_images": settings.max_images_per_claim,
            "max_upload_mb": settings.max_upload_mb,
        },
    )


@router.post("/api/chat/message")
async def chat_message(
    request: Request,
    payload: ChatMessagePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    reply = await handle_message(
        db,
        user_id,
        payload.text,
        full_name=request.session.get("full_name"),
        username=request.session.get("username"),
        background_tasks=background_tasks,
    )
    return JSONResponse(_reply_json(reply))


@router.post("/api/chat/upload")
async def chat_upload(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    form = await request.form()

    images_raw = [
        item
        for item in form.getlist("images")
        if isinstance(item, UploadFile) and item.filename
    ]
    video_field = form.get("video")
    video_raw = (
        video_field
        if isinstance(video_field, UploadFile) and video_field.filename
        else None
    )

    image_payloads: list[tuple[str, bytes, str]] = []
    for upload in images_raw:
        content_type = (upload.content_type or "").lower()
        if content_type not in IMAGE_CONTENT_TYPES and not (
            upload.filename or ""
        ).lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            continue
        data = await upload.read()
        if data:
            image_payloads.append(
                (upload.filename or "photo.jpg", data, content_type or "image/jpeg")
            )

    video_payload = None
    if video_raw:
        content_type = (video_raw.content_type or "").lower()
        data = await video_raw.read()
        if data:
            video_payload = (
                video_raw.filename or "video.mp4",
                data,
                content_type or "video/mp4",
            )

    if not image_payloads and not video_payload:
        return JSONResponse({"detail": "No supported files received."}, status_code=400)

    reply = append_uploads(
        db,
        user_id,
        images=image_payloads,
        video=video_payload,
    )
    return JSONResponse(_reply_json(reply))


@router.get("/api/chat/claims/{claim_id}/summary")
async def chat_claim_summary(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    summary = format_claim_summary(db, claim_id, user_id)
    if not summary:
        return JSONResponse({"detail": "Claim not found."}, status_code=404)
    return JSONResponse({"text": summary})
