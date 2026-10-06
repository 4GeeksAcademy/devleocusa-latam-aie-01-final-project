"""
TrackFlow Knowledge RAG – API Router
=====================================
Exposes POST /knowledge/query for natural language questions
against the TrackFlow knowledge base.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.agent.invocation import invoke_agent
from src.models.user import User
from src.services.auth_service import get_current_user

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


class KnowledgeQueryResponse(BaseModel):
    """Body for POST /knowledge/query response."""
    answer: str = Field(
        ...,
        description="Respuesta generada por el modelo a partir del contexto recuperado",
    )
    run_id: str = Field(..., description="Identificador para consultar el trace de esta corrida")


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
    _current_user: User = Depends(get_current_user),
) -> KnowledgeQueryResponse:
    """POST /knowledge/query — Query the TrackFlow knowledge base.

    The endpoint invokes the compiled agent graph and returns its run ID.
    """
    run_id = str(uuid4())
    try:
        result = await invoke_agent(
            request.app.state.agent_graph,
            payload.question,
            run_id,
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
