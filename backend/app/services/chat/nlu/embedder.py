"""Lazy MiniLM embedder for chat intent prototypes.

Weights load from CHAT_NLU_ROOT (default /mnt/ml-scratch/chat_nlu), never from
root disk caches when a scratch path is configured.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("ai_tribe.chat_nlu")

_lock = threading.Lock()
_model: Any = None
_model_path: Path | None = None
_load_error: str | None = None


def _resolve_model_dir(root: Path) -> Path | None:
    candidates = [
        root / "models" / "all-MiniLM-L6-v2",
        root / "all-MiniLM-L6-v2",
    ]
    for path in candidates:
        if (path / "config.json").is_file():
            return path
    return None


def reset_embedder() -> None:
    global _model, _model_path, _load_error
    with _lock:
        _model = None
        _model_path = None
        _load_error = None


def get_embedder(root: Path):
    """Return a SentenceTransformer-like object, or None if unavailable."""
    global _model, _model_path, _load_error
    with _lock:
        if _model is not None:
            return _model
        if _load_error is not None:
            return None

        model_dir = _resolve_model_dir(root)
        if model_dir is None:
            _load_error = f"MiniLM not found under {root}"
            logger.warning("Chat NLU: %s — using rule fallback", _load_error)
            return None

        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            _model = SentenceTransformer(str(model_dir), device="cpu")
            _model_path = model_dir
            logger.info("Chat NLU: loaded MiniLM from %s", model_dir)
            return _model
        except Exception as exc:
            _load_error = str(exc)
            logger.warning("Chat NLU: failed to load MiniLM (%s) — rule fallback", exc)
            return None


def embed_texts(root: Path, texts: list[str]) -> np.ndarray | None:
    model = get_embedder(root)
    if model is None or not texts:
        return None
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return np.asarray(vectors, dtype=np.float32)
