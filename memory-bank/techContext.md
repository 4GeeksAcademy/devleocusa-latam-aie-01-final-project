# Technical Context

## Política de memoria del agente
- Seguir `MEMORY-trackflow.es.md` (no la allowlist provisional del briefing): reglas de carrier corregidas; contexto de incidencias con patrón repetible; preferencias de reportes para clientes B2B recurrentes.
- No persistir direcciones ni ubicaciones sensibles B2B/B2C, rutas internas de almacén, incidencias puntuales sin patrón ni información de negociación comercial activa.
- Memoria episódica privada en PostgreSQL, separada de RAG/Qdrant y nunca fuente autoritativa de políticas; requiere consentimiento explícito. Propuesta 7d, memoria 180d, máximo 20 activas por usuario.

## Visión General

TrackFlow es una plataforma logística B2B para e-commerce mediano (moda, electrónica, cosmética) que opera binacionalmente entre **Los Ángeles (EE.UU.)** y **Zaragoza (España)**. El proyecto cubre tres líneas de servicio: almacenes, última milla y logística inversa. El sistema se construyó como **monorepo** para centralizar aplicaciones, servicios, datos y automatizaciones bajo un único repositorio versionado.

---

## Arquitectura

### Patrón principal
- **Monolito modular orientado a dominio** en el backend (FastAPI).
- **Separación por contratos API** entre frontend y backend (desacoplados por contrato, no por repositorio).
- **Fronteras de dominio explícitas**: cada módulo backend conserva reglas propias y evita dependencia accidental.

### Organización del código (monorepo)

| Directorio | Responsabilidad |
|---|---|
| `/uis/website` | Sitio corporativo público (landing page, marketing) |
| `/uis/backoffice` | Panel interno: autenticación, leads, candidaturas, inventario, incidencias, proveedores, reporting, telemetría, base de conocimiento |
| `/services/api` | Backend principal — FastAPI con routers por dominio |
| `/services/reporting` | Módulo de reporting ejecutivo (Prefect pipeline → TinyDB) |
| `/services/telemetry` | Módulo de ingestión y análisis de telemetría |
| `/data/pipelines` | Orquestación de pipelines con Prefect |
| `/data/process` | Procesamiento de datos (RAG, embeddings) |
| `/data/raw` | Datos crudos |
| `/src/` | Tipos y utilidades TypeScript compartidas entre frontends |
| `/packages/shared/` | Paquete compartido `@repo/shared-types` |
| `/skills/` | Skills reutilizables para agentes IA |
| `/agents/` | Patrones y plantillas de agentes IA |
| `/workflows` | Documentación de automatizaciones/orquestación |
| `/scripts` | Scripts utilitarios (análisis, exportación nocturna, validación, seed de incidencias) |
| `/docs` | Documentación del proyecto (RAG, telemetría, knowledge base, serialización) |
| `/memory-bank` | Notas de contexto del proyecto y progreso |
| `/sql/` | Consultas y esquemas SQL |
| `/tests/` | Pruebas de pipelines Python |

---

## Stack tecnológico

### Frontend
| Tecnología | Versión | Uso |
|---|---|---|
| **Next.js** | 16.2.9 (App Router) | Framework React para website y backoffice |
| **React** | 19.2.4 | Librería de UI |
| **TypeScript** | 5.x | Tipado estático |
| **Tailwind CSS** | 4.x | Estilos utility-first |
| **Turbopack** | (bundled) | Bundler de desarrollo (configurado con `root` en monorepo) |

### Backend
| Tecnología | Versión | Uso |
|---|---|---|
| **Python** | 3.11+ | Lenguaje del backend |
| **FastAPI** | ≥0.141.1 | Framework web principal |
| **Uvicorn** | ≥0.52.0 | ASGI server con hot-reload |
| **SQLModel** | ≥0.0.22, <0.0.34 | ORM / esquemas para PostgreSQL |
| **Pydantic** | ≥2.13.0 | Validación y serialización |
| **Pydantic Settings** | ≥2.15.0 | Configuración tipada desde variables de entorno |
| **TinyDB** | 4.8.0 | Base de datos local ligera (auth, proveedores, reporting) |
| **Psycopg2** | ≥2.9.0 | Conector PostgreSQL |
| **Supabase** | ≥2.0.0 | PostgreSQL managed (inventario SQL) |

### Tareas asíncronas y orquestación
| Tecnología | Versión | Uso |
|---|---|---|
| **Celery** | ≥5.4.0 (con Redis broker) | Tareas asíncronas (generación de reportes PDF) |
| **Prefect** | ≥3.8.4 | Orquestación de pipelines de datos |
| **Redis** | (Alpine) | Message broker para Celery + caché |
| **Flower** | 2.0 | Dashboard de observabilidad de Celery workers |

### Seguridad
| Tecnología | Versión | Uso |
|---|---|---|
| **python-jose** | ≥3.5.0 | JWT tokens |
| **passlib + bcrypt** | ≥1.7.4 | Hashing de contraseñas |
| **SendGrid** | ≥6.12.5 | Envío de emails (reset de contraseña) |

### Base de datos vectorial (RAG)
| Tecnología | Versión | Uso |
|---|---|---|
| **Qdrant** | latest | Base de datos de vectores para el sistema RAG |
| **OpenAI embeddings** | text-embedding-3-small | Generación de embeddings (dimensión 1536) |
| **OpenAI generation** | gpt-4o-mini | Generación de respuestas en lenguaje natural |

### Análisis de datos
| Tecnología | Versión | Uso |
|---|---|---|
| **Pandas** | ≥2.1.0 | Análisis y transformación de datos |
| **WeasyPrint** | ≥60.0 | Renderizado de PDFs |

### Testing
| Tecnología | Uso |
|---|---|
| **pytest** | Pruebas backend Python |
| **Jest** | Pruebas TypeScript (unitarias, con ts-jest) |
| **Vitest** | Framework de pruebas alternativo |

### Infraestructura
| Tecnología | Uso |
|---|---|
| **Docker** | Contenedores para API, UIS, Redis, Celery Worker, Flower, Qdrant |
| **Docker Compose** | Orquestación local de todos los servicios |
| **uv** | Instalador rápido de dependencias Python en Dockerfiles |

---

## Servicios desplegados (Docker Compose)

| Servicio | Puerto | Descripción |
|---|---|---|
| `api` | 8000 | Backend FastAPI (auth, inventario, incidencias, proveedores, usuarios, profiles, reporting, telemetría, knowledge) |
| `uis` | 3000, 3001 | Next.js (website en 3000, backoffice en 3001) |
| `redis` | 6379 | Message broker + caché |
| `celery-worker` | — | Worker de Celery para tareas asíncronas |
| `flower` | 5555 | Dashboard de observabilidad de Celery |
| `qdrant` | 6333, 6334 | Base de datos vectorial para RAG |

Red interna: `trackflow-net` (bridge). Variables de entorno compartidas vía `x-common-env` (`REDIS_URL`, `QDRANT_URL`).

---

## Módulos del Backend (FastAPI)

### Routers y dominios

| Router | Prefijo | Dominio |
|---|---|---|
| `auth_router` | `/auth` | Login JWT, `/me`, forgot/reset/change password |
| `users_router` | `/users` | CRUD de usuarios con roles (ADMIN, OPERATOR, VIEWER) |
| `profiles_router` | `/profiles` | Perfiles de usuario (`/me`) |
| `inventory_router` | `/inventory` | SKU, entradas/salidas de stock con cálculo dinámico |
| `suppliers_fastapi_router` | — | Directorio de proveedores (CRUD, filtros por país/categoría) |
| `incidents_fastapi_router` | — | Gestión de incidencias (CRUD, transiciones de estado, análisis CSV) |
| `reports_router` | `/reports` | Generación asíncrona de informes (dispatch Celery + polling) |
| `reporting_router` | `/reporting` | Pipeline ejecutivo: status, run manual, KPIs históricos |
| `telemetry_router` | configurable | Ingesta de eventos de telemetría + reporte agregado |
| `knowledge_router` | `/knowledge` | Consulta RAG contra la base de conocimiento |

### Modelo de datos (SQLModel / Supabase)

| Modelo | Tabla | Descripción |
|---|---|---|
| `SKU` | `sku` | Producto/SKU en almacén (sin columna de stock; balance calculado dinámicamente) |
| `SKUEntry` | `sku_entries` | Órdenes de entrada (inbound) |
| `SKUExit` | `sku_exits` | Órdenes de salida (outbound) |

### Modelo de datos (TinyDB — local)

| Tabla | Uso |
|---|---|
| `users` | Usuarios con email, hashed_password, role, is_active |
| `profiles` | Nombre, teléfono, dirección vinculados a user_id |
| `suppliers` | Directorio de proveedores (nombre, país, categorías, tarifa, estado) |
| `incidents` | Incidencias (título, categoría, estado, origen, sucursal) |
| `pipeline_executions` | Metadata de la última ejecución del pipeline |
| `executive_kpis` | Registros de KPIs ejecutivos históricos |
| `carriers` | Transportistas |
| `carrier_assignments` | Asignaciones de transportistas |

### Autenticación y autorización
- **JWT** con `python-jose`, tokens de acceso sin refresh.
- **Roles**: `ADMIN`, `OPERATOR`, `VIEWER`.
- **Contraseña**: validación estricta (límite 72 bytes UTF-8 para bcrypt), hashing bcrypt vía passlib.
- **Recuperación de contraseña**: forgot-password → envío de token por SendGrid → reset con token.
- **Middleware `ProtectedRoute`** en frontend que redirige a `/login` si no hay token válido.

### Caché en memoria
- Clase `TTLCache` personalizada (sin dependencias externas, lazy expiration, `time.monotonic()`).
- Instancias compartidas con invalidación manual ante escrituras:
  - `me_cache` (30s), `profile_cache` (30s)
  - `suppliers_list_cache` (300s), `supplier_cache` (300s)
  - `inventory_products_cache` (30s), `inventory_product_cache` (30s)
  - `_summary_cache` para incidencias (30s)
  - `users_list_cache` (120s)

### Celery tasks
- Generación asíncrona de reportes (executive_weekly, client_pdf).
- Patrón fire-and-forget + polling (`POST /reports/generate` → 202 Accepted → `GET /tasks/{task_id}`).
- Dead-letter queue en Supabase PostgreSQL para fallos después de 3 reintentos.
- Logging estructurado JSON para agregadores.

---

## Frontend — Backoffice

### Páginas (App Router)

| Ruta | Funcionalidad |
|---|---|
| `/login` | Inicio de sesión JWT |
| `/register` | Registro de usuario |
| `/forgot-password` | Solicitud de reset |
| `/reset-password` | Reset con token |
| `/` | Dashboard con `LeadValidationPanel` |
| `/candidaturas` | CRUD de candidaturas con filtros por status/stage, búsqueda, paginación |
| `/leads` | Vista del módulo de leads (placeholder) |
| `/operaciones` | Hub de operaciones con links a submódulos |
| `/operaciones/proveedores` | Directorio de proveedores |
| `/operaciones/incidencias` | Gestión de incidencias |
| `/operaciones/inventario` | Inventario (rutas legacy) |
| `/backoffice/inventory/*` | Productos/SKU, historial, entradas/salidas |
| `/reporting` | Dashboard de KPIs ejecutivos (volumen envíos, tasa entrega, costos, satisfacción, devoluciones) |
| `/telemetry` | Radar de telemetría (métricas de eventos, errores por tipo) |
| `/knowledge` | Consulta RAG a la base de conocimiento |
| `/account/profile` | Edición de perfil |
| `/account/change-password` | Cambio de contraseña |

### Componentes clave
- `AppShell`: layout con sidebar protegida, manejo de rutas públicas/privadas.
- `SidebarNav`: navegación con items activos resaltados.
- `ProtectedRoute`: wrapper de autenticación (client-side).
- `LeadValidationPanel`, `IncidentsAnalysisPanel`, `SuppliersDirectoryPanel`.
- UI primitives: `Alert`, `Spinner`, `StageBadge`, `StatusBadge`.

### Servicios del frontend
- `authApi.ts`: login, logout, forgot-password, change-password (JWT en localStorage).
- `candidatesApi.ts`: CRUD de candidaturas.
- `incidentsApi.ts`: CRUD de incidencias.
- `telemetry.ts`: emisión de eventos tipados al backend de telemetría.

---

## Frontend — Website
- Página corporativa pública con imagen de Unsplash remota.
- Sin autenticación ni rutas protegidas.
- Configuración Turbopack apuntando a la raíz del monorepo.

---

## Sistema de Telemetría

### Arquitectura
- **Frontend**: librería `telemetry.ts` que construye Event Envelope, sanitiza PII, implementa debounce (page views), throttle (sku.list) y agregación de errores (form validation).
- **Middleware backend**: `TelemetryMiddleware` en FastAPI con sanitización PII (regex para emails, teléfonos,路径, GPS, tarjetas de crédito, DNI, SSN), circuit breaker (silence mode tras >10 errores/10s), y exclusion enforcement.
- **Ingesta**: `POST /telemetry/events` → validación individual de eventos → bulk insert a PostgreSQL.
- **Análisis**: funciones Pandas puras (`error_rate_by_endpoint`, `avg_latency_by_service`, etc.).
- **Reporte**: `GET /telemetry/report` con caché TTL de 60s.

### Schema Registry
- Envoltorio estándar: `eventId`, `timestamp`, `sessionId`, `userId`, `event_type`, `schemaVersion`, `requestId`, `properties`.
- ~35+ tipos de eventos definidos en `event-schemas.json` (auth, sku, incidents, carriers, telemetry, UI, performance).
- Política de datos sensibles: hashing SHA-256 de emails, exclusión de passwords/JWT/GPS, truncación de User-Agent.

### Instrumentación frontend
- `Instrumentation` component en `layout.tsx` que instala:
  - Captura global de errores (`window.onerror` + `unhandledrejection`).
  - Tracking de page views via eventos de router Next.js.
  - Web Vitals (LCP, FID, CLS) con muestreo al 10%.

---

## Sistema RAG (Retrieval-Augmented Generation)

### Flujo
1. **Indexación (offline)**: documentos Markdown de `docs/company-knowledge-base/` → chunking por encabezados/párrafos → embeddings con `text-embedding-3-small` → inserción en Qdrant.
2. **Consulta (online)**: `POST /knowledge/query` → `retrieve()` (5 vecinos más cercanos, min_score 0.3) → `generate_answer()` con `gpt-4o-mini` → respuesta.

### Knowledge base
- `trackflow-carrier-coverage.es.md`: Cobertura de transportistas por país.
- `trackflow-returns-policy.es.md`: Política de devoluciones.
- `trackflow-sla-delivery.es.md`: SLAs de entrega.
- `trackflow-storage-pricing.es.md`: Precios de almacenamiento.

### Parámetros
- Dimensión del vector: 1536. Métrica: Cosine. Batch size de inserción: 50 puntos.

### Agente base con LangGraph (2026-10-02)
- El grafo vive en `services/api/src/agent/`: estado `AgentState` mínimo (`question`, `context`, `answer`, `error`); nodos separados para validar la pregunta, recuperar, generar, abstenerse y manejar pregunta inválida.
- `build_agent_graph()` define rutas condicionales: pregunta inválida evita retrieval; contexto vacío omite generación. Compila durante startup de FastAPI.
- `retrieve()` y `generate_answer(question, context)` se reutilizan a través de `rag_adapter.py`; `query()` monolítico no se invoca. `embed()` sigue siendo reutilizado internamente por el `retrieve()` existente.
- El saver `AsyncPostgresSaver` usa `SQL_URL`; `agent_graph_runtime()` hace `setup()` al iniciar y el endpoint asigna un `run_id` interno como `thread_id`. El 2026-10-02 se verificaron conexión a PostgreSQL, ejecución del grafo y lectura de snapshots reales.
- `POST /knowledge/query` mantiene `question`, retorna `answer` y `run_id`; los errores HTTP no exponen excepciones ni contenido arbitrario del campo `error` interno.
- `invoke_agent()` captura outputs ordenados de nodos; `trace_store.py` los guarda como JSONL en `services/api/data/agent_traces.jsonl` por defecto o en `AGENT_TRACE_PATH`. Los traces contienen pregunta, contexto recuperado y respuesta; protegerlos como datos sensibles.
- LangSmith se habilita con `LANGSMITH_API_KEY`; no había clave configurada en el entorno durante la verificación.
- Export de evidencia: `outputs/langgraph-agent-trace-validation.jsonl`. Usa el documento de devoluciones real, saver PostgreSQL real y cinco snapshots, pero retrieval/generación deterministas simulados porque Qdrant no respondió. No cuenta como consulta RAG live.
- Tres evals offline leen fixtures en `tests/pipelines/fixtures/agent_traces.json`; incluyen abstención, orden de nodos y una respuesta fixture anclada a `trackflow-returns-policy.es.md` (`30 días`). No sustituyen una evaluación sobre traces live.
- Estado de validación (2026-10-02): los tres evals pasaron; API + pipelines dieron 246 pasados antes del cambio del harness Prefect; tras cambiar a un harness por módulo, los 34 tests de `test_pipeline.py` pasan con `UserWarning` convertido en error. Recall@3 offline existente pasó 10/10.
- Pendiente técnico: LangGraph detecta edges a nodos inexistentes al compilar, pero no detecta nodos desconectados; `TypedDict` describe el estado sin validación de tipos en runtime. Qdrant y LangSmith no se validaron en vivo en este entorno.

### Memoria episódica del agente (2026-10-08)
- Política de `MEMORY-trackflow.es.md`: correcciones de carrier consolidadas carrier+país/zona, contexto de incidencias recurrentes y preferencias de informes mensuales B2B.
- Nunca recordar ubicaciones sensibles B2B/B2C, rutas internas de almacén, incidentes aislados de paquete ni negociaciones comerciales activas. `CONTEXT-company.md` no existe en el workspace auditado; `MEMORY-trackflow.es.md` es la fuente explícita de guardrails disponible.
- PostgreSQL separado en `agent_memory_proposals`, `agent_approved_memories` y `agent_memory_decisions`; no usa Qdrant/RAG ni checkpoints como almacén. Interfaz explícita `PostgresAgentMemoryStore`. La elección evita infraestructura vectorial para un máximo de 20 recuerdos pequeños por usuario y facilita claves únicas, TTL y auditoría.
- El turno del agente presenta la propuesta y solicita consentimiento en la misma conversación. La decisión se clasifica estructuradamente frente a la propuesta activa; `explicit_confirmation` debe ser verdadero para aprobar. Ambigüedad, error del clasificador, edición no re-aprobada y silencio al expirar no autorizan escritura (rechazo por defecto).
- Índice único parcial para una propuesta pendiente por usuario; consolidación por clave canónica; TTL 7/180 días; límite 20 recuerdos activos. Expiraciones y resultados de decisiones dejan auditoría; no se conserva el texto original libre de respuesta en los campos de decisión.
- `docs/agent-memory-design.md` incluye ejemplos memorables/no memorables y ciclos de aceptación. El 2026-10-08 se ejecutó el store contra Supabase en un esquema aislado/transacción revertida: ciclo aprobado creó y recuperó la memoria más su auditoría; ciclo rechazado conservó la memoria anterior sin añadir otra y registró `rejected`. Sin datos persistentes de prueba.
- La prueba ejercitó `setup`, DDL/índices y APIs de store con decisión ya determinada; no llamó al clasificador LLM ni al flujo HTTP completo. Aún faltan integración del clasificador, migración sobre esquema legado poblado, concurrencia real y expiración/limpieza.
- Validación de código registrada: 240 pruebas API, `compileall` y `git diff --check` pasaron.

---

## Pipelines de Datos

### Pipeline ejecutivo (Prefect)
- Orquestado vía Prefect con `@flow` decorators.
- Extrae datos, calcula KPIs ejecutivos (volumen envíos, tasa entrega a tiempo, costos operativos, satisfacción del cliente, devoluciones).
- Persiste resultados en TinyDB via `reporting.store`.
- Exposición vía `GET /reporting/status`, `POST /reporting/run`, `GET /reporting/kpis`.

### Modelo de predicción de ventas
- **Algoritmo**: Random Forest (estabilidad + explicabilidad).
- **Entrenamiento**: primeros 8 años (96 meses), evaluación: últimos 2 años (24 meses).
- **Métricas**: MSE, PSI, Gini normalizado, K2 de D'Agostino-Pearson.

---

## Validación y Contratos

- **Backend**: validación estricta con Pydantic v2 en frontera de API, reglas de dominio separadas.
- **Mensajes de error en español** para el usuario final.
- **Errores normalizados** con catálogo de códigos y detalle técnico acotado.
- **Response schemas desacoplados** de modelos de dominio (ej. `IncidentListResponse` sin `description` para list views).
- **Versionado de API** con prefijo `/api/v1` (diseñado, no aún implementado a nivel de prefijo global).

---

## Pruebas

| Tipo | Herramienta | Comando |
|---|---|---|
| Backend Python (auth, API) | pytest | `uv run pytest tests/ -v` |
| Frontend TypeScript | Jest / Vitest | `npx jest --coverage` / `npx vitest` |
| TypeScript (paquete compartido) | tsc | `npm run typecheck --prefix packages/shared` |
| Validación JS | Node.js | `node scripts/validation.js` |

---

## Principios Técnicos Clave

1. **Separación de concerns**: routers sin lógica de negocio, schemas desacoplados de ORM, configuración centralizada.
2. **Lazy singleton** para engine de base de datos (resuelve problemas con reloader de Uvicorn).
3. **Caché con invalidación proactiva**: TTL como safety net, invalidación inmediata ante escrituras.
4. **PII-first en telemetría**: sanitización en cliente y middleware, nunca se capturan passwords ni JWT completos.
5. **Lazy loading en frontend**: `next/dynamic` para componentes pesados, `useMemo` para cálculos derivados.
6. **Reutilización de lógica**: pipelines compartidos entre reporting y data/pipelines, utilidades TypeScript en `/src/` montadas en contenedor.
7. **Consistencia binacional**: reglas nucleares parametrizadas por país, configuración centralizada.
8. **Monorepo con hot-reload**: bind-mounts de código fuente en Docker para desarrollo iterativo rápido.

---

## Servidor MCP de herramientas corporativas (2026-10-06)

### Arquitectura y runtime
- El servicio vive en `mcps/` y ejecuta FastMCP por Streamable HTTP en `/mcp` (puerto 8001). `mcpauth` se integra como resource server; no se usan helpers OAuth de FastMCP.
- `/.well-known/oauth-protected-resource` es metadata pública del protocolo; MCP exige bearer JWT válido antes de `tools/list` y `tools/call`. Keycloak 26.3 es issuer local de desarrollo en Compose, con estado persistido en `trackflow_keycloak_data`.
- El cliente `trackflow-agent` usa client credentials y scopes mínimos. El cliente público `trackflow-mcp-playground` usa authorization code + PKCE S256.
- Configuración principal: `MCP_PUBLIC_URL`, `MCP_AUDIENCE=trackflow-mcp`, `OAUTH_ISSUER_URL`, `OAUTH_JWKS_URI`, `MCP_OAUTH_TOKEN_URL`, `MCP_OAUTH_CLIENT_ID`, `MCP_OAUTH_CLIENT_SECRET`, `MCP_OAUTH_SCOPES`, `TRACKFLOW_SERVICE_USERNAME`, `TRACKFLOW_SERVICE_PASSWORD`. Valores secretos viven solo en `.env` ignorado.

### Scopes y tokens OIDC
- Scope base MCP: `trackflow:mcp`. Scopes por tool: `incidents:read`, `incidents:create`, `incidents:status:write`, `inventory:read`.
- Clientes interactivos de Keycloak deben solicitar `openid` además de los scopes anteriores; `mcpauth` requiere `sub` en el access token.
- Keycloak 26 no creó automáticamente el client scope `basic` ni su mapper subject en este realm. Por eso el cliente `trackflow-mcp-playground` tiene el mapper `oidc-sub-mapper` configurado con `access.token.claim=true`. El mapper también está declarado en `mcps/keycloak/realm.json` para nuevos imports.
- `offline_access` no se requiere para probar; desactivar “Request refresh token” en Inspector evita refreshes tras cerrar la sesión SSO. Al cambiar mappers/scopes, borrar OAuth state y autorizar de nuevo.
- La integración de diagnóstico `verify_access_token` usa el verificador JWKS de `mcpauth`; ante rechazo solo registra tipo de excepción, algoritmo, `kid`, nombres de claims y campos faltantes. Nunca registrar bearer ni valores de claims.

### Contratos MCP
- Incidencias llaman la API FastAPI activa, usando una cuenta técnica TrackFlow normal para sus rutas con JWT local. La cuenta fue creada por `POST /users`; los nombres/email y password no deben escribirse en Memory Bank.
- Crear usa `POST /api/incidents`; consultar usa `GET /api/incidents/{id}` o filtros; cambio de estado usa únicamente `PATCH /api/incidents/{id}/status`.
- Inventario usa `GET /inventory/products` y filtra los `SKURead` live (`id`, `name`, `sku_code`, `warehouse`, `current_stock`). Ninguna tool de escritura llama endpoints; `request_inventory_change` responde `READ_ONLY` explícitamente.
- FastMCP puede entregar el resultado a `langchain-mcp-adapters` como bloque JSON de texto; `services/api/src/agent/mcp_tools.py` soporta tanto ese formato como `structuredContent`.
- Auditoría de `tools/call` registra cliente, tool y resultado. El logger `trackflow_mcp.tools` debe mantenerse en nivel INFO para emitir esas entradas en runtime.

### LangGraph y validación
- `agent_graph_runtime()` carga las tools MCP al startup. Los nodos operativos son async; se mantiene el orden RAG → incidencias → inventario y los fallbacks previos. No queda camino HTTP directo del agente a los endpoints operativos.
- El checkpointer se conecta con `psycopg.AsyncConnection.connect(..., prepare_threshold=None)` porque el saver predeterminado preparaba cada statement y causaba colisión `DuplicatePreparedStatement` en el pool PostgreSQL.
- Validación del 2026-10-06: `uv run --project mcps pytest -q mcps/tests` (9 pasaron); suite API/pipelines (262 pasaron, 2 omitidos); Compose válido y API/MCP/Keycloak healthy.
- Flujos reales observados: OAuth code exchange 200; tools/list descubre seis tools; consulta de inventario sin coincidencias devuelve lista vacía; escritura denegada; create/get/status lifecycle de incidencia vía MCP confirmado.
- El endpoint MCP y Keycloak necesitan puertos públicos temporales de Codespaces para clientes externos; el Inspector y el API deben permanecer privados. Cerrar los puertos públicos después del ejercicio.
