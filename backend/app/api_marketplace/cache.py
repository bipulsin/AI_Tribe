"""Short TTL response cache for external GET polling."""

from __future__ import annotations

import threading
import time
from typing import Any


_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}
DEFAULT_TTL = 15.0


def cache_get(key: str) -> Any | None:
    now = time.time()
    with _lock:
        item = _store.get(key)
        if not item:
            return None
        expires, value = item
        if expires < now:
            _store.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, *, ttl: float = DEFAULT_TTL) -> None:
    with _lock:
        _store[key] = (time.time() + ttl, value)


def cache_invalidate_prefix(prefix: str) -> None:
    with _lock:
        dead = [k for k in _store if k.startswith(prefix)]
        for k in dead:
            _store.pop(k, None)
