import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models import User

logger = logging.getLogger("ai_tribe")
settings = get_settings()


def _warn_default_credentials() -> None:
    """Print a clear console warning if the default admin/admin credential is active."""
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin and verify_password("admin", admin.password_hash):
            logger.warning(
                "DEFAULT CREDENTIAL ACTIVE: username 'admin' / password 'admin'. "
                "Change this before any use beyond local lab demos."
            )
            print(
                "\n"
                "=" * 72 + "\n"
                "  WARNING: Default credential admin/admin is still active.\n"
                "  Change this password before anything resembling production use.\n"
                + "=" * 72
                + "\n"
            )
    except Exception as exc:
        # Tables may not exist yet on first boot before migrations.
        logger.debug("Could not check default credentials: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import os

    from app.core.config import REPO_ROOT

    logger.info("ML_MODE=%s", settings.ml_mode)
    print(f"\n  ML_MODE={settings.ml_mode} "
          f"({'pretrained models' if settings.ml_live else 'deterministic stubs, no torch'})\n")

    # Only configure HF/torch caches when live inference is enabled.
    if settings.ml_live:
        weights_root = REPO_ROOT / "backend" / "app" / "ml_weights"
        os.environ.setdefault("HF_HOME", str(weights_root / "huggingface"))
        os.environ.setdefault("TORCH_HOME", str(weights_root / "torch"))
        (weights_root / "huggingface").mkdir(parents=True, exist_ok=True)
        (weights_root / "torch").mkdir(parents=True, exist_ok=True)

    settings.upload_path.mkdir(parents=True, exist_ok=True)
    try:
        from app.db.seed import seed_admin, seed_parts_catalog

        db = SessionLocal()
        try:
            seed_admin(db)
            seed_parts_catalog(db)
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Could not run seed on boot: %s", exc)

    _warn_default_credentials()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

templates = Jinja2Templates(directory=str(settings.templates_dir))
app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

# Uploaded media served for thumbnails / estimate images
upload_dir = settings.upload_path
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")


# Public paths that do not require a session
PUBLIC_PATHS = {
    "/login",
    "/auth/login",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@app.middleware("http")
async def require_session(request: Request, call_next):
    path = request.url.path
    if (
        path in PUBLIC_PATHS
        or path.startswith("/static/")
        or path.startswith("/uploads/")
    ):
        return await call_next(request)

    user_id = request.session.get("user_id")
    if not user_id:
        accept = request.headers.get("accept", "")
        wants_json = path.startswith("/api/") or "application/json" in accept
        if wants_json:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse(url="/login", status_code=303)

    return await call_next(request)


# SessionMiddleware must be added last so it is the outermost middleware
# (Starlette runs last-added middleware first on the request path).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=False,
)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/")
async def root():
    return RedirectResponse(url="/claims/new", status_code=303)


# Route modules are registered as milestones land.
# Milestone 1: health + skeleton only.
# Milestone 2+: auth, claims, pipeline, estimate.
try:
    from app.api import routes_auth, routes_claims, routes_estimate, routes_pipeline

    app.include_router(routes_auth.router)
    app.include_router(routes_claims.router)
    app.include_router(routes_pipeline.router)
    app.include_router(routes_estimate.router)
except ImportError:
    # Partial scaffold during early milestones — routes land incrementally.
    pass
