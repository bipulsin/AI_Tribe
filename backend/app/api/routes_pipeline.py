"""Pipeline SSE stream and manual-review actions."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db
from app.core.events import event_bus
from app.models import Claim, PipelineEvent
from app.models.enums import ClaimStatus
from app.services.pipeline_orchestrator import event_to_dict

router = APIRouter(tags=["pipeline"])


def _claim_for_user(db: Session, claim_id: int, user_id: int) -> Claim | None:
    claim = db.get(Claim, claim_id)
    if not claim or claim.created_by != user_id:
        return None
    return claim


@router.get("/api/pipeline/{claim_id}/stream")
async def pipeline_stream(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    claim = _claim_for_user(db, claim_id, user_id)
    if not claim:
        return JSONResponse({"detail": "Claim not found"}, status_code=404)

    history = db.scalars(
        select(PipelineEvent)
        .where(PipelineEvent.claim_id == claim_id)
        .order_by(PipelineEvent.id.asc())
    ).all()
    historical = [event_to_dict(event) for event in history]
    claim_status = claim.status.value if claim.status else None
    already_complete = claim_status in {
        ClaimStatus.estimate_ready.value,
        ClaimStatus.authenticity_failed.value,
        ClaimStatus.review_required.value,
        ClaimStatus.closed.value,
    }

    async def event_generator():
        # Replay audit trail so reconnects catch up.
        for payload in historical:
            yield {"event": "stage", "data": json.dumps(payload)}

        if already_complete:
            last_ts = historical[-1].get("created_at") if historical else None
            terminal: dict[str, Any] = {
                "claim_id": claim_id,
                "pipeline_complete": True,
                "created_at": last_ts,
                "halted": claim_status
                in {
                    ClaimStatus.authenticity_failed.value,
                    ClaimStatus.review_required.value,
                },
                "claim_status": claim_status,
            }
            if claim_status == ClaimStatus.estimate_ready.value:
                terminal["redirect"] = f"/claims/{claim_id}/estimate"
            elif claim_status == ClaimStatus.authenticity_failed.value:
                terminal["halt_message"] = (
                    "Authenticity or forensic checks did not pass. "
                    "This claim is paused for manual review."
                )
            yield {"event": "stage", "data": json.dumps(terminal)}
            return

        queue = await event_bus.subscribe(claim_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue

                yield {"event": "stage", "data": json.dumps(payload)}
                if payload.get("pipeline_complete"):
                    break
        finally:
            await event_bus.unsubscribe(claim_id, queue)

    return EventSourceResponse(event_generator())


@router.post("/api/pipeline/{claim_id}/request-review")
async def request_manual_review(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    claim = _claim_for_user(db, claim_id, user_id)
    if not claim:
        return JSONResponse({"detail": "Claim not found"}, status_code=404)

    claim.status = ClaimStatus.review_required
    db.commit()
    return JSONResponse(
        {
            "claim_id": claim.id,
            "status": claim.status.value,
            "detail": "Claim sent for manual review.",
        }
    )
