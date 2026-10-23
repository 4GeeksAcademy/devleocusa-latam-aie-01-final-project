from __future__ import annotations

import asyncio

from src.services.chat_pubsub import ChatPubSub


def test_pubsub_delivers_same_event_to_each_subscriber() -> None:
    async def scenario() -> None:
        pubsub = ChatPubSub()
        first = await pubsub.subscribe("chat_case")
        second = await pubsub.subscribe("chat_case")
        event = {"event": "token_chunk", "data": {"session_id": "chat_case", "token": "hola"}}
        await pubsub.publish("chat_case", event)
        assert await first.get() == event
        assert await second.get() == event
        await pubsub.unsubscribe("chat_case", first)
        await pubsub.unsubscribe("chat_case", second)

    asyncio.run(scenario())
