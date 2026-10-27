# Auditoría OWASP Top 10 — TrackFlow

- **Versión de referencia:** OWASP Top 10:2021.
- **Fecha de trabajo:** 2026-10-23.
- **Actualización de evidencia:** 2026-10-26.
- **Alcance declarado:** `services/api`, UIs (`uis/website`, `uis/backoffice`), agente LangGraph/RAG y MCP; además, Compose, reporting, telemetría y componentes auxiliares que forman parte del fork.
- **Advertencia:** auditoría inicial estática y pruebas locales, no pentest externo ni escaneo del servidor productivo. “No implementado” no significa “seguro”. Para el servidor, ver `server-hardening.es.md`.

## Inventario del alcance de IA

| Componente | Hallazgo de implementación en el fork | Responsable funcional propuesto |
|---|---|---|
| Agente CX/RAG | Implementado como agente de conocimiento LangGraph, `/knowledge/query`, chat WebSocket y tools MCP. No se encontró flujo de tracking de pedidos B2C por número de pedido en las rutas revisadas. | Ingeniería de plataforma / agente |
| Selección de carrier | Hay modelos y servicio de carriers/asignaciones; la existencia de un motor de recomendación con APIs externas no quedó demostrada en esta pasada. | Operaciones logísticas + backend |
| Aprobación automática de devoluciones | No se identificó motor de aprobación automática de devoluciones en el alcance de código revisado; no confundir las aprobaciones de RFP con devoluciones. | Operaciones + backend (si se implementa) |
| RAG de políticas/SLA por país | Hay documentos de conocimiento y agente RAG; aislamiento multi-tenant B2B de documentos no quedó demostrado. | Data/RAG + seguridad |

## Estado ejecutivo y fixes ya aplicados

| Hallazgo | Severidad inicial | Evidencia previa | Corrección aplicada | Evidencia posterior |
|---|---:|---|---|---|
| `/users` permitía lectura de usuarios con cualquier JWT; `PUT` solo impedía modificar a otros, pero permitía asignar `role=admin` al propio usuario; borrado sin autorización de rol. | Crítica (A01) | `services/api/src/routes/users_router.py`: funciones `get_users`, `get_user`, `put_user`, `remove_user` antes del cambio no aplicaban rol ADMIN; prueba manual reproducible: token de usuario normal contra `GET /users`, `PUT /users/{mi_id}` con `{"role":"admin"}`, `DELETE /users/{otro_id}`. | Admin requerido para listar/crear/borrar; usuario solo lee/actualiza su propia cuenta; cambio de rol restringido a admin. Registro público se preserva, el modelo no admite rol en payload y crea rol por defecto. | `python -m pytest services/api/tests/test_user_access_control.py -q` — cubre denegación a usuario normal, elevación de privilegio y administración por ADMIN. |
| JWT utilizaba una clave hardcodeada cuando `SECRET_KEY` faltaba. | Crítica (A02/A07) | `services/api/src/services/auth_service.py` antes devolvía `trackflow-dev-secret-key`, conocido por el código. | Se elimina fallback; `_get_secret_key()` falla cerrado si no está configurada la variable. | `python -m pytest services/api/tests/test_auth.py -q` prueba clave ausente/vacía y validación JWT. |
| Lecturas de inventario y órdenes no autenticadas; escrituras admitían cualquier usuario autenticado. | Alta (A01) | `services/api/src/routes/inventory.py`: rutas GET sin dependencia de usuario; writes requerían token pero no rol. | Todas las lecturas requieren autenticación; writes restringidos a ADMIN/MANAGER. | `python -m pytest services/api/tests/test_inventory_access_control.py services/api/tests/test_inventory.py -q`. |
| CORS wildcard y falta de cabeceras HTTP defensivas. | Alta (A05) | `services/api/src/fastapi_server.py` antes usaba `allow_origins=["*"]`. | CORS usa `CORS_ALLOWED_ORIGINS` (vacío por defecto; navegador cross-origin bloqueado salvo allowlist) con validación de origen absoluta; se añaden nosniff, frame denial, referrer, permissions y HSTS en HTTPS. Compose fija localhost para desarrollo. | `docker compose config --quiet`; verificación manual del middleware y validación con dominios reales pendientes. |

> Los comandos “antes” de arriba son reproducciones derivadas del estado anterior identificado en revisión estática; no se preservó un checkout/ejecución automática pre-fix. Para el sign-off final, el equipo debe ejecutar cada reproducción en una rama/commit base aislado si requiere artefacto automatizado comparativo.

## Reproducción de las correcciones (antes/después)

**Integridad de la evidencia:** los comandos de la columna “después” son verificaciones reproducibles contra el código corregido. No se ha ejecutado ni conservado una reproducción dinámica del estado vulnerable; por tanto, los pasos “antes” son procedimientos para repetir en una copia aislada, no resultados históricos ni evidencia ya obtenida. No probar el estado vulnerable contra producción ni contra datos reales.

### Preparar el estado anterior de forma segura

Identificar por revisión de historial el commit que contiene la versión vulnerable y crear una copia temporal. Sustituir `<SHA_VULNERABLE>` por un SHA verificado; no asumir que cualquier commit anterior es el estado vulnerable:

```sh
git log --oneline --all -- services/api/src/routes/users_router.py services/api/src/routes/inventory.py services/api/src/services/auth_service.py services/api/src/fastapi_server.py
git worktree add --detach /tmp/trackflow-owasp-before <SHA_VULNERABLE>
```

Levantar esa copia únicamente con configuración local, base de datos desechable y usuarios/datos ficticios. Guardar SHA, configuración sanitizada, comando, fecha y salida real. Al terminar:

```sh
git worktree remove /tmp/trackflow-owasp-before
```

No añadir como resultado una salida esperada. Si la prueba previa no se ejecutó, marcarla como “pendiente de ejecución”.

### Pruebas de autorización de usuarios — A01 (crítica)

**Antes (pendiente de ejecución):** contra la instancia local del worktree vulnerable, crear un usuario normal ficticio e intentar listar usuarios, elevar su propio rol y eliminar otro usuario ficticio. Por ejemplo, con tokens creados exclusivamente para esa instancia:

```sh
curl -i "$API_URL/users" -H "Authorization: Bearer $USER_JWT"
curl -i -X PUT "$API_URL/users/$USER_ID" \
	-H "Authorization: Bearer $USER_JWT" \
	-H 'Content-Type: application/json' -d '{"role":"admin"}'
curl -i -X DELETE "$API_URL/users/$OTHER_USER_ID" \
	-H "Authorization: Bearer $USER_JWT"
```

Registrar los códigos HTTP y el estado resultante de la base desechable. La vulnerabilidad descrita consistía en que esas operaciones carecían de las comprobaciones de rol/propiedad correspondientes; no se afirma aquí un código observado para una ejecución previa.

**Después (regresión automatizada):**

```sh
cd services/api && python -m pytest tests/test_user_access_control.py -q
```

Las aserciones verifican `403` a usuario normal al listar/leer a otro usuario, elevar su propio rol y borrar a otro; también comprueban la gestión permitida por ADMIN y que el registro público no asigne un rol privilegiado. Registrar el resultado real de pytest al ejecutar.

### Secreto de firma JWT — A02/A07 (crítica)

**Antes (pendiente de ejecución):** en el worktree vulnerable, con entorno de prueba aislado y sin `SECRET_KEY`, iniciar el proceso o invocar la generación/validación de JWT. Verificar si utiliza el fallback identificado en revisión estática. No imprimir ni conservar claves o tokens. No usar secretos reales.

**Después (regresión automatizada):**

```sh
cd services/api && python -m pytest tests/test_auth.py -k 'fallback_when_env_var' -q
```

Las pruebas comprueban que `_get_secret_key()` falla con `RuntimeError` cuando `SECRET_KEY` no está configurada o está vacía, en lugar de utilizar el secreto predeterminado conocido. Registrar el resultado real de pytest al ejecutar.

### Autenticación y roles de inventario — A01

**Antes (pendiente de ejecución):** desde la instancia vulnerable local y con datos desechables, consultar productos y órdenes sin token y probar una escritura con JWT de usuario normal. Registrar los códigos HTTP y no reutilizar esta prueba contra datos reales.

**Después (regresión automatizada):**

```sh
cd services/api && python -m pytest tests/test_inventory_access_control.py tests/test_inventory.py -q
```

Las pruebas de acceso verifican que las lecturas sin autenticación respondan `401` y que una escritura por un usuario sin rol suficiente responda `403`; las pruebas funcionales de inventario cubren el comportamiento permitido.

### CORS y cabeceras HTTP — A05

**Antes (pendiente de ejecución):** en una instancia vulnerable local, realizar un preflight desde un origen de prueba no confiable y guardar la respuesta. Esta solicitud es solo una señal del comportamiento CORS del servidor; no equivale por sí sola a una prueba completa desde navegador.

**Después (comprobación manual del servidor corregido):** levantar una instancia local con `CORS_ALLOWED_ORIGINS` definido a un origen de prueba permitido y establecer `API_URL` al servidor local. Revisar que el origen no permitido no reciba `Access-Control-Allow-Origin`; confirmar las cabeceras en la respuesta. Este procedimiento no es un test automatizado del repositorio:

```sh
export API_URL="http://127.0.0.1:8000"
curl -i -X OPTIONS "$API_URL/health" \
	-H 'Origin: https://origen-no-permitido.example' \
	-H 'Access-Control-Request-Method: GET'
curl -sSI "$API_URL/health" | grep -Ei \
	'X-Content-Type-Options|X-Frame-Options|Referrer-Policy|Permissions-Policy|Strict-Transport-Security'
```

Para comprobar HSTS debe usarse HTTPS en un entorno de prueba; la API lo añade solo cuando la solicitud se recibe con esquema HTTPS. Resultado de esta comprobación manual: **pendiente de registrar**. La configuración y sintaxis de Compose pueden verificarse por separado con `docker compose config --quiet`, lo que no demuestra CORS ni cabeceras en ejecución.

## Evaluación OWASP: backend

| Categoría | Resultado / hallazgo | Evidencia y estado |
|---|---|---|
| A01 Broken Access Control | **Aplica — crítica corregida** en administración de usuarios e inventario. | `services/api/src/routes/users_router.py` (`GET/POST/PUT/DELETE /users`), `services/api/src/routes/inventory.py` (`/inventory/products`, `/inventory/orders`); pruebas `test_user_access_control.py`, `test_inventory_access_control.py`. Tenant B2B general no probado/demostrado. |
| A02 Cryptographic Failures | **Aplica — crítica corregida**: clave JWT por defecto eliminada. TLS productivo no verificable desde el repo. | `services/api/src/services/auth_service.py::_get_secret_key`; `services/api/tests/test_auth.py`. `SECRET_KEY` debe estar en entorno/secrets y ser rotada si se usó default históricamente. |
| A03 Injection | **Aplica, sin crítico confirmado en esta revisión.** Consultas SQL observadas usan SQLModel expressions; CSV se procesa como archivo. | `services/api/src/routes/inventory.py`, `services/api/src/routes/incidents_fastapi_router.py`; confirmar con revisión completa de cada query y pruebas de payloads maliciosos. |
| A04 Insecure Design | **Aplica.** Hay decisiones de autorización por rol y un agente con tools; reglas de tenant/datos de cliente requieren validación de negocio adicional. | `services/api/src/agent/graph.py`, `services/api/src/agent/operational_tools.py`, routers de inventario/incidencias. No se confirmó motor de aprobación de devoluciones. |
| A05 Security Misconfiguration | **Aplica — alta corregida parcialmente.** CORS wildcard eliminado, cabeceras añadidas; deployment, TLS, debug, proxy y secretos deben validarse en entorno. | `services/api/src/fastapi_server.py`; Compose publica servicios de desarrollo, evidencia detallada en `server-hardening.es.md`. |
| A06 Vulnerable and Outdated Components | **Aplica — evaluación pendiente de escaneo completo.** Manifests contienen rangos de versiones y algunas imágenes usan `latest`. | `services/api/requirements.txt`, `mcps/Dockerfile` (`uv:latest`), `docker-compose.yml` (`redis:alpine`, `qdrant/qdrant:latest`). Resultado de escaneo no disponible aún. |
| A07 Identification and Authentication Failures | **Aplica.** JWT con fallback inseguro corregido; se debe evaluar rate limit de login/reset, expiración y gestión de sesiones. | `services/api/src/services/auth_service.py`, `services/api/src/routes/auth_router.py`; pruebas auth existentes. |
| A08 Software and Data Integrity Failures | **Aplica — evaluación parcial.** Hay lockfiles de algunos proyectos; no se acreditó verificación de artefactos/build provenance. | `mcps/uv.lock`, manifests npm y Dockerfiles; falta pipeline/SBOM/firmado reproducible documentado. |
| A09 Security Logging and Monitoring Failures | **Aplica — revisión parcial.** Hay logging de herramientas MCP y guardrails; se debe completar comprobación de redacción y retención de todo el backend. | `mcps/src/trackflow_mcp/server.py::ToolAuditMiddleware`, `services/api/src/agent/guardrails.py`; no registrar prompts/tokens. |
| A10 SSRF | **No se confirmó vulnerabilidad, categoría aplicable a revisar.** Esta revisión no completó un inventario de todos los destinos HTTP controlables por usuario. | `services/api/src/agent/` y clientes de integración; inspección completa y pruebas SSRF pendientes. |

## Evaluación OWASP: frontend

| Categoría | Resultado / hallazgo | Evidencia y estado |
|---|---|---|
| A01 | **Aplica.** El control visual de rutas no reemplaza ACL del API; se detectó además acceso anónimo a varias rutas de inventario antes de la corrección backend. | `uis/backoffice/app/components/auth/ProtectedRoute.tsx`; `services/api/src/routes/inventory.py` (backend fix ya aplicado). No se detectó interfaz específica B2B/tenant en el inventario actual. |
| A02 | **Aplica.** JWT del backoffice se guarda en `localStorage`, accesible a JS ante XSS. No hay evidencia de XSS explotable en la revisión inicial. | `uis/backoffice/services/authApi.ts` (`AUTH_TOKEN_STORAGE_KEY`, helpers de sesión); migrar a cookies HttpOnly/Secure/SameSite requeriría diseño. |
| A03 | **No se confirmó vulnerabilidad.** React escapa interpolaciones por defecto; falta revisión completa de sinks y entradas. | Revisar `uis/backoffice/app/**`, website y uso de `dangerouslySetInnerHTML`/HTML no confiable antes del cierre. |
| A04 | **Aplica.** Autenticación depende de cliente y API; evitar asumir que ocultar rutas controla permisos. | `uis/backoffice/app/components/AppShell.tsx`, `ProtectedRoute.tsx`, `services/authApi.ts`. |
| A05 | **Aplica — corrección backend complementaria.** Las respuestas API ganan cabeceras, pero no se ha probado política de headers en Next/proxy productivo. | `uis/website/next.config.ts`, `uis/backoffice/next.config.ts`; falta CSP/HSTS en el edge. |
| A06 | **Aplica — pendiente de escaneo.** | `uis/website/package.json`, `uis/backoffice/package.json` y lockfiles por confirmar/escaneo npm audit pendiente. |
| A07 | **Aplica.** Tokens en almacenamiento del navegador y controles client-side necesitan threat model; auth real se valida en API. | `uis/backoffice/services/authApi.ts`, `ProtectedRoute.tsx`. |
| A08 | **Aplica — parcial.** Instalación de dependencias/build debe verificarse y fijarse en pipeline productivo. | `uis/Dockerfile` instala mediante `npm install`; no se evidencia build de producción multi-stage (usa `next dev` en `uis/start.sh`). |
| A09 | **Aplica — parcial.** El frontend emite telemetría; confirmar exclusión de PII y sanitización de errores. | `uis/backoffice/lib/telemetry.ts`, `lib/instrumentation.ts`; pruebas de sanitización deben revisarse en suite correspondiente. |
| A10 | **No aplica directamente como servidor**, pero el frontend puede enviar URLs a backend; no se identificó un proxy de URL en UI revisada. | Confirmar cuando el inventario de endpoints SSRF del backend esté finalizado. |

## Evaluación OWASP: sistema agéntico (carril independiente)

| Categoría | Resultado / hallazgo | Evidencia y estado |
|---|---|---|
| A01 | **Aplica.** Nuevos gates por rol deniegan `USER` en RAG/chat e incidencias; lectura/mutación MCP requiere cuenta `SERVICE` explícita y los scopes OAuth por herramienta. No se confirmó autorización multi-tenant: operadores/servicios aún consultan datos globales. | `services/api/src/services/access_control.py`, `services/api/src/routes/{knowledge_router,chat_router,incidents_fastapi_router}.py`; tests `test_knowledge_router_agent.py`, `test_chat_websocket.py`, `test_incidents_authorization.py`. El acceso cruzado B2B por tenant sigue sin implementar/demostrar; los gates por rol no equivalen a aislamiento. |
| A02 | **Aplica.** Credenciales de servicio y API de modelos se cargan desde settings/env; no registrar valores. Transporte interno HTTP en Compose de desarrollo, no evidencia TLS productivo. | `mcps/src/trackflow_mcp/settings.py`, `docker-compose.yml`; `.env` ignorado por Git. Verificar secret manager y TLS externos. |
| A03 | **Aplica.** Prompt injection/data indirecta y salida del modelo son riesgos; guardrails locales cubren patrones, no son garantía de ACL. | `services/api/src/agent/guardrails.py`, `routing.py`, `nodes.py`; tests `services/api/tests/test_agent_guardrails.py`, `test_agent_tools.py`; límites están descritos en `memory-bank/progress.md`. |
| A04 | **Aplica.** Agente con tools y memoria; herramientas de escritura deben limitarse al alcance requerido y operaciones irreversibles a HITL. | `services/api/src/agent/operational_tools.py`; MCP `request_inventory_change` es deny-only según `mcps/src/trackflow_mcp/server.py`; no se encontró aprobación de devolución/carrier de alto impacto. |
| A05 | **Aplica.** Permisos dependen de scopes y composición; Compose expone MCP/Keycloak en host y los defaults de URL son HTTP para desarrollo. | `docker-compose.yml`, `mcps/src/trackflow_mcp/settings.py`, `mcps/src/trackflow_mcp/server.py`. Mantener MCP/OAuth privado tras proxy seguro en producción. |
| A06 | **Aplica.** Cadena de suministro de LangGraph/MCP/modelos requiere escaneo como backend. | `services/api/requirements.txt`, `mcps/pyproject.toml`, `mcps/uv.lock`; escaneo pendiente. |
| A07 | **Aplica.** MCP valida OAuth audience/scope; el agente obtiene credenciales de servicio. Auditar separación usuario↔credencial y expiración. | `mcps/src/trackflow_mcp/auth.py`, `server.py`, `services/api/src/agent/mcp_tools.py`; tests OAuth del agente/MCP. |
| A08 | **Aplica.** Resultados del modelo/RAG son datos no confiables; se documenta aislamiento y verificación de salidas, pero no hay firma/provenance del corpus demostrada. | `services/api/src/agent/nodes.py`, `rag_adapter.py`, `docs/rag/langgraph-agent.md`. |
| A09 | **Aplica.** Hay auditoría de herramienta sin texto conversacional y resumen de guardrails por usuario; retención multiworker limitada. | `mcps/src/trackflow_mcp/server.py::ToolAuditMiddleware`, `services/api/src/agent/guardrails.py`, `services/api/src/routes/knowledge_router.py`. |
| A10 | **Aplica a revisar.** El agente/MCP puede acceder a servicios internos configurados; no se encontró prueba de que un usuario controle el destino, pero debe confirmarse en clientes y tools. | `mcps/src/trackflow_mcp/api_client.py`, `services/api/src/agent/`; pruebas SSRF pendientes. |

## Pruebas y limitaciones

- Correcciones ejecutadas en esta rama: `python -m pytest services/api/tests/test_user_access_control.py services/api/tests/test_inventory_access_control.py services/api/tests/test_auth.py services/api/tests/test_inventory.py -q` — **155 passed** (ejecutado el 2026-10-26).
- `docker compose config --quiet` y `git diff --check` pasaron durante la implementación actual.
- Pendiente: escáner SCA/SAST, verificación real del host, scan externo autorizado, pruebas de CORS/security headers, revisión completa SSRF, validación de tenant B2B, token storage y dominios/HTTPS productivos.
- **Sign-off bloqueado** hasta cerrar pendientes críticos y verificar host/red en el entorno objetivo.

## Actualización de alcance y evidencia — 2026-10-27

- Inventario completo y responsabilidad compartida: `docs/security/ai-inventory.es.md`. Se deja constancia de que la búsqueda de pedido B2C, el aislamiento B2B general y la aprobación automática de devoluciones no quedaron demostrados en código; no se confunden con flujos de aprobación RFP.
- Se encontró un fallback de `SECRET_KEY` hardcodeado en `services/api/src/services/password_reset_service.py` (además del hallazgo previo en auth, ya corregido). Se eliminó: reset falla cerrado si no hay `SECRET_KEY`; prueba nueva en `services/api/tests/test_password_reset_secrets.py`.
- Se implementa limitador por usuario con Redis compartido en `POST /knowledge/query`: configuración `AGENT_RATE_LIMIT`/`AGENT_RATE_WINDOW_SECONDS`, respuestas 429 + `Retry-After`, 503 fail-closed si Redis falla. Código: `services/api/src/agent/rate_limit.py`; wiring en `fastapi_server.py`; `docker-compose.yml` establece 20/60s. La operación contra Redis real y despliegue quedan por verificar.
- Se incorporó validación NFC y rechazo de caracteres de control en el input de knowledge. Pruebas reproducibles de inyección directa bloqueada antes de cualquier clasificador, retrieval o generación añadidas a `services/api/tests/test_knowledge_router_agent.py`.
- Se amplió `.env.example` con variables de modelo/MCP/telemetría y Redis, sin valores de claves. `.env` está ignorado por Git; esto no acredita un escaneo exhaustivo del historial ni uso de vault en producción. El código de reset activo ya no contiene el fallback conocido; escaneo completo de secretos sigue pendiente.
- El agente persiste trazas estructuradas sin pregunta/respuesta; tests existentes `services/api/tests/test_agent_invocation.py` verifican decisiones/rutas/tool y omisión de ticket/datos sensibles. La durabilidad/alertado multiworker está pendiente.
- No se encontró un flujo de devolución automática ni gates implementados/demostrados para despacho de alto valor, cambio de carrier en tránsito o compartir datos entre tenants. Se requieren controles deterministas y confirmación humana autenticada antes de cualquier activación. Ver informe NIST para brechas y responsables.
