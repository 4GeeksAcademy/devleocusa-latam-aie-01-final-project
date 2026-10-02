# Agente RAG con LangGraph

El endpoint `POST /knowledge/query` ejecuta el grafo compilado durante el startup de FastAPI. El grafo valida la pregunta, llama una sola vez a `retrieve()` del pipeline existente y dirige el estado a `generate_answer(question, context)` o a la respuesta de abstención si no hay chunks que superen el umbral de retrieval. No conserva historial de conversación.

## Checkpoints y trazas

El checkpointer PostgreSQL de LangGraph usa `SQL_URL`, la misma conexión configurada para PostgreSQL/Supabase. El saver crea su esquema al iniciar la API. Cada corrida usa un `run_id` como `thread_id` interno; el endpoint lo devuelve con `answer`.

Las trazas locales se escriben como JSONL, una corrida por línea, con eventos ordenados y el resultado de cada nodo. La ruta por defecto es `services/api/data/agent_traces.jsonl`; `AGENT_TRACE_PATH` permite cambiarla. En despliegues con LangSmith se puede configurar:

```env
LANGSMITH_API_KEY=<secret>
LANGSMITH_PROJECT=trackflow-agent
LANGSMITH_TRACING=true
AGENT_TRACE_PATH=/ruta/persistente/agent_traces.jsonl
```

Si `LANGSMITH_API_KEY` está presente y `LANGSMITH_TRACING` no se definió, el servicio activa LangSmith y usa el proyecto `trackflow-agent`. Sin una clave, se conserva la traza local JSONL.

Los traces contienen la pregunta, chunks recuperados y respuesta. Deben almacenarse con controles de acceso apropiados y no habilitarse en LangSmith si la política de datos no permite enviar ese contenido al servicio externo.

## Pruebas

Desde la raíz del monorepo:

```bash
uv run --project services/api --with pytest --with scikit-learn python -m pytest services/api/tests tests/pipelines -v
```

Las evaluaciones de agente en `tests/pipelines/test_agent_traces.py` leen snapshots en `tests/pipelines/fixtures/agent_traces.json`; no ejecutan llamadas a Qdrant, OpenAI ni LangSmith.