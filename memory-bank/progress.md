# Progress
Integración de MCP con su OAUTH terminada y testeada.

## Estado por hito
- Hito 7: RAG completado.
- Base agéntica: grafo, checkpoints PostgreSQL, trazas locales y endpoint integrados.
- Suite API + pipelines: 246 tests pasaron antes del ajuste de ciclo de vida del harness Prefect.
- Después del ajuste: los 34 tests del módulo `test_pipeline.py` pasan con `UserWarning` tratado como error.
- Evals del agente: 3 pasaron.
- Supabase: conexión `SELECT 1` y escritura/lectura de checkpoints verificadas; prueba de grafo dejó 4 snapshots y export de trace dejó 5.

## Foco actual

- Servicio MCP independiente en `mcps/`, FastMCP Streamable HTTP (`/mcp`, puerto 8001) y OAuth resource-server con `mcpauth`; Keycloak 26.3 en Compose (puerto 8080, volumen persistente). Protected Resource Metadata publica resource, issuer y scopes; tools/list y tools/call están protegidos.
- Tools publicadas: `create_incident`, `get_incident`, `list_incidents`, `update_incident_status`, `search_inventory` y `request_inventory_change` deny-only. El último siempre responde `READ_ONLY`; inventario solo usa el GET real.
- Contratos verificados: enums y campos de incidencias reales; cambios de estado por `PATCH /api/incidents/{id}/status`; stock calculado por el router SQLModel activo.
- El agente usa `langchain-mcp-adapters` sobre Streamable HTTP/OAuth; se retiraron las llamadas HTTP directas operativas y se preservó el routing secuencial RAG/incidencias/inventario. El JWT del usuario no pasa al grafo.
- Keycloak para clientes interactivos debe solicitar `openid` además de `trackflow:mcp` y scopes operativos. El token de Inspector inicialmente carecía de `sub`; se añadió el mapper `oidc-sub-mapper` al cliente `trackflow-mcp-playground` y al realm versionado.
- Se creó una cuenta técnica TrackFlow normal vía `POST /users`; `TRACKFLOW_SERVICE_USERNAME` y `TRACKFLOW_SERVICE_PASSWORD` están solo en el `.env` raíz ignorado. MCP los usa para obtener/cachéar el JWT local que requieren las rutas de incidencias. No registrar ni copiar secretos a este archivo.
- Auditoría MCP registra cliente, tool y resultado; el diagnóstico JWT registra solo causa, `alg`, `kid`, nombres de claims y campos fallidos, nunca el token ni los valores de claims.
- Se corrigió el checkpointer LangGraph para conectar Psycopg con `prepare_threshold=None`, evitando `DuplicatePreparedStatement` al iniciar contra el pool PostgreSQL.
- Validación (2026-10-06): suite MCP 9/9; suite API/pipelines 262 pasaron y 2 omitidos; `docker compose config --quiet` pasó; API, MCP y Keycloak quedaron healthy. OAuth Authorization Code/PKCE de Inspector completó code exchange 200 y el mapper `sub` resolvió el rechazo de JWT.
- Flujos reales por MCP: discovery de seis tools; búsqueda de inventario (0 coincidencias en el dataset actual); escritura de inventario rechazada; alta, consulta y lifecycle `open → in_progress → resolved` probados desde el agente. Inspector también creó/consultó tickets y avanzó estado a `discarded`.
- Datos dummy persistidos en TinyDB local: ticket de agente `3de042ca-bcaf-4e25-8cc7-82b235524a78` (resolved) y ticket de Inspector `fc3f875a-0754-4617-8e86-e2a061cd79e4` (discarded). No hay tool de borrado de incidencias.
- Inspector está disponible en `6274` privado; MCP `8001` y Keycloak `8080` fueron públicos temporalmente para Codespaces. Volver `8001` y `8080` a privado al terminar la validación manual.