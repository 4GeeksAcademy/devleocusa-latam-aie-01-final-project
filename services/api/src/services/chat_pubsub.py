"""In-process pub/sub channels, one per chat session."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class ChatPubSub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers[session_id].add(queue)
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                self._subscribers.pop(session_id, None)

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(session_id, ()))
        for queue in subscribers:
            queue.put_nowait(event)


chat_pubsub = ChatPubSub()
