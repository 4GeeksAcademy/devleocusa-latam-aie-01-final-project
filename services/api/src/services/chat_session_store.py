"""Small durable chat-session store using the API's existing TinyDB layer."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from tinydb import Query

from src.database import get_chat_messages_table, get_chat_sessions_table

_lock = RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_session(session_id: str) -> dict[str, Any] | None:
    with _lock:
        item = get_chat_sessions_table().get(Query().session_id == session_id)
        return dict(item) if item else None


def create_or_get_session(session_id: str, user_id: str) -> dict[str, Any]:
    with _lock:
        existing = get_session(session_id)
        if existing:
            if existing["user_id"] != user_id:
                raise PermissionError("La sesión pertenece a otro usuario.")
            return existing
        session = {
            "session_id": session_id,
            "agent_id": "first_line_cx",
            "user_id": user_id,
            # The current identity model has no separate client entity. Keep a
            # stable client key tied to the authenticated customer identity.
            "client_id": user_id,
            "status": "active",
            "created_at": _now(),
        }
        get_chat_sessions_table().insert(session)
        return session


def list_messages(session_id: str) -> list[dict[str, Any]]:
    with _lock:
        messages = get_chat_messages_table().search(Query().session_id == session_id)
        return sorted((dict(item) for item in messages), key=lambda item: item["created_at"])


def add_message(session_id: str, role: str, text: str, status: str = "completed") -> dict[str, Any]:
    item = {
        "message_id": f"msg_{uuid4().hex}",
        "session_id": session_id,
        "role": role,
        "text": text,
        "status": status,
        "created_at": _now(),
    }
    with _lock:
        get_chat_messages_table().insert(item)
    return item


def update_message(
    message_id: str, *, text: str, status: str, sequence: int | None = None
) -> dict[str, Any] | None:
    with _lock:
        table = get_chat_messages_table()
        query = Query().message_id == message_id
        found = table.get(query)
        if not found:
            return None
        update = {"text": text, "status": status}
        if sequence is not None:
            update["sequence"] = sequence
        table.update(update, query)
        updated = table.get(query)
        return dict(updated) if updated else None


def set_session_status(session_id: str, status: str) -> None:
    if status not in {"active", "interrupted", "closed"}:
        raise ValueError("Estado de sesión no permitido.")
    with _lock:
        get_chat_sessions_table().update({"status": status}, Query().session_id == session_id)
