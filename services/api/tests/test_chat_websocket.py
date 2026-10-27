from __future__ import annotations

import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.routes import chat_router as chat_module
from src.services.auth_service import create_access_token


def test_websocket_auth_and_snapshot(manager_user, monkeypatch) -> None:
    user, _ = manager_user
    app = FastAPI()
    app.include_router(chat_module.chat_router)

    class Graph:
        async def astream(self, *_args, **_kwargs):
            yield {"answer": "respuesta"}

    app.state.agent_graph = Graph()
    monkeypatch.setattr(chat_module.store, "get_session", lambda _session_id: None)
    created = {}

    def create_session(session_id: str, user_id: str):
        created.update(session_id=session_id, user_id=user_id)
        return {"session_id": session_id, "agent_id": "first_line_cx", "user_id": user_id,
                "client_id": user_id, "status": "active", "created_at": "2026-10-22T00:00:00+00:00"}

    monkeypatch.setattr(chat_module.store, "create_or_get_session", create_session)
    partial = {"message_id": "assistant-active", "role": "assistant", "text": "parcial recuperado",
               "status": "streaming", "sequence": 3}
    monkeypatch.setattr(chat_module.store, "list_messages", lambda _session_id: [partial])
    token = create_access_token(user.id)

    with TestClient(app) as client:
        with client.websocket_connect(f"/chat/ws/test_session?token={token}") as socket:
            snapshot = socket.receive_json()
            assert snapshot["event"] == "session_snapshot"
            assert snapshot["data"]["session"]["agent_id"] == "first_line_cx"
            assert snapshot["data"]["messages"] == [partial]
            resumed = socket.receive_json()
            assert resumed["event"] == "token_chunk"
            assert resumed["data"] == {
                "session_id": "test_session", "message_id": "assistant-active",
                "token": "parcial recuperado", "sequence": 3, "replace": True,
            }

    assert created == {"session_id": "test_session", "user_id": str(user.id)}


def test_websocket_rejects_missing_auth() -> None:
    app = FastAPI()
    app.include_router(chat_module.chat_router)
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/chat/ws/no_auth"):
                raise AssertionError("unauthenticated websocket was accepted")
        except Exception as error:
            assert "1008" in str(error) or "WebSocketDisconnect" in type(error).__name__


def test_websocket_rejects_customer_role(test_user) -> None:
    user, _ = test_user
    app = FastAPI()
    app.include_router(chat_module.chat_router)
    token = create_access_token(user.id)

    with TestClient(app) as client:
        try:
            with client.websocket_connect(f"/chat/ws/customer_session?token={token}"):
                raise AssertionError("customer websocket was accepted")
        except Exception as error:
            assert "1008" in str(error) or "WebSocketDisconnect" in type(error).__name__


def test_interrupt_cancels_producer_and_persists_partial(monkeypatch) -> None:
    events: list[dict] = []
    persisted: dict[str, dict] = {}

    class FakeStore:
        @staticmethod
        def add_message(session_id, role, text, status="completed"):
            record = {"message_id": f"{role}-{len(persisted)}", "session_id": session_id,
                      "role": role, "text": text, "status": status}
            persisted[record["message_id"]] = record
            return record

        @staticmethod
        def update_message(message_id, *, text, status, sequence=None):
            persisted[message_id].update(text=text, status=status, sequence=sequence)
            return persisted[message_id]

        @staticmethod
        def set_session_status(*_args):
            return None

    class FakePubSub:
        @staticmethod
        async def publish(_session_id, event):
            events.append(event)

    class Graph:
        pass

    async def fake_invoke(_graph, _question, _session_id, _user_id):
        callback = chat_module.stream_callback_context.get()
        cancel_signal = chat_module.stream_cancel_context.get()
        callback("parcial")
        while not cancel_signal.is_set():
            await asyncio.sleep(0)
        return {"answer": "no se debe completar"}

    async def scenario() -> None:
        monkeypatch.setattr(chat_module, "store", FakeStore)
        monkeypatch.setattr(chat_module, "chat_pubsub", FakePubSub)
        monkeypatch.setattr(chat_module, "invoke_agent", fake_invoke)
        task = asyncio.create_task(chat_module._produce_turn(Graph(), "interrupt_case", "user", "rastreo"))
        while not any(event["event"] == "token_chunk" for event in events):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert any(event["event"] == "generation_interrupted" for event in events)
    assert not any(event["event"] == "generation_completed" for event in events)
    assistant = next(message for message in persisted.values() if message["role"] == "assistant")
    assert assistant["text"] == "parcial"
    assert assistant["status"] == "interrupted"


def test_interrupt_waits_for_generation_shutdown_before_starting_new_turn(monkeypatch) -> None:
    events: list[dict] = []
    persisted: dict[str, dict] = {}
    order: list[str] = []

    class FakeStore:
        @staticmethod
        def add_message(session_id, role, text, status="completed"):
            record = {"message_id": f"{role}-{len(persisted)}", "session_id": session_id,
                      "role": role, "text": text, "status": status}
            persisted[record["message_id"]] = record
            return record

        @staticmethod
        def update_message(message_id, *, text, status, sequence=None):
            persisted[message_id].update(text=text, status=status, sequence=sequence)
            return persisted[message_id]

        @staticmethod
        def set_session_status(*_args):
            return None

    class FakePubSub:
        @staticmethod
        async def publish(_session_id, event):
            events.append(event)
            if event["event"] == "generation_interrupted":
                order.append("interrupted")

    class Graph:
        pass

    async def fake_invoke(_graph, question, _session_id, _user_id):
        if question == "original":
            callback = chat_module.stream_callback_context.get()
            cancel_signal = chat_module.stream_cancel_context.get()
            callback("parcial")
            while not cancel_signal.is_set():
                await asyncio.sleep(0)
            order.append("original_stopped")
            return {"answer": ""}
        order.append("redirect_started")
        return {"answer": f"nuevo:{question}"}

    async def scenario() -> None:
        monkeypatch.setattr(chat_module, "store", FakeStore)
        monkeypatch.setattr(chat_module, "chat_pubsub", FakePubSub)
        monkeypatch.setattr(chat_module, "invoke_agent", fake_invoke)
        graph = Graph()
        original = asyncio.create_task(chat_module._start_turn(graph, "ordered", "user", "original"))
        while not any(event["event"] == "token_chunk" for event in events):
            await asyncio.sleep(0)
        await chat_module._start_turn(graph, "ordered", "user", "devolución")
        await original

    asyncio.run(scenario())
    assert order.index("original_stopped") < order.index("interrupted")
    assert order.index("interrupted") < order.index("redirect_started")
    assistants = [message for message in persisted.values() if message["role"] == "assistant"]
    assert assistants[0]["text"] == "parcial" and assistants[0]["status"] == "interrupted"
    assert assistants[1]["text"] == "nuevo:devolución" and assistants[1]["status"] == "completed"


def test_reconnect_snapshot_restores_streaming_partial_and_watermark() -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    partial = {"message_id": "assistant-1", "role": "assistant", "text": "respuesta parcial",
               "status": "streaming", "sequence": 4}
    chat_module._resume_stream_delivery("reconnect", partial, queue)
    event = queue.get_nowait()
    assert event["event"] == "_resume_stream"
    assert event["message"]["status"] == "streaming"
    assert event["message"]["sequence"] == 4


def test_streaming_generation_extracts_answer_and_closes_provider(monkeypatch) -> None:
    from src.agent import memory_generation

    captured = {"closed": False, "stream": False}

    class FakeMemoryGeneration(BaseModel):
        answer: str
        proposal: dict | None = None

    class FakeResponse:
        choices = []

        def __iter__(self):
            for part in ['{"answer":"Hola', ' mundo\\nTrackFlow","proposal":null}']:
                yield type("Event", (), {"choices": [type("Choice", (), {
                    "delta": type("Delta", (), {"content": part})()
                })()]})()

        @staticmethod
        def close():
            captured["closed"] = True

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            captured["stream"] = kwargs["stream"]
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    tokens: list[str] = []
    monkeypatch.setattr(memory_generation, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(memory_generation, "MemoryGeneration", FakeMemoryGeneration)
    callback = memory_generation.stream_callback_context.set(tokens.append)
    explicit = memory_generation.stream_context_explicit.set(True)
    try:
        result = memory_generation.generate_answer_and_proposal("pregunta", [])
    finally:
        memory_generation.stream_context_explicit.reset(explicit)
        memory_generation.stream_callback_context.reset(callback)

    assert captured == {"closed": True, "stream": True}
    assert result.answer == "Hola mundo\nTrackFlow"
    assert "".join(tokens) == result.answer
