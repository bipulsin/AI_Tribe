from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: backend/app/core/config.py -> ../../../
REPO_ROOT = Path(__file__).resolve().parents[3]

MlMode = Literal["stub", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Tribe: Motor Damage Assessment"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me-to-a-long-random-string"

    # "stub" (default): deterministic fixtures, no torch/transformers imports.
    # "live": load pretrained HF / torchvision models (requires requirements-ml.txt).
    ml_mode: MlMode = "stub"

    session_cookie_name: str = "ai_tribe_session"
    session_max_age: int = 86400

    database_url: str = "postgresql+psycopg://ai_tribe:ai_tribe@localhost:5432/ai_tribe"

    upload_dir: str = str(REPO_ROOT / "data" / "uploads")
    max_images_per_claim: int = 10
    max_upload_mb: int = 25

    host: str = "0.0.0.0"
    port: int = 8000

    @field_validator("ml_mode", mode="before")
    @classmethod
    def _normalize_ml_mode(cls, value: object) -> str:
        if value is None or value == "":
            return "stub"
        normalized = str(value).strip().lower()
        if normalized not in {"stub", "live"}:
            raise ValueError('ML_MODE must be "stub" or "live"')
        return normalized

    @property
    def ml_live(self) -> bool:
        return self.ml_mode == "live"

    @property
    def frontend_dir(self) -> Path:
        return REPO_ROOT / "frontend"

    @property
    def templates_dir(self) -> Path:
        return self.frontend_dir / "templates"

    @property
    def static_dir(self) -> Path:
        return self.frontend_dir / "static"

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
