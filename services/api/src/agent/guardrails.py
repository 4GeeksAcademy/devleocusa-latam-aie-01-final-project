from __future__ import annotations

import logging
import re
import threading
import unicodedata
from collections import deque
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel


GuardrailAction = Literal["allow", "refuse", "redirect"]
GuardrailCategory = Literal["security", "scope", "content", "structural"]

logger = logging.getLogger(__name__)

JAILBREAK_RESPONSE = (
    "No puedo cambiar ni ignorar mis instrucciones. Puedo ayudarte con consultas "
    "de logística y servicios de TrackFlow."
)
PERSONAL_TASK_RESPONSE = (
    "No puedo realizar tareas personales ajenas a TrackFlow. Puedo ayudarte con "
    "consultas sobre envíos, almacenes, carriers, incidencias o devoluciones."
)
SAFE_OUTPUT_FALLBACK = (
    "No puedo compartir esa respuesta de forma segura. Puedo ayudarte con una "
    "consulta sobre los servicios de TrackFlow."
)
CASUAL_REDIRECT = (
    "¿Tienes alguna consulta sobre envíos, almacenes, carriers, incidencias o "
    "devoluciones de TrackFlow?"
)
OUT_OF_SCOPE_RESPONSE = (
    "Puedo responder brevemente preguntas generales, pero mi función principal es "
    "ayudarte con logística y servicios de TrackFlow. ¿Tienes alguna consulta sobre "
    "envíos, almacenes, carriers, incidencias o devoluciones?"
)


class InputDecision(BaseModel):
    action: GuardrailAction
    category: GuardrailCategory | None = None
    reason: str
    response: str | None = None


_JAILBREAK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:ignore|ignora|olvida|desatiende|omite)\b.{0,100}\b(?:previous|anteriores?|instrucciones?|reglas?|prompt|sistema|system)\b",
        r"\b(?:ignore|ignora|disregard|desatiende|omite)\b.{0,100}\b(?:instrucciones?|instructions?|reglas?|rules?)\b",
        r"\b(?:you are now|now you are|ahora eres|desde ahora eres)\b.{0,100}\b(?:chatgpt|asistente|assistant|chatbot)\b",
        r"\b(?:developer mode|modo desarrollador|modo sin restricciones|unrestricted mode)\b",
        r"\b(?:ahora|desde ahora|a partir de ahora)\b.{0,80}\b(?:eres|actua como|you are|become)\b.{0,80}\b(?:sin reglas|sin restricciones|unrestricted|no rules|sin limites|sin limitaciones)\b",
        r"\b(?:actua como si|act as if|pretend you have|finge que tienes)\b.{0,120}\b(?:sin reglas|sin restricciones|no rules|without rules|no restrictions|unrestricted|no tuv\w+ reglas)\b",
        r"\b(?:ignore|ignora|disregard|desatiende|omite)\b.{0,100}\b(?:everything|todo|all instructions|todas las instrucciones)\b.{0,100}\b(?:before|antes|previous|anterior|message|mensaje|system|sistema)\b",
        r"\b(?:forget|olvida)\b.{0,80}\b(?:trabajas|trabajas para|work for|work at|empresa|company|trackflow)\b",
        r"\b(?:forget|olvida)\b.{0,80}\b(?:everything|todo)\b.{0,80}\b(?:before|antes|previous|anterior)\b",
        r"\b(?:revela|muestra|imprime|reveal|show|print)\b.{0,80}\b(?:system prompt|prompt del sistema|instrucciones internas|developer message)\b",
        r"\b(?:jailbreak|override system|override instructions|anula las instrucciones)\b",
    )
)
_PERSONAL_TASK_PATTERN = re.compile(
    r"\b(?:escribeme|escribe|redacta|hazme|haz de|ayudame|crea|write me|write|help me|"
    r"create|actua como|pretend to be)\b.{0,120}\b(?:poema|poetry|poem|ensayo|essay|"
    r"tarea|deberes|universidad|homework|love letter|carta de amor|terapeuta|terapia|"
    r"therapist|therapy|otro proyecto|proyecto personal|personal project|codigo|code|"
    r"asistente personal|personal assistant)\b",
    re.IGNORECASE,
)
_CASUAL_PATTERN = re.compile(
    r"\b(?:hola|buenos dias|buenas tardes|buenas noches|como estas|how are you|"
    r"que hora es|what time is it|capital de|capital of|quien fue|who was|"
    r"dato curioso|trivia|curiosidad|que tiempo hace|weather in|chiste|joke)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def inspect_user_input(question: str) -> InputDecision:
    """Apply deterministic high-confidence guards before model/tool invocation."""
    normalized = _normalize(question)
    if any(pattern.search(normalized) for pattern in _JAILBREAK_PATTERNS):
        return InputDecision(
            action="refuse",
            category="security",
            reason="instruction_override",
            response=JAILBREAK_RESPONSE,
        )
    if _PERSONAL_TASK_PATTERN.search(normalized):
        return InputDecision(
            action="refuse",
            category="scope",
            reason="personal_task",
            response=PERSONAL_TASK_RESPONSE,
        )
    if _CASUAL_PATTERN.search(normalized):
        return InputDecision(
            action="redirect",
            category="scope",
            reason="general_casual_question",
        )
    return InputDecision(action="allow", reason="in_scope_or_unclassified")


_SENSITIVE_OUTPUT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b",
        r"\b(?:password|contrase[nn]a|api[_ -]?key|secret|token|jwt)\s*[:=]?\s*\S+",
        r"\b\d{1,6}\s+[\w.'-]+(?:\s+[\w.'-]+){0,4}\s+(?:street|st\.?|road|rd\.?|avenue|ave\.?|calle|avenida|boulevard|blvd\.?)\b",
        r"\b(?:calle|avenida|carrera|street|road|avenue)\s+[\w.'-]+(?:\s+[\w.'-]+){0,3}\s+(?:numero\s*)?\d{1,6}\b",
        r"\b(?:ssn|dni|nif|passport|pasaporte)\s*(?:es|:|#)?\s*[a-z0-9-]{5,}\b",
        r"\b(?:codigo postal|postal code|zip code)\s*(?:es|:|#)?\s*[a-z0-9 -]{4,10}\b",
        r"\b(?:pasillo|estanteria|muelle|loading dock|warehouse aisle|internal route|ruta interna)\s*(?:n(?:umero|o)?\.?\s*)?\w+\b",
        r"\b(?:negociaci[oó]n(?:es)?(?: comercial)? activa|tarifa negociada|contrato(?:s)?(?: comerciales?)? (?:activos? )?en negociaci[oó]n|deal value|margen comercial confidencial)\b",
        r"\b(?:system prompt|prompt del sistema|instrucciones internas|developer message|api key)\b",
    )
)
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d ().-]{8,}\d(?!\w)")


def validate_model_output(answer: Any) -> str | None:
    """Return a stable failure code when generated text is unsafe or malformed."""
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 6000:
        return "invalid_response_structure"
    normalized_answer = _normalize(answer)
    if _PHONE_PATTERN.search(normalized_answer) or any(
        pattern.search(normalized_answer) for pattern in _SENSITIVE_OUTPUT_PATTERNS
    ):
        return "sensitive_or_internal_content"
    return None


def untrusted_content(source: str, content: Any) -> dict[str, Any]:
    """Represent retrieved/tool/memory text as data, not as an instruction."""
    return {
        "source": source,
        "trust_level": "untrusted_data",
        "text": content,
        "content": content,
    }


_EVENT_LIMIT = 5000
_guardrail_events: deque[dict[str, Any]] = deque(maxlen=_EVENT_LIMIT)
_events_lock = threading.Lock()


def record_guardrail_event(
    *,
    user_id: str,
    run_id: str | None,
    category: GuardrailCategory,
    action: GuardrailAction,
    reason: str,
) -> None:
    """Log and retain content-free metadata for the process-local summary."""
    created_at = datetime.now(UTC)
    event = {
        "user_id": str(user_id),
        "run_id": run_id,
        "created_at": created_at,
        "category": category,
        "action": action,
        "reason": reason,
    }
    with _events_lock:
        _guardrail_events.append(event)
    logger.warning(
        "agent_guardrail_triggered",
        extra={
            "guardrail_category": category,
            "guardrail_action": action,
            "guardrail_reason": reason,
            "run_id": run_id,
            "user_id": str(user_id),
        },
    )


def summarize_guardrail_events(
    user_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    with _events_lock:
        matching = [
            event.copy()
            for event in _guardrail_events
            if event["user_id"] == str(user_id)
            and (since is None or event["created_at"] >= since)
            and (until is None or event["created_at"] <= until)
        ]
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for event in matching:
        by_category[event["category"]] = by_category.get(event["category"], 0) + 1
        by_action[event["action"]] = by_action.get(event["action"], 0) + 1
        by_reason[event["reason"]] = by_reason.get(event["reason"], 0) + 1
    return {
        "total": len(matching),
        "by_category": by_category,
        "by_action": by_action,
        "by_reason": by_reason,
    }