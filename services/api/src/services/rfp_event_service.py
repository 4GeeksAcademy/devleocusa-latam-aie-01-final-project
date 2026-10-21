"""Multi-instance fan-out for authenticated RFP SSE subscribers.

Supabase/PostgreSQL remains the durable source of truth. Redis Pub/Sub carries
low-latency events between API processes; each process fans out to its local
SSE connections. Client recovery queries the durable ticket list because
Pub/Sub is intentionally not a persistent queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)
RFP_TICKET_CREATED = "rfp_ticket_created"
RFP_TICKET_CHANNEL = "trackflow:rfp:events:v1"
_QUEUE_CAPACITY = 100
_RECONNECT_DELAY_SECONDS = 2


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_CAPACITY)
    )
    loop: asyncio.AbstractEventLoop | None = None


class RFPEventBroker:
    """Redis-backed cross-process fan-out with a process-local fallback."""

    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._lock = threading.RLock()
        self._instance_id = str(uuid.uuid4())
        self._publisher: Redis | None = None
        self._listener: AsyncRedis | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._redis_connected = False
        self._redis_ever_connected = False
        self._connection_generation = 0
        self._connection_state_lock = threading.Lock()

    @property
    def should_reconnect_sse(self) -> bool:
        """Close existing SSE streams after an established Redis link is lost."""
        with self._connection_state_lock:
            return self._redis_ever_connected and not self._redis_connected

    @property
    def connection_generation(self) -> int:
        with self._connection_state_lock:
            return self._connection_generation

    async def start(self, redis_url: str | None = None) -> None:
        """Start the Redis subscription loop; retry if Redis is temporarily down."""
        if self._listener_task and not self._listener_task.done():
            return
        if self._listener is not None or self._publisher is not None:
            await self.stop()
        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._publisher = Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
        )
        self._listener = AsyncRedis.from_url(
            url, decode_responses=True, socket_connect_timeout=1, socket_timeout=None
        )
        self._stopping = False
        self._listener_task = asyncio.create_task(self._listen_forever())

    async def stop(self) -> None:
        """Stop Redis resources cleanly during API shutdown."""
        self._stopping = True
        task, self._listener_task = self._listener_task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        with self._connection_state_lock:
            self._redis_connected = False
            self._redis_ever_connected = False
        if self._listener:
            await self._listener.aclose()
            self._listener = None
        if self._publisher:
            self._publisher.close()
            self._publisher = None

    async def _listen_forever(self) -> None:
        while not self._stopping:
            pubsub = None
            try:
                assert self._listener is not None
                pubsub = self._listener.pubsub()
                await pubsub.subscribe(RFP_TICKET_CHANNEL)
                with self._connection_state_lock:
                    self._redis_connected = True
                    self._redis_ever_connected = True
                logger.info("RFP SSE Redis subscription active")
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(message["data"])
                        if envelope.get("origin") == self._instance_id:
                            continue
                        event = envelope.get("event")
                        if isinstance(event, dict):
                            self._publish_local(event)
                    except (TypeError, ValueError, KeyError):
                        logger.warning("Ignoring malformed RFP event from Redis")
            except asyncio.CancelledError:
                raise
            except Exception:
                # Any failed subscription attempt invalidates streams opened
                # while Redis was unavailable as well as established streams.
                with self._connection_state_lock:
                    self._connection_generation += 1
                    self._redis_connected = False
                if not self._stopping:
                    logger.exception("RFP Redis subscription failed; retrying")
                    await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        logger.debug("Error closing RFP Redis Pub/Sub connection", exc_info=True)

    async def subscribe(self) -> Subscriber:
        subscriber = Subscriber(loop=asyncio.get_running_loop())
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    async def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _publish_local(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            loop = subscriber.loop
            if loop is None or loop.is_closed():
                continue

            def enqueue(target: Subscriber = subscriber) -> None:
                with self._lock:
                    if target not in self._subscribers:
                        return
                if target.queue.full():
                    try:
                        target.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    target.queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("RFP SSE subscriber queue remained full")

            try:
                loop.call_soon_threadsafe(enqueue)
            except RuntimeError:
                logger.debug("RFP SSE subscriber loop closed during publish")

    def publish(self, event: dict[str, Any]) -> None:
        """Fan out locally immediately and publish to other API processes."""
        self._publish_local(event)
        publisher = self._publisher
        if publisher is None:
            return
        envelope = json.dumps(
            {"origin": self._instance_id, "event": event},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            publisher.publish(RFP_TICKET_CHANNEL, envelope)
        except Exception:
            # Local SSE still works; clients recover from Supabase on reconnect.
            logger.exception("Could not distribute RFP event through Redis")


rfp_event_broker = RFPEventBroker()
