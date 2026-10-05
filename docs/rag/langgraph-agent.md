# Agente RAG con LangGraph

El endpoint autenticado `POST /knowledge/query` ejecuta el grafo compilado durante el startup de FastAPI. Un clasificador LLM devuelve una decisión tipada para consultar RAG, incidencias, inventario o una combinación. Las fuentes se ejecutan secuencialmente en este orden: RAG, incidencias, inventario; el grafo combina la evidencia disponible para generar la respuesta. No conserva historial de conversación.

## Tools operativas

Las tools consultan por HTTP las APIs de este mismo servicio; no indexan ni simulan datos operativos. `lookup_incidents` solo hace `GET /api/incidents/{id}` o `GET /api/incidents` con filtros. Estas rutas requieren JWT. `lookup_inventory` solo hace `GET /inventory/products`; la ruta GET de inventario actualmente no exige autenticación, aunque se propaga el bearer recibido por el agente. El stock procede del balance calculado por el API SQLModel.

`POST /knowledge/query` exige un bearer JWT válido. El token se pasa al grafo únicamente como contexto efímero y no forma parte del estado, checkpoints ni trazas locales. El timeout de cada llamada HTTP operativa es de 4 segundos; timeout, caída, respuesta inválida o falta de coincidencia generan un fallback explícito y nunca un estado/stock supuesto. En preguntas mixtas, un fallo operativo no impide contestar con evidencia RAG disponible y se informa del fallo.

Configuración no secreta:

```env
TRACKFLOW_API_BASE_URL=http://127.0.0.1:8000
AGENT_ROUTER_MODEL=gpt-4o-mini
```

En Docker Compose el API usa `http://127.0.0.1:8000` para llamar a sus propias rutas. El clasificador reutiliza `GENERATION_MODEL_ID`, `GENERATION_API_KEY` y `GENERATION_BASE_URL` del pipeline RAG (con fallback a `OPENAI_API_KEY` y endpoint OpenAI estándar); si no hay modelo configurado, usa `gpt-4o-mini`. `TRACKFLOW_API_BASE_URL` puede cambiarse cuando el API se despliegue detrás de otra URL.

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