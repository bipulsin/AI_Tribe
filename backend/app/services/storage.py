"""Object storage interface.

Local filesystem under data/uploads/ for the POC. Swap the implementation
for S3-compatible Oracle Object Storage later without touching callers.
"""

from __future__ import annotations

import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings


class StorageBackend(ABC):
    @abstractmethod
    def save(self, source_path: Path, claim_id: int, filename: str) -> str:
        """Persist a file and return the storage-relative path."""

    @abstractmethod
    def resolve(self, relative_path: str) -> Path:
        """Resolve a storage-relative path to an absolute filesystem path."""

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        """Remove a stored file if it exists."""


class LocalFilesystemStorage(StorageBackend):
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = root or settings.upload_path
        self.root.mkdir(parents=True, exist_ok=True)

    def _claim_dir(self, claim_id: int) -> Path:
        path = self.root / str(claim_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, source_path: Path, claim_id: int, filename: str) -> str:
        safe_name = Path(filename).name
        unique = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        dest = self._claim_dir(claim_id) / unique
        shutil.copy2(source_path, dest)
        return f"{claim_id}/{unique}"

    def save_bytes(self, data: bytes, claim_id: int, filename: str) -> str:
        safe_name = Path(filename).name
        unique = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        dest = self._claim_dir(claim_id) / unique
        dest.write_bytes(data)
        return f"{claim_id}/{unique}"

    def resolve(self, relative_path: str) -> Path:
        return self.root / relative_path

    def delete(self, relative_path: str) -> None:
        path = self.resolve(relative_path)
        if path.exists():
            path.unlink()


def get_storage() -> StorageBackend:
    return LocalFilesystemStorage()
