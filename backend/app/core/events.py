"""In-memory SSE pub/sub bus for pipeline stage updates.

Each claim_id gets a list of asyncio.Queues. Publishers fan out events
to every active subscriber. Historical events live in the database and
are replayed on reconnect by the SSE route.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[int, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, claim_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers[claim_id].append(queue)
        return queue

    async def unsubscribe(self, claim_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(claim_id, [])
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers and claim_id in self._subscribers:
                del self._subscribers[claim_id]

    async def publish(self, claim_id: int, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(claim_id, []))
        for queue in subscribers:
            await queue.put(event)


event_bus = EventBus()
