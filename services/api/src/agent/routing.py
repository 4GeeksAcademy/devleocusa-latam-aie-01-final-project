from __future__ import annotations

import json
import os

from openai import OpenAI

from src.agent.state import RoutingDecision


def classify_question(question: str) -> RoutingDecision:
    """Choose live sources from the question using a validated JSON response."""
    client = OpenAI(
        api_key=os.getenv("GENERATION_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("GENERATION_BASE_URL", "https://api.openai.com/v1"),
        timeout=10.0,
    )
    response = client.chat.completions.create(
        model=os.getenv(
            "AGENT_ROUTER_MODEL",
            os.getenv("GENERATION_MODEL_ID", "gpt-4o-mini"),
        ),
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Clasifica la pregunta de soporte y devuelve solo JSON. Usa esta estructura, "
                    "poniendo null en los bloques de fuentes que no selecciones: "
                    '{"sources":["incidents"],"incident":{"ticket_id":"482",'
                    '"status":null,"origin":null,"branch":null,"category":null},'
                    '"inventory":null}. Las fuentes válidas son rag, incidents e inventory. '
                    "Usa RAG para políticas y procedimientos; "
                    "incidents para estado/detalle/filtros de tickets; inventory para stock. "
                    "Selecciona todas las fuentes necesarias si la pregunta es mixta. "
                    "Extrae solo IDs, filtros y productos mencionados explícitamente. "
                    "Incidents requiere ticket_id o al menos un filtro. Inventory requiere "
                    "un nombre, SKU o identificador de producto. No respondas la pregunta."
                ),
            },
            {"role": "user", "content": question},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("El clasificador no devolvió una decisión.")
    return RoutingDecision.model_validate(json.loads(content))