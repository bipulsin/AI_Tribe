"""In-process rate limiting for external API tokens."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque


_lock = threading.Lock()
_minute_buckets: dict[int, deque[float]] = defaultdict(deque)
_day_buckets: dict[int, deque[float]] = defaultdict(deque)


def _limits() -> tuple[int, int]:
    per_min = int(os.environ.get("API_RATE_LIMIT_PER_MIN", "60"))
    per_day = int(os.environ.get("API_RATE_LIMIT_PER_DAY", "5000"))
    return max(1, per_min), max(1, per_day)


def check_rate_limit(user_id: int) -> tuple[bool, int | None]:
    """Return (allowed, retry_after_seconds)."""
    per_min, per_day = _limits()
    now = time.time()
    with _lock:
        minute = _minute_buckets[user_id]
        day = _day_buckets[user_id]
        while minute and now - minute[0] > 60:
            minute.popleft()
        while day and now - day[0] > 86400:
            day.popleft()
        if len(minute) >= per_min:
            retry = max(1, int(60 - (now - minute[0])) + 1)
            return False, retry
        if len(day) >= per_day:
            retry = max(1, int(86400 - (now - day[0])) + 1)
            return False, retry
        minute.append(now)
        day.append(now)
        return True, None
