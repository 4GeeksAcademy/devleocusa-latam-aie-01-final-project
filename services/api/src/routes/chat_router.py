"""Bidirectional WebSocket chat for the existing First-line CX agent."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from src.agent.memory_generation import (
    stream_callback_context,
    stream_cancel_context,
    stream_control_context,
    stream_context_explicit,
)
from src.agent.invocation import invoke_agent
from src.agent.graph import build_agent_graph
from src.services.auth_service import get_user_from_token
from src.services.chat_pubsub import chat_pubsub
from src.services import chat_session_store as store

logger = logging.getLogger(__name__)
chat_router = APIRouter(tags=["chat"])
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_active_producers: dict[str, asyncio.Task[None]] = {}
_session_turn_locks: dict[str, asyncio.Lock] = {}
_turn_controls: dict[str, dict[str, Any]] = {}
_turn_generations: dict[str, asyncio.Task[dict[str, Any]]] = {}
_turn_cancellations: dict[str, asyncio.Event] = {}


class GenerationInterrupted(Exception):
    """Raised once the underlying provider stream has actually stopped."""


def _resume_stream_delivery(session_id: str, message: dict[str, Any],
                            queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Queue a persisted partial after the snapshot for this subscriber."""
    # The queue is private to this WebSocket, so this synthetic delivery is not
    # broadcast to other subscribers and cannot cause duplicate generation.
    queue.put_nowait({"event": "_resume_stream", "message": message})


class IncomingEvent(BaseModel):
    event: str
    data: dict[str, Any]


class UserMessage(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=1000)


class InterruptRequest(BaseModel):
    session_id: str
    new_input: str = Field(min_length=1, max_length=1000)


async def _run_generation(graph: Any, session_id: str, user_id: str, question: str,
                          token_queue: asyncio.Queue[str], cancel_signal: threading.Event,
                          control: dict[str, Any], stopped: asyncio.Event) -> dict[str, Any]:
    """Consume the existing graph while its synchronous model streams answer deltas."""
    loop = asyncio.get_running_loop()

    def emit_token(token: str) -> None:
        def enqueue_if_active() -> None:
            if not cancel_signal.is_set():
                token_queue.put_nowait(token)

        loop.call_soon_threadsafe(enqueue_if_active)

    callback_token = stream_callback_context.set(emit_token)
    cancel_token = stream_cancel_context.set(cancel_signal)
    control_token = stream_control_context.set(control)
    explicit_token = stream_context_explicit.set(True)
    try:
        return await invoke_agent(graph, question, session_id, user_id)
    finally:
        stream_callback_context.reset(callback_token)
        stream_cancel_context.reset(cancel_token)
        stream_control_context.reset(control_token)
        stream_context_explicit.reset(explicit_token)
        stopped.set()


async def _produce_turn(graph: Any, session_id: str, user_id: str, text: str) -> None:
    user_message = store.add_message(session_id, "user", text)
    await chat_pubsub.publish(session_id, {
        "event": "user_message",
        "data": {"session_id": session_id, "message_id": user_message["message_id"], "text": text},
    })
    assistant = store.add_message(session_id, "assistant", "", status="streaming")
    token_queue: asyncio.Queue[str] = asyncio.Queue()
    cancel_signal = threading.Event()
    control: dict[str, Any] = {"close_stream": None}
    stopped = asyncio.Event()
    generation = asyncio.create_task(
        _run_generation(graph, session_id, user_id, text, token_queue, cancel_signal, control, stopped)
    )
    _turn_controls[session_id] = control
    _turn_generations[session_id] = generation
    _turn_cancellations[session_id] = cancel_signal
    sequence = 0
    text_so_far = ""
    try:
        while not generation.done() or not token_queue.empty():
            if token_queue.empty() and not generation.done():
                get_token = asyncio.create_task(token_queue.get())
                done, _ = await asyncio.wait({generation, get_token}, return_when=asyncio.FIRST_COMPLETED)
                if get_token in done:
                    token = get_token.result()
                else:
                    get_token.cancel()
                    with suppress(asyncio.CancelledError):
                        await get_token
                    continue
            elif not token_queue.empty():
                token = token_queue.get_nowait()
            else:
                break
            text_so_far += token
            sequence += 1
            store.update_message(assistant["message_id"], text=text_so_far, status="streaming", sequence=sequence)
            await chat_pubsub.publish(session_id, {
                "event": "token_chunk",
                "data": {"session_id": session_id, "message_id": assistant["message_id"],
                         "token": token, "sequence": sequence},
            })
        result = await generation
        if cancel_signal.is_set():
            raise GenerationInterrupted
        while not token_queue.empty():
            token = token_queue.get_nowait()
            text_so_far += token
            sequence += 1
            store.update_message(assistant["message_id"], text=text_so_far, status="streaming", sequence=sequence)
            await chat_pubsub.publish(session_id, {
                "event": "token_chunk",
                "data": {"session_id": session_id, "message_id": assistant["message_id"],
                         "token": token, "sequence": sequence},
            })
        final_answer = result.get("answer", "")
        if not text_so_far and isinstance(final_answer, str) and final_answer:
            text_so_far = final_answer
            sequence = 1
            await chat_pubsub.publish(session_id, {
                "event": "token_chunk",
                "data": {"session_id": session_id, "message_id": assistant["message_id"],
                         "token": final_answer, "sequence": sequence},
            })
        store.update_message(assistant["message_id"], text=text_so_far, status="completed")
        store.set_session_status(session_id, "active")
        await chat_pubsub.publish(session_id, {
            "event": "generation_completed",
            "data": {"session_id": session_id, "message_id": assistant["message_id"]},
        })
    except (asyncio.CancelledError, GenerationInterrupted) as interruption:
        was_task_cancelled = isinstance(interruption, asyncio.CancelledError)
        cancel_signal.set()
        close_stream = control.get("close_stream")
        if callable(close_stream):
            with suppress(Exception):
                close_stream()
        # Do not cancel the coroutine driving invoke_agent: that would not stop
        # synchronous provider work in LangGraph's worker. Close its response,
        # then wait for its finally block to confirm the stream has stopped.
        with suppress(asyncio.CancelledError, Exception):
            await generation
        await stopped.wait()
        while not token_queue.empty():
            token = token_queue.get_nowait()
            text_so_far += token
            sequence += 1
            store.update_message(assistant["message_id"], text=text_so_far, status="streaming", sequence=sequence)
            await chat_pubsub.publish(session_id, {
                "event": "token_chunk",
                "data": {"session_id": session_id, "message_id": assistant["message_id"],
                         "token": token, "sequence": sequence},
            })
        store.update_message(assistant["message_id"], text=text_so_far, status="interrupted")
        store.set_session_status(session_id, "interrupted")
        await chat_pubsub.publish(session_id, {
            "event": "generation_interrupted",
            "data": {"session_id": session_id, "message_id": assistant["message_id"], "status": "interrupted"},
        })
        if was_task_cancelled:
            raise asyncio.CancelledError
    except Exception:
        if cancel_signal.is_set():
            # Provider clients may raise while close() tears down an active
            # HTTP response. That is an abort, not a failed assistant turn.
            store.update_message(assistant["message_id"], text=text_so_far, status="interrupted")
            store.set_session_status(session_id, "interrupted")
            await chat_pubsub.publish(session_id, {
                "event": "generation_interrupted",
                "data": {"session_id": session_id, "message_id": assistant["message_id"],
                         "status": "interrupted"},
            })
            return
        logger.exception("Chat agent turn failed (session_id=%s)", session_id)
        store.update_message(assistant["message_id"], text=text_so_far, status="failed")
        await chat_pubsub.publish(session_id, {
            "event": "chat_error", "data": {"session_id": session_id, "message": "No se pudo generar una respuesta."}
        })
    finally:
        if _turn_controls.get(session_id) is control:
            _turn_controls.pop(session_id, None)
            _turn_generations.pop(session_id, None)
            _turn_cancellations.pop(session_id, None)


async def _start_turn(graph: Any, session_id: str, user_id: str, text: str) -> None:
    """Ensure one agent producer per session across all subscriber sockets."""
    turn_lock = _session_turn_locks.setdefault(session_id, asyncio.Lock())
    async with turn_lock:
        active = _active_producers.get(session_id)
        if active and not active.done():
            cancel = _turn_cancellations.get(session_id)
            if cancel:
                cancel.set()
            control = _turn_controls.get(session_id, {})
            close_stream = control.get("close_stream")
            if callable(close_stream):
                with suppress(Exception):
                    close_stream()
            generation = _turn_generations.get(session_id)
            if generation and not generation.done():
                with suppress(asyncio.CancelledError, Exception):
                    await generation
            active.cancel()
            with suppress(asyncio.CancelledError):
                await active
        task = asyncio.create_task(_produce_turn(graph, session_id, user_id, text))
        _active_producers[session_id] = task
    try:
        await task
    except asyncio.CancelledError:
        # Replacing an older producer is an expected turn transition. Do not
        # let cancellation of that child cancel the socket's scheduling task.
        if not task.cancelled():
            raise
    finally:
        if _active_producers.get(session_id) is task:
            _active_producers.pop(session_id, None)


@chat_router.websocket("/chat/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str) -> None:
    if not _SESSION_ID.fullmatch(session_id):
        await websocket.close(code=1008, reason="session_id inválido")
        return
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Autenticación requerida")
        return
    try:
        user = get_user_from_token(token)
        session = store.create_or_get_session(session_id, str(user.id))
    except (ValueError, PermissionError):
        await websocket.close(code=1008, reason="No autorizado")
        return

    await websocket.accept()
    agent_graph = getattr(websocket.app.state, "agent_graph", None)
    if agent_graph is None:
        agent_graph = build_agent_graph()
    queue = await chat_pubsub.subscribe(session_id)
    snapshot_messages = store.list_messages(session_id)
    streaming_messages = [item for item in snapshot_messages
                          if item.get("role") == "assistant" and item.get("status") == "streaming"]
    await websocket.send_json({
        "event": "session_snapshot",
        "data": {"session_id": session_id, "session": session, "messages": snapshot_messages},
    })
    for item in streaming_messages:
        _resume_stream_delivery(session_id, item, queue)

    async def send_events() -> None:
        while True:
            event = await queue.get()
            if event.get("event") == "_resume_stream":
                message = event["message"]
                await websocket.send_json({
                    "event": "token_chunk",
                    "data": {"session_id": session_id,
                             "message_id": message["message_id"],
                             "token": message.get("text", ""),
                             "sequence": message.get("sequence", 0),
                             "replace": True},
                })
                continue
            await websocket.send_json(event)

    turn_tasks: set[asyncio.Task[None]] = set()

    def schedule_turn(text: str) -> None:
        task = asyncio.create_task(_start_turn(
            agent_graph, session_id, str(user.id), text
        ))
        turn_tasks.add(task)
        task.add_done_callback(turn_tasks.discard)

    async def receive_events() -> None:
        while True:
            raw = await websocket.receive_json()
            try:
                envelope = IncomingEvent.model_validate(raw)
                data = envelope.data
                if data.get("session_id") != session_id:
                    raise ValueError("session_id no coincide con el handshake")
                if envelope.event == "user_message":
                    message = UserMessage.model_validate(data)
                    schedule_turn(message.text)
                elif envelope.event == "interrupt_requested":
                    request = InterruptRequest.model_validate(data)
                    await chat_pubsub.publish(session_id, {
                        "event": "interrupt_requested",
                        "data": {"session_id": session_id, "new_input": request.new_input},
                    })
                    schedule_turn(request.new_input)
                else:
                    await websocket.send_json({"event": "chat_error", "data": {"session_id": session_id, "message": "Evento no soportado."}})
            except (ValidationError, ValueError) as error:
                await websocket.send_json({"event": "chat_error", "data": {"session_id": session_id, "message": str(error)}})

    event_sender = asyncio.create_task(send_events())
    receiver = asyncio.create_task(receive_events())
    try:
        _done, pending = await asyncio.wait({event_sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        event_sender.cancel()
        receiver.cancel()
        for task in (event_sender, receiver):
            if task:
                with suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                    await task
        for task in tuple(turn_tasks):
            if task.done():
                with suppress(asyncio.CancelledError, Exception):
                    await task
        await chat_pubsub.unsubscribe(session_id, queue)
