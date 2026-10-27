"""
TrackFlow Knowledge RAG – API Router
=====================================
Exposes POST /knowledge/query for natural language questions
against the TrackFlow knowledge base.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from src.agent.invocation import invoke_agent
from src.agent.guardrails import summarize_guardrail_events
from src.models.user import User
from src.services.access_control import require_internal_operator

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


# ── Request / Response schemas ─────────────────────────────────────────

class KnowledgeQueryRequest(BaseModel):
    """Body for POST /knowledge/query."""
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Pregunta en lenguaje natural sobre la base de conocimiento de TrackFlow",
        examples=["¿Cuál es la política de devoluciones de TrackFlow?"],
    )

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value).strip()
        if any(unicodedata.category(character) == "Cc" and character not in "\n\t" for character in normalized):
            raise ValueError("La pregunta contiene caracteres de control no permitidos.")
        if len(normalized) < 3:
            raise ValueError("La pregunta debe contener al menos 3 caracteres.")
        return normalized


class KnowledgeQueryResponse(BaseModel):
    """Body for POST /knowledge/query response."""
    answer: str = Field(
        ...,
        description="Respuesta generada por el modelo a partir del contexto recuperado",
    )
    run_id: str = Field(..., description="Identificador para consultar el trace de esta corrida")


class GuardrailSummaryResponse(BaseModel):
    total: int
    by_category: dict[str, int]
    by_action: dict[str, int]
    by_reason: dict[str, int]


async def enforce_knowledge_rate_limit(
    request: Request,
    current_user: User = Depends(require_internal_operator),
) -> None:
    """Apply a shared, authenticated-user limit before any model/tool call."""
    limiter = getattr(request.app.state, "agent_rate_limiter", None)
    if limiter is None:
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible.")
    try:
        allowed, retry_after = await limiter.allow(str(current_user.id))
    except Exception:
        logger.exception("No se pudo consultar el rate limiter del agente")
        # Fail closed: a Redis failure must not permit unbounded model spend.
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible.") from None
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Límite de consultas alcanzado. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )


# ── Endpoint ───────────────────────────────────────────────────────────

@knowledge_router.post(
    "/query",
    response_model=KnowledgeQueryResponse,
    summary="Consultar la base de conocimiento de TrackFlow",
    description=(
        "Recibe una pregunta en lenguaje natural y devuelve una respuesta "
        "generada por IA a partir de la base de conocimiento indexada."
    ),
)
async def knowledge_query(
    payload: KnowledgeQueryRequest,
    request: Request,
    _current_user: User = Depends(require_internal_operator),
    _rate_limit: None = Depends(enforce_knowledge_rate_limit),
) -> KnowledgeQueryResponse:
    """POST /knowledge/query — Query the TrackFlow knowledge base.

    The endpoint invokes the compiled agent graph and returns its run ID.
    """
    run_id = str(uuid4())
    try:
        graph = request.app.state.agent_graph
        result = await invoke_agent(
            graph, payload.question, run_id, str(_current_user.id)
        )
    except Exception:
        logger.exception("Falló la corrida del agente run_id=%s", run_id)
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo procesar la consulta. Identificador: {run_id}",
        ) from None

    if result.get("error"):
        raise HTTPException(status_code=422, detail="La pregunta no es válida.")
    if not result.get("answer"):
        raise HTTPException(
            status_code=500,
            detail=f"El agente no produjo una respuesta. Identificador: {run_id}",
        )

    return KnowledgeQueryResponse(answer=result["answer"], run_id=run_id)


@knowledge_router.get(
    "/guardrails/summary",
    response_model=GuardrailSummaryResponse,
    summary="Resumen de activaciones de guardrails",
)
async def guardrails_summary(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    _current_user: User = Depends(require_internal_operator),
) -> GuardrailSummaryResponse:
    for bound in (since, until):
        if bound is not None and bound.utcoffset() is None:
            raise HTTPException(status_code=422, detail="Las fechas deben incluir zona horaria.")
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=422, detail="since debe ser anterior o igual a until.")
    summary = summarize_guardrail_events(str(_current_user.id), since=since, until=until)
    return GuardrailSummaryResponse.model_validate(summary)
