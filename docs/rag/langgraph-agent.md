# Agente RAG con LangGraph

El endpoint autenticado `POST /knowledge/query` ejecuta el grafo compilado durante el startup de FastAPI. Un clasificador LLM devuelve una decisión tipada para consultar RAG, incidencias, inventario o una combinación. Las fuentes se ejecutan secuencialmente en este orden: RAG, incidencias, inventario; el grafo combina la evidencia disponible para generar la respuesta. La memoria episódica por usuario está en tablas PostgreSQL separadas, con una propuesta pendiente de consentimiento explícito y auditoría; no se escribe en Qdrant ni en el knowledge base. Diseño, restricciones y retención: [agent-memory-design.md](../agent-memory-design.md).

## Tools operativas vía MCP

Las consultas operativas se cargan por discovery desde el servidor MCP independiente, usando `langchain-mcp-adapters` y Streamable HTTP. El agente ya no llama directamente a `/api/incidents` ni a `/inventory/products`. Las operaciones expuestas, schemas y scopes están documentados en [mcps/README.md](../../mcps/README.md).

El cliente del agente usa OAuth client credentials y pide un token con `trackflow:mcp incidents:read inventory:read`. Las credenciales OAuth se mantienen en la configuración del servicio API, fuera del estado de LangGraph, checkpoints y traces. El MCP valida bearer, issuer, audience y scopes con `mcpauth`; a su vez usa una cuenta técnica TrackFlow separada para las rutas de incidencias que exigen el JWT local. No se reenvía el token del usuario de `POST /knowledge/query`.

El MCP consulta las APIs existentes, no accede directamente a TinyDB ni a Supabase. La búsqueda de inventario usa el `current_stock` calculado por el API SQLModel. Actualizar el estado de una incidencia usa únicamente `PATCH /api/incidents/{id}/status`. Inventario es read-only y la tool deny-only `request_inventory_change` responde `READ_ONLY` sin efectos.

Las llamadas MCP fallidas generan fallbacks honestos del agente. En preguntas mixtas, un fallo operativo no impide contestar con evidencia RAG disponible. Las trazas locales conservan el estado/conteo de resultados, no payloads de herramientas ni credenciales.

Configuración local: seguir los pasos de [mcps/README.md](../../mcps/README.md), incluyendo `MCP_SERVER_URL`, `MCP_OAUTH_TOKEN_URL`, `MCP_OAUTH_CLIENT_ID`, `MCP_OAUTH_CLIENT_SECRET` y `MCP_OAUTH_SCOPES`. El clasificador reutiliza `GENERATION_MODEL_ID`, `GENERATION_API_KEY` y `GENERATION_BASE_URL` del pipeline RAG (con fallback a `OPENAI_API_KEY` y endpoint OpenAI estándar); si no hay modelo configurado, usa `gpt-4o-mini`.

## Checkpoints y trazas

El checkpointer PostgreSQL de LangGraph usa `SQL_URL`, la misma conexión configurada para PostgreSQL/Supabase. El saver crea su esquema al iniciar la API. Cada corrida usa un `run_id` como `thread_id` interno; el endpoint lo devuelve con `answer`.

Las trazas locales se escriben como JSONL, una corrida por línea, con eventos ordenados. Incluyen las fuentes seleccionadas, nodos recorridos y estado/conteo de resultados operativos; omiten payloads completos de tickets/productos y el bearer. La ruta por defecto es `services/api/data/agent_traces.jsonl`; `AGENT_TRACE_PATH` permite cambiarla. En despliegues con LangSmith se puede configurar:

```env
LANGSMITH_API_KEY=<secret>
LANGSMITH_PROJECT=trackflow-agent
LANGSMITH_TRACING=true
AGENT_TRACE_PATH=/ruta/persistente/agent_traces.jsonl
```

Si `LANGSMITH_API_KEY` está presente y `LANGSMITH_TRACING` no se definió, el servicio activa LangSmith y usa el proyecto `trackflow-agent`. Sin una clave, se conserva la traza local JSONL.

Las trazas locales conservan la pregunta y la respuesta final; deben almacenarse con controles de acceso apropiados. LangSmith puede capturar contenido de ejecuciones del grafo, por lo que debe deshabilitarse si la política de datos no permite enviar preguntas/evidencia a ese servicio externo.

## Pruebas

Desde la raíz del monorepo:

```bash
uv run --project services/api --with pytest --with scikit-learn python -m pytest services/api/tests tests/pipelines -v
```

Las pruebas `services/api/tests/test_agent_graph.py` cubren rutas deterministas del grafo y casos mixtos/fallback. `tests/pipelines/test_agent_routing_evals.py` agrega dos evals contra el clasificador LLM real: ticket -> incidentes sin RAG y política -> RAG sin tools. Son optativas para evitar llamadas/costos de OpenAI durante la suite normal; habilítalas con `RUN_LIVE_AGENT_EVALS=1` y `OPENAI_API_KEY`. `services/api/tests/test_agent_tools.py` valida contratos, autenticación, timeout y respuestas HTTP usando transporte simulado; los datos simulados solo viven en esos tests. Las evaluaciones anteriores en `tests/pipelines/test_agent_traces.py` siguen leyendo snapshots y no ejecutan Qdrant, OpenAI ni LangSmith.