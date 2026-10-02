# Progress
RAG base terminado; flujo agéntico LangGraph integrado en la rama `feature/langgraph-agent-base`.

## Estado por hito
- Hito 7: RAG completado.
- Base agéntica: grafo, checkpoints PostgreSQL, trazas locales y endpoint integrados.
- Suite API + pipelines: 246 tests pasaron antes del ajuste de ciclo de vida del harness Prefect.
- Después del ajuste: los 34 tests del módulo `test_pipeline.py` pasan con `UserWarning` tratado como error.
- Evals del agente: 3 pasaron.
- Supabase: conexión `SELECT 1` y escritura/lectura de checkpoints verificadas; prueba de grafo dejó 4 snapshots y export de trace dejó 5.

## Foco actual
- Cerrar brecha de compilación: LangGraph rechaza edges a nodos inexistentes, pero acepta nodos desconectados; `TypedDict` no valida los tipos en runtime.
- Las evals en `tests/pipelines/test_agent_traces.py` verifican snapshots fixture; no son todavía una evaluación automática de una corrida real de retrieval/generación.