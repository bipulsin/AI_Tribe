"""Public partner API under /api/v1/external/."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api_marketplace.claims import (
    assessment_payload,
    claim_detail_payload,
    estimate_payload,
    get_claim_by_exact_ref,
    resolve_claim_ref,
    submit_claim_external,
    submit_images_external,
    verify_upload_token,
)
from app.api_marketplace.deps import finish_log, require_external_auth
from app.api_marketplace.envelope import fail, ok
from app.core.database import get_db
from app.services.pipeline_orchestrator import ensure_pipeline_started

router = APIRouter(prefix="/api/v1/external", tags=["api-marketplace-external"])


class SubmitClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surveyor_name: str
    claimant_name: str
    garage_name: str
    garage_location: Optional[str] = None
    date_of_accident: str
    policy_number: Optional[str] = None
    vehicle_reg_number: Optional[str] = None
    contact_phone: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=4000)


@router.post("/claims/submit")
async def external_submit_claim(
    payload: SubmitClaimBody,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = await require_external_auth(request, db, api_name="submit_claim")
    if not isinstance(auth, tuple):
        return auth
    user, _prefix, request_id = auth
    try:
        data = submit_claim_external(
            db,
            user_id=user.id,
            surveyor_name=payload.surveyor_name,
            claimant_name=payload.claimant_name,
            garage_name=payload.garage_name,
            date_of_accident=payload.date_of_accident,
            garage_location=payload.garage_location,
        )
    except ValueError as exc:
        args = exc.args[0] if exc.args else None
        if isinstance(args, tuple) and args[0] == "VALIDATION_ERROR":
            resp = fail(
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                request_id=request_id,
                status_code=422,
                details=args[1],
            )
            finish_log(db, request, api_name="submit_claim", claim_no=None, status_code=422, error_code="VALIDATION_ERROR")
            return resp
        if isinstance(args, tuple) and args[0] == "DUPLICATE_CLAIM":
            resp = fail(
                code="DUPLICATE_CLAIM",
                message=str(args[1]),
                request_id=request_id,
                status_code=409,
            )
            finish_log(db, request, api_name="submit_claim", claim_no=None, status_code=409, error_code="DUPLICATE_CLAIM")
            return resp
        resp = fail(
            code="INTERNAL_ERROR",
            message=str(exc),
            request_id=request_id,
            status_code=500,
        )
        finish_log(db, request, api_name="submit_claim", claim_no=None, status_code=500, error_code="INTERNAL_ERROR")
        return resp
    except Exception:
        resp = fail(
            code="INTERNAL_ERROR",
            message="Could not create claim.",
            request_id=request_id,
            status_code=500,
        )
        finish_log(db, request, api_name="submit_claim", claim_no=None, status_code=500, error_code="INTERNAL_ERROR")
        return resp

    finish_log(
        db,
        request,
        api_name="submit_claim",
        claim_no=data.get("claim_no"),
        status_code=200,
    )
    return ok(data, request_id=request_id)


@router.post("/claims/{claim_no}/images")
async def external_submit_images(
    claim_no: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    images: list[UploadFile] | None = File(None),
    video: UploadFile | None = File(None),
    upload_token: str | None = Form(None),
):
    # Prefer upload_token auth for intake; else require API token + subscription.
    request_id = getattr(request.state, "api_request_id", None)
    user = None
    used_upload_token = False

    if upload_token:
        from app.api_marketplace.envelope import new_request_id

        request_id = request_id or new_request_id()
        request.state.api_request_id = request_id
        claim = get_claim_by_exact_ref(db, claim_no)
        if not claim:
            resp = fail(
                code="CLAIM_NOT_FOUND",
                message="Claim not found.",
                request_id=request_id,
                status_code=404,
            )
            finish_log(db, request, api_name="submit_images", claim_no=claim_no, status_code=404, error_code="CLAIM_NOT_FOUND")
            return resp
        try:
            verify_upload_token(upload_token, claim_no=claim.claim_reference, user_id=claim.created_by)
            used_upload_token = True
            from app.models import User

            user = db.get(User, claim.created_by)
            request.state.api_user = user
        except ValueError as exc:
            code = str(exc.args[0]) if exc.args else "UPLOAD_TOKEN_INVALID"
            resp = fail(
                code=code,
                message="Upload token is invalid or expired.",
                request_id=request_id,
                status_code=401,
            )
            finish_log(db, request, api_name="submit_images", claim_no=claim_no, status_code=401, error_code=code)
            return resp
    else:
        auth = await require_external_auth(request, db, api_name="submit_images")
        if not isinstance(auth, tuple):
            return auth
        user, _prefix, request_id = auth
        claim = get_claim_by_exact_ref(db, claim_no, user_id=user.id)
        if not claim:
            resp = fail(
                code="CLAIM_NOT_FOUND",
                message="Claim not found.",
                request_id=request_id,
                status_code=404,
            )
            finish_log(db, request, api_name="submit_images", claim_no=claim_no, status_code=404, error_code="CLAIM_NOT_FOUND")
            return resp

    if not user:
        resp = fail(code="TOKEN_INVALID", message="Unauthorized.", request_id=request_id, status_code=401)
        return resp

    # When using upload_token, still require subscription if they also sent bearer? Spec: upload_token OR api token.
    if not used_upload_token:
        pass
    else:
        # Upload-token path should not require subscription gate beyond claim ownership.
        pass

    files = [f for f in (images or []) if f and f.filename]
    if not files and not (video and video.filename):
        resp = fail(
            code="VALIDATION_ERROR",
            message="No files received.",
            request_id=request_id,
            status_code=422,
        )
        finish_log(db, request, api_name="submit_images", claim_no=claim_no, status_code=422, error_code="VALIDATION_ERROR")
        return resp

    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.models import Claim

    claim = db.scalar(
        select(Claim).options(selectinload(Claim.images)).where(Claim.id == claim.id)
    )

    data = await submit_images_external(
        db, claim=claim, images=files, video=video, start_pipeline=True
    )
    if data.get("accepted"):
        background_tasks.add_task(ensure_pipeline_started, claim.id)

    finish_log(db, request, api_name="submit_images", claim_no=claim.claim_reference, status_code=200)
    return ok(data, request_id=request_id)


@router.get("/claims/{claim_ref}/assessment")
async def external_assessment(
    claim_ref: str,
    request: Request,
    db: Session = Depends(get_db),
):
    # More specific routes must be registered before generic claim_ref — FastAPI matches in order.
    auth = await require_external_auth(request, db, api_name="assessment_detail")
    if not isinstance(auth, tuple):
        return auth
    user, _prefix, request_id = auth
    claim, candidates = resolve_claim_ref(db, claim_ref, user_id=user.id)
    if candidates:
        resp = fail(
            code="AMBIGUOUS_CLAIM_REF",
            message="Multiple claims match that reference.",
            request_id=request_id,
            status_code=409,
            details=candidates,
        )
        finish_log(db, request, api_name="assessment_detail", claim_no=claim_ref, status_code=409, error_code="AMBIGUOUS_CLAIM_REF")
        return resp
    if not claim:
        resp = fail(
            code="CLAIM_NOT_FOUND",
            message="Claim not found.",
            request_id=request_id,
            status_code=404,
        )
        finish_log(db, request, api_name="assessment_detail", claim_no=claim_ref, status_code=404, error_code="CLAIM_NOT_FOUND")
        return resp
    data = assessment_payload(db, claim)
    finish_log(db, request, api_name="assessment_detail", claim_no=claim.claim_reference, status_code=200)
    return ok(data, request_id=request_id)


@router.get("/claims/{claim_ref}/estimate")
async def external_estimate(
    claim_ref: str,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = await require_external_auth(request, db, api_name="estimation_detail")
    if not isinstance(auth, tuple):
        return auth
    user, _prefix, request_id = auth
    claim, candidates = resolve_claim_ref(db, claim_ref, user_id=user.id)
    if candidates:
        resp = fail(
            code="AMBIGUOUS_CLAIM_REF",
            message="Multiple claims match that reference.",
            request_id=request_id,
            status_code=409,
            details=candidates,
        )
        finish_log(db, request, api_name="estimation_detail", claim_no=claim_ref, status_code=409, error_code="AMBIGUOUS_CLAIM_REF")
        return resp
    if not claim:
        resp = fail(
            code="CLAIM_NOT_FOUND",
            message="Claim not found.",
            request_id=request_id,
            status_code=404,
        )
        finish_log(db, request, api_name="estimation_detail", claim_no=claim_ref, status_code=404, error_code="CLAIM_NOT_FOUND")
        return resp
    data = estimate_payload(db, claim)
    finish_log(db, request, api_name="estimation_detail", claim_no=claim.claim_reference, status_code=200)
    return ok(data, request_id=request_id)


@router.get("/claims/{claim_ref}")
async def external_claim_detail(
    claim_ref: str,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = await require_external_auth(request, db, api_name="claim_detail")
    if not isinstance(auth, tuple):
        return auth
    user, _prefix, request_id = auth
    claim, candidates = resolve_claim_ref(db, claim_ref, user_id=user.id)
    if candidates:
        resp = fail(
            code="AMBIGUOUS_CLAIM_REF",
            message="Multiple claims match that reference.",
            request_id=request_id,
            status_code=409,
            details=candidates,
        )
        finish_log(db, request, api_name="claim_detail", claim_no=claim_ref, status_code=409, error_code="AMBIGUOUS_CLAIM_REF")
        return resp
    if not claim:
        resp = fail(
            code="CLAIM_NOT_FOUND",
            message="Claim not found.",
            request_id=request_id,
            status_code=404,
        )
        finish_log(db, request, api_name="claim_detail", claim_no=claim_ref, status_code=404, error_code="CLAIM_NOT_FOUND")
        return resp
    data = claim_detail_payload(db, claim)
    finish_log(db, request, api_name="claim_detail", claim_no=claim.claim_reference, status_code=200)
    return ok(data, request_id=request_id)


@router.get("/police-details/{claim_no}")
async def external_police_details(
    claim_no: str,
    request: Request,
    db: Session = Depends(get_db),
):
    from app.api_marketplace.envelope import new_request_id

    request_id = new_request_id()
    resp = fail(
        code="NOT_AVAILABLE",
        message="Police details API is not yet available.",
        request_id=request_id,
        status_code=501,
    )
    finish_log(
        db,
        request,
        api_name="police_details",
        claim_no=claim_no,
        status_code=501,
        error_code="NOT_AVAILABLE",
    )
    return resp
