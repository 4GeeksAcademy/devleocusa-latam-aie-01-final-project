"""LLM helper shared by every rfp_intake agent.

Single place that owns: client construction, the JSON-response contract and
defensive parsing (the model is asked for JSON, but we never trust it blindly).
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import LLM_MODEL, make_llm

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMResponseError(RuntimeError):
    """Raised when the LLM cannot be coerced into a JSON object."""


def _extract_json(text: str) -> dict[str, Any]:
    """Parse ``text`` as JSON, falling back to the first brace-delimited block."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    raise LLMResponseError(f"Respuesta del LLM no es un JSON valido: {text[:300]!r}")


def chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Call the chat model expecting a JSON object; retry on parse failures."""
    llm = make_llm()
    last_error: Exception | None = None

    for _ in range(max_retries + 1):
        try:
            response = llm.chat.completions.create(
                model=LLM_MODEL,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = response.choices[0].message.content or ""
            return _extract_json(content)
        except LLMResponseError as exc:
            last_error = exc

    raise LLMResponseError(str(last_error)) from last_error
