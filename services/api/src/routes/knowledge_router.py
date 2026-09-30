"""
TrackFlow Knowledge RAG – API Router
=====================================
Exposes POST /knowledge/query for natural language questions
against the TrackFlow knowledge base.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


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
async def knowledge_query(payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
    """POST /knowledge/query — Query the TrackFlow knowledge base.

    This endpoint imports and calls query() from the RAG pipeline.
    No retrieval or generation logic is duplicated here.
    """
    try:
        # Import here to avoid circular imports and to allow lazy loading
        from src.pipelines.rag import query as rag_query

        answer = rag_query(payload.question)
        return KnowledgeQueryResponse(answer=answer)

    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"El módulo RAG no está disponible: {e}",
        )
    except Exception as e:
        # Log the full error server-side; return a safe message to the client
        raise HTTPException(
            status_code=500,
            detail=f"Error al procesar la consulta: {type(e).__name__}",
        )
