from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    context: list[dict[str, Any]]
    answer: str
    error: str