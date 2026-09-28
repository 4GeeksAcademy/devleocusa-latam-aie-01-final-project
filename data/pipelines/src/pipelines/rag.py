"""
TrackFlow RAG – Retrieval & Generation Pipeline
=================================================
Responsibilities:
  - retrieve():  Embed query → search Qdrant → filter by min_score → return payloads
  - generate_answer():  Build prompt → call LLM → return answer string
  - query():  The single public entry point. retrieve() + generate_answer()

This module does NOT index documents — that lives in data/process/rag.py.
Keeping these responsibilities separate allows a future LangGraph agent
to call retrieve() and generate_answer() as independent steps.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, MatchValue

# ── Load environment variables ─────────────────────────────────────────
_env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_env_path)

# ── Configuration ──────────────────────────────────────────────────────
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION", "trackflow-knowledge-base")

# Embeddings config (same model used in data/process/rag.py)
EMBEDDINGS_MODEL_ID: str = os.getenv("EMBEDDINGS_MODEL_ID", "text-embedding-3-small")
EMBEDDINGS_API_KEY: str = os.getenv("EMBEDDINGS_API_KEY", "")
EMBEDDINGS_BASE_URL: str = os.getenv("EMBEDDINGS_BASE_URL", "https://api.openai.com/v1")

# Generation config (DIFFERENT model for answer generation)
GENERATION_MODEL_ID: str = os.getenv("GENERATION_MODEL_ID", "gpt-4o-mini")
GENERATION_API_KEY: str = os.getenv("GENERATION_API_KEY", "")
GENERATION_BASE_URL: str = os.getenv("GENERATION_BASE_URL", "https://api.openai.com/v1")

# TrackFlow voice and audience (from CONTEXT-trackflow-briefing)
COMPANY_NAME: str = "TrackFlow"
SYSTEM_PERSONA = (
    "Eres el asistente de conocimiento de TrackFlow, empresa de logística "
    "de última milla y gestión de almacenes. Responde como un experto en "
    "logística y operaciones de TrackFlow, con conocimiento de sus políticas, "
    "procedimientos y servicios. Tu audiencia son los account managers, "
    "coordinadores de almacén y agentes de atención al cliente de TrackFlow. "
    "Responde siempre en español de forma clara, profesional y práctica. "
    "Usa la información del contexto proporcionado para fundamentar tus respuestas."
)

NO_CONTEXT_MESSAGE = (
    "No encontré información relevante en la base de conocimiento de TrackFlow "
    "para responder a esa pregunta. Por favor, reformula tu consulta o contacta "
    "al equipo de soporte para obtener más información."
)


# ── Lazy-init clients ──────────────────────────────────────────────────
_embedding_client: Optional[OpenAI] = None
_generation_client: Optional[OpenAI] = None
_qdrant_client: Optional[QdrantClient] = None


def _get_embedding_client() -> OpenAI:
    """Lazy-init the OpenAI client used exclusively for embeddings."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(
            api_key=EMBEDDINGS_API_KEY,
            base_url=EMBEDDINGS_BASE_URL,
        )
    return _embedding_client


def _get_generation_client() -> OpenAI:
    """Lazy-init the OpenAI client used exclusively for generation."""
    global _generation_client
    if _generation_client is None:
        _generation_client = OpenAI(
            api_key=GENERATION_API_KEY,
            base_url=GENERATION_BASE_URL,
        )
    return _generation_client


def _get_qdrant_client() -> QdrantClient:
    """Lazy-init the Qdrant client."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=QDRANT_URL)
    return _qdrant_client


# ── embed() — reuse the same function from data/process ────────────────

def embed(text: str) -> list[float]:
    """Generate an embedding vector for *text* using the dedicated embeddings model.

    This is the SAME function used in data/process/rag.py for indexing.
    Using the same model and parameters ensures consistent vectors on both sides.

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the embedding vector.
    """
    client = _get_embedding_client()
    response = client.embeddings.create(
        model=EMBEDDINGS_MODEL_ID,
        input=text,
    )
    return response.data[0].embedding


# ── retrieve() ─────────────────────────────────────────────────────────

def retrieve(query: str, *, k: int = 5, min_score: float = 0.3) -> list[dict]:
    """Search Qdrant for the k most relevant chunks and filter by minimum score.

    Args:
        query: The user's natural language question.
        k: Maximum number of results to return.
        min_score: Minimum cosine similarity score (0-1). Results below this
                   threshold are discarded.

    Returns:
        A list of payload dicts (each containing at minimum: text,
        source_document, section, company, language, chunk_index).
        The list may be empty if nothing passes the min_score threshold.
    """
    qdrant = _get_qdrant_client()

    # 1. Embed the query using the SAME model as indexing
    query_vector = embed(query)

    # 2. Search Qdrant for the k nearest neighbors
    search_results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=k,
        with_payload=True,
    )

    # 3. Filter by min_score and extract payloads
    filtered_payloads: list[dict] = []
    for result in search_results.points:
        score = getattr(result, "score", 0.0)
        if score >= min_score and result.payload is not None:
            # Convert payload to a plain dict (strip Qdrant SDK objects)
            payload = dict(result.payload) if not isinstance(result.payload, dict) else result.payload
            payload["_score"] = score  # Keep score for debugging/logging
            filtered_payloads.append(payload)

    return filtered_payloads


# ── generate_answer() ──────────────────────────────────────────────────

def generate_answer(question: str, context: list[dict]) -> str:
    """Build a prompt from question + context chunks, call the LLM, and return the answer.

    This function is intentionally separated from query() so that a future
    LangGraph agent can call retrieve() and generate_answer() independently.

    Args:
        question: The user's natural language question.
        context: List of payload dicts returned by retrieve().

    Returns:
        The model's answer as a plain string.
    """
    # 1. Build context block from retrieved chunks
    if not context:
        return NO_CONTEXT_MESSAGE

    context_parts: list[str] = []
    for i, chunk in enumerate(context, 1):
        source = chunk.get("source_document", "desconocido")
        section = chunk.get("section", "sin sección")
        text = chunk.get("text", "")
        context_parts.append(
            f"[Fuente {i}: {source} — Sección: {section}]\n{text}"
        )
    context_block = "\n\n".join(context_parts)

    # 2. Build the user message with context
    user_message = (
        f"Basándote EXCLUSIVAMENTE en la siguiente información de la base de "
        f"conocimiento de {COMPANY_NAME}, responde a la pregunta del usuario.\n"
        f"Si la información no es suficiente para responder completamente, "
        f"indica qué información falta. No inventes datos que no estén en el contexto.\n\n"
        f"=== CONOCIMIENTO DISPONIBLE ===\n{context_block}\n\n"
        f"=== PREGUNTA DEL USUARIO ===\n{question}"
    )

    # 3. Call the LLM
    client = _get_generation_client()
    response = client.chat.completions.create(
        model=GENERATION_MODEL_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PERSONA},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
        max_tokens=1024,
    )

    return response.choices[0].message.content or NO_CONTEXT_MESSAGE


# ── query() — public entry point ───────────────────────────────────────

def query(question: str, *, k: int = 5, min_score: float = 0.3) -> str:
    """The ONLY function external consumers should call.

    Orchestrates: retrieve() → generate_answer() → final answer string.

    Args:
        question: The user's natural language question.
        k: Number of chunks to retrieve.
        min_score: Minimum similarity score threshold.

    Returns:
        The final answer string generated by the LLM.
    """
    context = retrieve(question, k=k, min_score=min_score)
    return generate_answer(question, context)
