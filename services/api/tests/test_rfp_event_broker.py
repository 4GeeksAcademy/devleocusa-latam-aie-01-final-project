"""Cross-instance fan-out tests for the Redis-backed RFP event broker."""

from __future__ import annotations

import asyncio
import json


def test_redis_pubsub_delivers_to_other_api_instance(monkeypatch):
    from src.services import rfp_event_service as event_service

    class FakeHub:
        def __init__(self):
            self.queues: list[asyncio.Queue] = []

        def subscribe(self) -> asyncio.Queue:
            queue: asyncio.Queue = asyncio.Queue()
            self.queues.append(queue)
            return queue

        def publish(self, channel: str, data: str) -> None:
            for queue in tuple(self.queues):
                queue.put_nowait({"type": "message", "channel": channel, "data": data})

    hub = FakeHub()

    class FakePubSub:
        def __init__(self):
            self.queue = hub.subscribe()

        async def subscribe(self, _channel: str) -> None:
            return None

        async def listen(self):
            while True:
                yield await self.queue.get()

        async def aclose(self) -> None:
            return None

    class FakeAsyncRedis:
        def pubsub(self):
            return FakePubSub()

        async def aclose(self) -> None:
            return None

    class FakeRedis:
        def publish(self, channel: str, data: str) -> None:
            hub.publish(channel, data)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        event_service.Redis,
        "from_url",
        staticmethod(lambda *_args, **_kwargs: FakeRedis()),
    )
    monkeypatch.setattr(
        event_service.AsyncRedis,
        "from_url",
        staticmethod(lambda *_args, **_kwargs: FakeAsyncRedis()),
    )

    async def exercise():
        first = event_service.RFPEventBroker()
        second = event_service.RFPEventBroker()
        first_subscriber = await first.subscribe()
        second_subscriber = await second.subscribe()
        await first.start("redis://test")
        await second.start("redis://test")
        try:
            # Let both listeners subscribe before publishing.
            for _ in range(10):
                if len(hub.queues) == 2:
                    break
                await asyncio.sleep(0)
            assert len(hub.queues) == 2

            event = {
                "event": "rfp_ticket_created",
                "data": {"ticket_id": "ticket-cross-instance", "status": "analyzing"},
            }
            first.publish(event)
            first_delivery, second_delivery = await asyncio.gather(
                asyncio.wait_for(first_subscriber.queue.get(), timeout=1),
                asyncio.wait_for(second_subscriber.queue.get(), timeout=1),
            )
            assert first_delivery == event
            assert second_delivery == event
        finally:
            await first.stop()
            await second.stop()

    asyncio.run(exercise())


def test_event_envelope_is_json_serializable():
    event = {"event": "rfp_ticket_created", "data": {"ticket_id": "id-1"}}
    envelope = {"origin": "api-instance", "event": event}
    assert json.loads(json.dumps(envelope))["event"] == event