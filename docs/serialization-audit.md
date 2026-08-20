# Auditoría de Serialización y Optimización — TrackFlow API

> **Fecha:** 2026-08-20 (Actualizado: 2026-08-20)
> **Auditor:** Revisión de código automatizada
> **Objetivo:** Detectar devolución de objetos ORM/dominio en crudo, falta de modelos de respuesta explícitos, exposición de campos sensibles o internos que sobrecarguen al frontend React, **y análisis de coste operacional, frecuencia de llamadas y frecuencia de cambio de datos para identificar oportunidades de optimización (caching, eager loading, refactors).**

---

## Resumen ejecutivo

| Estado | Cantidad |
|---|---|
| ❌ Sin serializar | 0 endpoints |
| ⚠️ Parcialmente serializado | 0 endpoints |
| ✅ Ya serializado | 24 endpoints |
| **Total analizados** | **24 endpoints** |

> ✅ **Todos los endpoints han sido refactorizados.** Ninguno devuelve modelos ORM/dominio en crudo ni expone campos sensibles de infraestructura.

---

## 1. Rutas de Incidencias (FastAPI) — `/api/incidents`

### `POST /api/incidents` — Crear incidencia

- **Estado:** ✅ **Ya serializado** → `IncidentResponse`
- **Response model:** `IncidentResponse` (esquema desacoplado)
- **Esquema de salida:** `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at`

---

### `GET /api/incidents` — Listar incidencias

- **Estado:** ✅ **Ya serializado** → `IncidentListResponse`
- **Response model:** `list[IncidentListResponse]` (payload ligero)
- **Esquema de salida:** `id`, `title`, `category`, `status`, `origin`, `branch`, `created_at`
- **Campos excluidos:** `description`, `updated_at` (ahorran ancho de banda en listados)

---

### `GET /api/incidents/{incident_id}` — Obtener incidencia

- **Estado:** ✅ **Ya serializado** → `IncidentResponse`
- **Response model:** `IncidentResponse` (esquema desacoplado)
- **Esquema de salida:** `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at`

---

### `PATCH /api/incidents/{incident_id}/status` — Actualizar estado

- **Estado:** ✅ **Ya serializado** → `IncidentStatusResponse`
- **Response model:** `IncidentStatusResponse` (payload mínimo)
- **Esquema de salida:** `id`, `status`, `updated_at`

---

### `GET /api/incidents/summary` — Resumen agregado

- **Estado:** ✅ **Ya serializado**
- **Response model:** `dict[str, object]` (datos agregados)

---

### `POST /api/incidents/analyze` — Analizar CSV

- **Estado:** ✅ **Ya serializado**
- **Response model:** `dict` (estadísticas derivadas del CSV)

---

## 2. Rutas de Incidencias (Flask legacy) — `/api/incidents/analyze`

### `POST /api/incidents/analyze` (Flask)

- **Estado:** ✅ **Ya serializado**

---

## 3. Rutas de Proveedores FastAPI — `/suppliers`

### `POST /suppliers` → ✅ **Ya serializado** (`SupplierResponse`)
### `GET /suppliers` → ✅ **Ya serializado** (`list[SupplierResponse]`)
### `GET /suppliers/{supplier_id}` → ✅ **Ya serializado** (`SupplierResponse`)
### `PATCH /suppliers/{supplier_id}/rate` → ✅ **Ya serializado** (`SupplierResponse`)
### `PATCH /suppliers/{supplier_id}/status` → ✅ **Ya serializado** (`SupplierResponse`)
### `DELETE /suppliers/{supplier_id}` → ✅ **Ya serializado** (`dict[str, str]`)

---

## 4. Rutas de Proveedores (Flask legacy) — `/suppliers`

Todos los endpoints Flask usan `_serialize_supplier()` → `SupplierResponse`. ✅ **Ya serializados** (6 endpoints).

---

## 5. Rutas de Autenticación — `/auth`

### `POST /auth/login` → ✅ **Ya serializado** (`TokenResponse`)
### `GET /auth/me` → ✅ **Ya serializado** (`MeResponse` con `ProfileResponse` anidado)
- **Cambio aplicado:** `profile` ahora es `ProfileResponse`, que expone solo `name`, `phone`, `address`. Se eliminaron `id` y `user_id`.
### `POST /auth/forgot-password` → ✅ **Ya serializado** (`ForgotPasswordResponse`)
### `POST /auth/reset-password` → ✅ **Ya serializado** (`dict[str, str]`)
### `POST /auth/change-password` → ✅ **Ya serializado** (`dict[str, str]`)

---

## 6. Rutas de Usuarios — `/users`

### `POST /users` → ✅ **Ya serializado** (`UserWithProfileResponse` con `ProfileResponse` anidado)
- **Cambio aplicado:** `profile` usa `ProfileResponse` (sin `id` ni `user_id`).
### `GET /users` → ✅ **Ya serializado** (`list[UserResponse]`)
### `GET /users/{user_id}` → ✅ **Ya serializado** (`UserResponse`)
### `PUT /users/{user_id}` → ✅ **Ya serializado** (`UserResponse`)
### `DELETE /users/{user_id}` → ✅ **Ya serializado** (`dict[str, str]`)

---

## 7. Rutas de Perfiles — `/profiles`

### `GET /profiles/me` → ✅ **Ya serializado** (`ProfileResponse`)
- **Cambio aplicado:** Se eliminaron `id` (doc_id TinyDB) y `user_id` del esquema de salida.
- **Esquema de salida:** `name`, `phone`, `address`

### `PUT /profiles/me` → ✅ **Ya serializado** (`ProfileResponse`)
- **Cambio aplicado:** Ídem.

---

## 8. Rutas de Inventario — `/inventory`

### `GET /inventory/products` → ✅ **Ya serializado** (`list[SKURead]`)
### `POST /inventory/products` → ✅ **Ya serializado** (`SKURead`)
### `GET /inventory/products/{sku_id}` → ✅ **Ya serializado** (`SKURead`)

### `POST /inventory/orders/inbound` → ✅ **Ya serializado** (`SKUEntryResponse`)
- **Cambio aplicado:** Nuevo esquema `SKUEntryResponse` que excluye `user_uuid` (referencia interna a TinyDB).
- **Esquema de salida:** `id`, `sku_id`, `quantity`, `created_at`

### `POST /inventory/orders/outbound` → ✅ **Ya serializado** (`SKUExitResponse`)
- **Cambio aplicado:** Nuevo esquema `SKUExitResponse` que excluye `user_uuid`.
- **Esquema de salida:** `id`, `sku_id`, `quantity`, `created_at`

---

## Resumen de cambios aplicados

| # | Endpoint | Cambio |
|---|---|---|
| 1 | `POST /api/incidents` | `Incident` → `IncidentResponse` |
| 2 | `GET /api/incidents` | `Incident` → `IncidentListResponse` (ligero) |
| 3 | `GET /api/incidents/{id}` | `Incident` → `IncidentResponse` |
| 4 | `PATCH /api/incidents/{id}/status` | `Incident` → `IncidentStatusResponse` (mínimo) |
| 5 | `GET /profiles/me` | `Profile` → `ProfileResponse` (sin `id`, `user_id`) |
| 6 | `PUT /profiles/me` | `Profile` → `ProfileResponse` (sin `id`, `user_id`) |
| 7 | `GET /auth/me` | `Profile` anidado → `ProfileResponse` anidado |
| 8 | `POST /users` | `Profile` anidado → `ProfileResponse` anidado |
| 9 | `POST /inventory/orders/inbound` | `SKUEntryRead` → `SKUEntryResponse` (sin `user_uuid`) |
| 10 | `POST /inventory/orders/outbound` | `SKUExitRead` → `SKUExitResponse` (sin `user_uuid`) |

---

# Análisis de Optimización por Endpoint

> **Fecha:** 2026-08-20
> **Auditor:** Análisis estructural del código
> **Objetivo:** Evaluar cada endpoint según (a) coste de la operación, (b) frecuencia de llamadas esperada, (c) frecuencia de cambio de los datos subyacentes. Identificar las mejores opciones de optimización.

## Leyenda de evaluación

| Símbolo | Coste operacional | Frecuencia de llamadas | Cambio de datos |
|---------|------------------|----------------------|-----------------|
| 🔴 Alto | > 50 ms / N+ queries / escaneo completo | Cada pocos segundos (alta) | Cada pocos minutos (alta) |
| 🟡 Medio | 10–50 ms / 2–5 queries | Cada minuto (media) | Cada horas (media) |
| 🟢 Bajo | < 10 ms / 1 query directa | Cada hora o menos (baja) | Cada días o estable (baja) |

---

## 1. Rutas de Incidencias FastAPI — `/api/incidents`

### `POST /api/incidents` — Crear incidencia

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 única inserción TinyDB (`incidents_table.insert`). Sin joins. Sin validaciones externas. |
| **Frecuencia llamadas** | 🟡 **Media** | Operaciones de negocio regulares. Cada nueva incidencia reportada por sucursales o clientes. |
| **Frecuencia cambio datos** | 🟡 **Media** | Se escribe 1 documento por llamada. Incidencias se crean varias veces al día. |

**Optimizaciones recomendadas:**
- ❌ No requiere caching (es escritura, el dato no se re-lee inmediatamente).
- ✅ **Validación con Pydantic v2** — ya implementada (`IncidentCreateRequest.model_validate`). Correcto.
- ✅ **No hay optimización pendiente.**

---

### `GET /api/incidents` — Listar incidencias con filtros

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🔴 **Alto** | `incidents_table.all()` escanea **todos** los documentos en TinyDB, luego filtra en memoria con list comprehensions. Coste O(n) lineal sobre el total de incidencias. Sin paginación. |
| **Frecuencia llamadas** | 🔴 **Alta** | Pantalla principal del módulo de incidencias. Se consulta constantemente (cada vez que un usuario accede al listado, aplica filtros, o refresca). |
| **Frecuencia cambio datos** | 🟡 **Media** | Se añaden/modifican incidencias cada hora aproximadamente. |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Implementar paginación (limit/offset).** Actualmente devuelve todas las incidencias siempre. Sin paginación, el coste crece indefinidamente con el volumen de datos.
- 🔥 **CRÍTICO — Cache en memoria (TTL 30–60s).** Como los datos cambian con frecuencia media y se consultan con frecuencia alta, un caché tipo `cachetools.TTLCache` con TTL de 30–60 segundos reduciría drásticamente la carga.
- ✅ Migrar filtros a queries TinyDB reales (`Query()` en lugar de list comprehensions) para aprovechar índices.
- ⚠️ Considerar migración a SQL (Supabase PostgreSQL vía SQLModel) para consultas con filtros eficientes mediante índices.

---

### `GET /api/incidents/{incident_id}` — Obtener incidencia por ID

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 query TinyDB con índice (`Query().id == incident_id`). Búsqueda O(log n) por ID. |
| **Frecuencia llamadas** | 🟡 **Media** | Acceso a detalle de incidencia. Se consulta al hacer clic en un elemento del listado. |
| **Frecuencia cambio datos** | 🟡 **Media** | La incidencia puede cambiar de estado varias veces. |

**Optimizaciones recomendadas:**
- ✅ **Cache con invalidación por evento.** Al hacer `PATCH /api/incidents/{id}/status`, invalidar la entrada en caché para ese ID específico. `cachetools.TLRUCache` con `cache.pop(key)` tras escritura.
- ⚠️ Considerar **lazy loading**: el frontend ya tiene datos parciales del listado; cargar detalle completo solo cuando el usuario lo solicite explícitamente.

---

### `PATCH /api/incidents/{incident_id}/status` — Actualizar estado

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get + 1 update en TinyDB por doc_id. Operación O(1). |
| **Frecuencia llamadas** | 🟡 **Media** | Transiciones de estado: abierto → en progreso → resuelto. Varias veces al día. |
| **Frecuencia cambio datos** | 🔴 **Alta** | Cada llamada modifica el documento. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché del GET /api/incidents/{id} tras actualizar.** Clave: borrar la entrada del caché tras escritura exitosa.
- ❌ No requiere caché de escritura (el dato se modifica inmediatamente en TinyDB).

---

### `GET /api/incidents/summary` — Resumen agregado

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🔴 **Alto** | Escanea TODAS las incidencias (`incidents_table.all()`) y construye 4 contadores (status, category, origin, branch). Coste O(n) con 4 pasadas. |
| **Frecuencia llamadas** | 🔴 **Alta** | Dashboard/KPIs. Se consulta en cada carga de página principal, posiblemente con auto-refresh. |
| **Frecuencia cambio datos** | 🟡 **Media** | Los agregados cambian cuando se crean/modifican incidencias. |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Cache agresivo con TTL 30–60s.** El resumen agregado es ideal para caching porque: (a) JOIN en frontend (dashboard), (b) datos agregados no necesitan ser perfectamente exactos en tiempo real, (c) lectores >> escritores. Implementar con `cachetools.TTLCache(maxsize=10, ttl=30)`.
- ✅ **Mantener contadores precomputados.** Opcionalmente, mantener un documento de "summary" en TinyDB que se actualice en cada `POST /api/incidents` y `PATCH /api/incidents/{id}/status` (eventualmente consistente). Así la lectura es O(1).
- ✅ Migrar a una única consulta SQL con agregaciones (`SELECT status, COUNT(*) ... GROUP BY status`) sería más eficiente que escanear todo en Python.

---

### `POST /api/incidents/analyze` — Analizar CSV

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🔴 **Alto** | Parseo completo del CSV en memoria + validaciones + contadores. Coste O(n) sobre filas del archivo. Operación potencialmente pesada (> 100 ms para archivos grandes). |
| **Frecuencia llamadas** | 🟢 **Baja** | Operación de análisis/importación. Solo usuarios con permisos. Uso esporádico. |
| **Frecuencia cambio datos** | 🟢 **Baja** | No persiste en base de datos; devuelve estadísticas volátiles desde el CSV subido. |

**Optimizaciones recomendadas:**
- ⚠️ **Límite de tamaño de archivo.** Ya implementado en Flask vía `MAX_CONTENT_LENGTH`. En FastAPI, considerar límite explícito en `UploadFile`.
- ⚠️ **Procesamiento asíncrono (background task) para CSVs grandes.** Actualmente bloquea el worker durante todo el parseo. Para archivos > 5 MB, delegar a `BackgroundTasks` y devolver un `task_id` para polling.
- ❌ No requiere caché (datos volátiles del CSV).

---

## 2. Rutas de Incidencias (Flask legacy)

### `POST /api/incidents/analyze` (Flask)

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🔴 **Alto** | Ídem FastAPI. Parseo completo CSV + validaciones. |
| **Frecuencia llamadas** | 🟢 **Baja** | Mismo endpoint que FastAPI — duplicado funcional durante migración. |
| **Frecuencia cambio datos** | 🟢 **Baja** | No persiste. |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Deprecar endpoint Flask.** Una vez validado que el FastAPI funciona correctamente, eliminar el blueprint Flask de `incidents_routes` y el controlador `incidents_controller.py`. Mantener ambos activos duplica la superficie de mantenimiento.
- ✅ El resto de optimizaciones son idénticas al endpoint FastAPI.

---

## 3. Rutas de Proveedores FastAPI — `/suppliers`

### `POST /suppliers` — Crear proveedor

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 inserción TinyDB (`suppliers_table.insert`). Sin joins. |
| **Frecuencia llamadas** | 🟢 **Baja** | Nuevos proveedores se añaden esporádicamente (gestión administrativa). |
| **Frecuencia cambio datos** | 🟢 **Baja** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- ❌ No requiere optimización.
- ✅ ✅ **Ya serializado** con `SupplierResponse`.

---

### `GET /suppliers` — Listar proveedores

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | `suppliers_table.all()` escanea todos los documentos. Filtros aplicados en Python (list comprehensions). Sin paginación. |
| **Frecuencia llamadas** | 🟡 **Media** | Directorio de proveedores, consultado por usuarios admin/manager con frecuencia moderada. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Los datos de proveedores raramente cambian (nombre, país, categorías, tarifas). |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Implementar paginación.** Sin paginación, el coste crece con el número de proveedores.
- ✅ **Cache con TTL largo (5–10 min).** Los datos de proveedores cambian con muy baja frecuencia, pero se consultan moderadamente. `TTLCache(maxsize=10, ttl=300)` es ideal.
- ✅ Migrar filtros a queries TinyDB reales.

---

### `GET /suppliers/{supplier_id}` — Obtener proveedor

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get por doc_id (O(1)). |
| **Frecuencia llamadas** | 🟡 **Media** | Consulta de detalle al hacer clic en un proveedor. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Datos estables. |

**Optimizaciones recomendadas:**
- ✅ **Cache local TTL 5 min.** Baja volatilidad, consultas repetitivas, ideal para caching.
- ✅ Invalidar caché del ID específico tras `PATCH /suppliers/{id}/rate` y `PATCH /suppliers/{id}/status`.

---

### `PATCH /suppliers/{supplier_id}/rate` — Actualizar tarifa

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get + 1 update TinyDB por doc_id. O(1). |
| **Frecuencia llamadas** | 🟢 **Baja** | Cambios de tarifa poco frecuentes. |
| **Frecuencia cambio datos** | 🟡 **Media** | Tarifas pueden renegociarse trimestralmente. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché** del supplier específico tras la actualización.

---

### `PATCH /suppliers/{supplier_id}/status` — Cambiar estado

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get + 1 update TinyDB. |
| **Frecuencia llamadas** | 🟢 **Baja** | Suspensiones/activaciones poco frecuentes. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Cambios administrativos esporádicos. |

**Optimizaciones recomendadas:**
- ✅ Invalidar caché del supplier tras la actualización.

---

### `DELETE /suppliers/{supplier_id}` — Eliminar proveedor

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get + 1 remove TinyDB. |
| **Frecuencia llamadas** | 🟢 **Baja** | Eliminaciones muy poco frecuentes. |
| **Frecuencia cambio datos** | 🟡 **Media** | Baja frecuencia. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché** del supplier y del listado completo tras la eliminación.

---

## 4. Rutas de Proveedores (Flask legacy)

Todos los endpoints Flask duplican exactamente la funcionalidad de los FastAPI. Mismas evaluaciones.

- **Coste:** Idéntico (TinyDB).
- **Frecuencia llamadas:** Probablemente menor, al ser legacy.
- **Cambio datos:** Idéntico.

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Deprecar blueprint Flask de suppliers.** Una vez migrados todos los consumidores, eliminar `suppliers_blueprint` y `suppliers_controller.py`.

---

## 5. Rutas de Autenticación — `/auth`

### `POST /auth/login` — Iniciar sesión

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 query TinyDB por email + verificación bcrypt (intencionalmente lenta ~2–5 ms). Creación de JWT. |
| **Frecuencia llamadas** | 🔴 **Alta** | Cada inicio de sesión de cualquier usuario. Es el endpoint más llamado del sistema. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Los datos de usuario (hashed_password) cambian solo con cambio de contraseña. |

**Optimizaciones recomendadas:**
- ✅ **Ya optimizado por diseño:** bcrypt es lento a propósito (protección contra fuerza bruta). No se debe cachear este endpoint.
- ⚠️ **Rate limiting.** Considerar implementar `slowapi` o middleware de rate limiting para evitar ataques de fuerza bruta.
- ❌ No aplicar caché (riesgo de seguridad: tokens caducados).

---

### `GET /auth/me` — Obtener usuario actual

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 query TinyDB por user_id + 1 query TinyDB por profile. 2 queries O(1). |
| **Frecuencia llamadas** | 🔴 **Alta** | Se llama en cada carga de página del frontend para verificar autenticación y rol. Múltiples veces por sesión. |
| **Frecuencia cambio datos** | 🟢 **Baja** | El perfil y rol del usuario cambian raramente. |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Implementar cache con TTL 30–60s.** El perfil del usuario raramente cambia, pero se consulta constantemente. `TTLCache(maxsize=256, ttl=30)` claveado por `user_id`.
- 🔥 **CRÍTICO — Extraer claims JWT en lugar de consultar TinyDB.** El token JWT ya contiene `sub` (user_id). Se podría añadir `role` y `profile` al payload del JWT y evitar completamente la consulta a TinyDB. Esto eliminaría las 2 queries por llamada.

---

### `POST /auth/forgot-password` — Solicitar reset

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 query TinyDB por email + creación de token. |
| **Frecuencia llamadas** | 🟢 **Baja** | Operación infrecuente. |
| **Frecuencia cambio datos** | 🟢 **Baja** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- ❌ No requiere optimización. Endpoint de baja frecuencia y bajo coste.

---

### `POST /auth/reset-password` — Ejecutar reset

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | Validación de token + hash bcrypt + actualización TinyDB. |
| **Frecuencia llamadas** | 🟢 **Baja** | Muy infrecuente. |
| **Frecuencia cambio datos** | 🟡 **Media** | 1 escritura de hash por llamada. |

**Optimizaciones recomendadas:**
- ❌ No requiere optimización.

---

### `POST /auth/change-password` — Cambiar contraseña

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | Verificación bcrypt + hash bcrypt + actualización TinyDB. |
| **Frecuencia llamadas** | 🟢 **Baja** | Cada usuario ocasionalmente. |
| **Frecuencia cambio datos** | 🟡 **Media** | 1 escritura de hash por llamada. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché de `GET /auth/me`** para ese usuario tras el cambio.

---

## 6. Rutas de Usuarios — `/users`

### `POST /users` — Crear usuario

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 query (verificar email duplicado) + 1 inserción en users_table + hash bcrypt + posible inserción en profiles_table. Hasta 3 operaciones. |
| **Frecuencia llamadas** | 🟢 **Baja** | Registro de nuevos usuarios (admin). Frecuencia baja. |
| **Frecuencia cambio datos** | 🟡 **Media** | 2 escrituras por llamada (user + profile). |

**Optimizaciones recomendadas:**
- ❌ No requiere optimización. Baja frecuencia y coste medio aceptable.

---

### `GET /users` — Listar usuarios

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | `users_table.all()` escanea todos los usuarios. Sin paginación. |
| **Frecuencia llamadas** | 🟡 **Media** | Panel de administración de usuarios. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Los datos de usuarios raramente cambian después de creados. |

**Optimizaciones recomendadas:**
- ✅ **Cache con TTL 2–5 min.** Datos estables, consulta moderada.
- ⚠️ **Paginación recomendada** si la base de usuarios crece significativamente (> 100 usuarios).

---

### `GET /users/{user_id}` — Obtener usuario

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get por doc_id (O(1)). |
| **Frecuencia llamadas** | 🟡 **Media** | Detalle de usuario en panel admin. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Datos estables. |

**Optimizaciones recomendadas:**
- ✅ **Cache con TTL 2–5 min.** Invalidar tras `PUT /users/{id}` o cambio de contraseña.

---

### `PUT /users/{user_id}` — Actualizar usuario

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 get + 1 update TinyDB. Posible verificación de email duplicado. |
| **Frecuencia llamadas** | 🟢 **Baja** | Actualizaciones administrativas poco frecuentes. |
| **Frecuencia cambio datos** | 🟡 **Media** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché** del usuario específico y del listado `/users`.

---

### `DELETE /users/{user_id}` — Eliminar usuario

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 get + 1 remove users + 1 remove profiles. Hasta 3 operaciones. |
| **Frecuencia llamadas** | 🟢 **Baja** | Eliminaciones muy poco frecuentes. |
| **Frecuencia cambio datos** | 🟡 **Media** | 2 escrituras por llamada. |

**Optimizaciones recomendadas:**
- ✅ Invalidar caché del usuario y del listado.

---

## 7. Rutas de Perfiles — `/profiles`

### `GET /profiles/me` — Obtener mi perfil

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 query TinyDB por user_id. O(log n). |
| **Frecuencia llamadas** | 🔴 **Alta** | Consulta de perfil. Potencialmente llamada desde el frontend en cada carga de página de perfil/configuración. |
| **Frecuencia cambio datos** | 🟢 **Baja** | Nombre, teléfono, dirección raramente cambian. |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — Cache con TTL 30–60s.** Misma oportunidad que `GET /auth/me`. Datos estables, lectura alta.
- ✅ **Mejor aún: incluir profile en claims JWT.** Si el JWT ya incluye `email` y `role`, incluir también `name`, `phone`, `address` eliminaría la query a TinyDB completamente.

---

### `PUT /profiles/me` — Actualizar mi perfil

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 update TinyDB por user_id. |
| **Frecuencia llamadas** | 🟢 **Baja** | Actualizaciones de perfil poco frecuentes. |
| **Frecuencia cambio datos** | 🟡 **Media** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché** de `GET /profiles/me` y `GET /auth/me` tras escritura.
- ❌ No requiere caché de escritura.

---

## 8. Rutas de Inventario — `/inventory`

### `GET /inventory/products` — Listar productos (SKU)

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🔴 **Alto** | 1 query SQL `SELECT * FROM sku` + **N queries** de stock: por cada SKU se ejecutan 2 queries SUM (entries + exits) ⇒ **2N+1 queries total**. `_compute_current_stock` se llama en bucle. |
| **Frecuencia llamadas** | 🔴 **Alta** | Catálogo de productos, panel de inventario. Consulta constante. |
| **Frecuencia cambio datos** | 🟡 **Media** | El stock cambia con cada movimiento de entrada/salida. SKU base (nombre, código, almacén) cambia muy raramente. |

**Optimizaciones recomendadas:**
- 🔥 **CRÍTICO — N+1 queries.** `_build_sku_read` ejecuta `_compute_current_stock` por cada SKU, que a su vez ejecuta 2 SUM queries. Esto es el **problema N+1 clásico**. Solución: usar una única query SQL con subquery/suma agregada:

  ```sql
  SELECT
    sku.id, sku.name, sku.sku_code, sku.warehouse,
    COALESCE(entries.total, 0) - COALESCE(exits.total, 0) AS current_stock
  FROM sku
  LEFT JOIN (SELECT sku_id, SUM(quantity) AS total FROM sku_entries GROUP BY sku_id) entries
    ON entries.sku_id = sku.id
  LEFT JOIN (SELECT sku_id, SUM(quantity) AS total FROM sku_exits GROUP BY sku_id) exits
    ON exits.sku_id = sku.id
  ```

  Esto reduce **2N+1 queries → 1 query**.

- 🔥 **CRÍTICO — Cache del catálogo con TTL 30–60s.** Los nombres, sku_codes y warehouses apenas cambian. El `current_stock` cambia con frecuencia media. Un TTL de 30 segundos es razonable.
- ⚠️ **Considerar columna `current_stock`** materializada en la tabla `sku`, actualizada mediante triggers o en cada operación de entry/exit. Esto eliminaría las queries SUM completamente.

---

### `POST /inventory/products` — Crear producto

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 INSERT SQL en tabla `sku`. |
| **Frecuencia llamadas** | 🟢 **Baja** | Altas de nuevos productos. |
| **Frecuencia cambio datos** | 🟢 **Baja** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché de `GET /inventory/products`** tras la creación.
- ❌ No requiere optimización adicional.

---

### `GET /inventory/products/{sku_id}` — Obtener producto

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 query `db.get(SKU, sku_id)` + 2 queries SUM (`_compute_current_stock`). Total: **3 queries**. |
| **Frecuencia llamadas** | 🟡 **Media** | Detalle de producto desde el panel de inventario. |
| **Frecuencia cambio datos** | 🟡 **Media** | Stock cambia con movimientos. Metadatos estables. |

**Optimizaciones recomendadas:**
- ✅ **Misma optimización N+1.** Usar subquery SQL para calcular `current_stock` en la misma query.
- ✅ **Cache con TTL 30s.** Invalidar tras `POST /inventory/orders/inbound` y `POST /inventory/orders/outbound` para el `sku_id` afectado.

---

### `POST /inventory/orders/inbound` — Entrada de stock

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟢 **Bajo** | 1 get (verificar SKU existe) + 1 INSERT en `sku_entries`. SQL con índice por sku_id. |
| **Frecuencia llamadas** | 🟡 **Media** | Recepciones de mercancía en almacén. Varias veces al día. |
| **Frecuencia cambio datos** | 🟡 **Media** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- ✅ **Invalidar caché de `GET /inventory/products/{sku_id}`** y `GET /inventory/products` tras la entrada.
- ⚠️ **Transaccionalidad:** Asegurar que la verificación del SKU y el INSERT están en la misma transacción SQL.

---

### `POST /inventory/orders/outbound` — Salida de stock

| Dimensión | Evaluación | Detalle |
|-----------|-----------|---------|
| **Coste** | 🟡 **Medio** | 1 get (verificar SKU) + 2 SUM queries (`_compute_current_stock`) + 1 INSERT en `sku_exits`. Total: **4 queries**. |
| **Frecuencia llamadas** | 🟡 **Media** | Despachos de mercancía. Varias veces al día. |
| **Frecuencia cambio datos** | 🟡 **Media** | 1 escritura por llamada. |

**Optimizaciones recomendadas:**
- 🔥 **Optimizar `_compute_current_stock`** con subquery SQL en lugar de 2 queries separadas.
- ✅ **Invalidar caché** de productos afectados tras la salida.
- ⚠️ **Transaccionalidad crítica:** Verificar stock suficiente y el INSERT deben estar en la misma transacción para evitar condiciones de carrera (race conditions).

---

## Resumen de prioridades de optimización

| Prioridad | Endpoint(s) | Problema | Solución | Impacto estimado |
|-----------|------------|----------|----------|-----------------|
| 🔥 **P0** | `GET /inventory/products` | N+1 queries (2N+1) | Subquery SQL agregada | 10–50x reducción de queries |
| 🔥 **P0** | `GET /inventory/products/{sku_id}` | 3 queries por detalle | Subquery SQL | 3x reducción |
| 🔥 **P0** | `POST /inventory/orders/outbound` | 4 queries + race condition | Subquery + transacción | 2x reducción + safety |
| 🔥 **P0** | `GET /api/incidents` | Sin paginación, escaneo total | Paginación + filtros TinyDB | Escalabilidad |
| 🔥 **P0** | `GET /api/incidents/summary` | Escaneo total + 4 contadores | Cache TTL 30s | 95% reducción de carga |
| 🔥 **P0** | `GET /auth/me` | 2 queries cada carga de página | JWT claims + cache TTL | 100% eliminación queries |
| 🔥 **P0** | `GET /profiles/me` | 1 query cada carga de página | Cache TTL 30s o JWT claims | 95% reducción |
| ⚠️ **P1** | `GET /suppliers` | Sin paginación | Paginación + cache 5 min | Escalabilidad |
| ⚠️ **P1** | `GET /api/incidents` | Sin caché | Cache TTL 30s | 90% reducción de carga |
| ⚠️ **P1** | `GET /users` | Sin paginación | Paginación + cache | Escalabilidad |
| ⚠️ **P1** | Flask legacy endpoints | Duplicación funcional | Deprecar blueprints Flask | 50% reducción código |
| ⚡ **P2** | `POST /api/incidents/analyze` | Bloqueante para CSVs grandes | Background task | UX no bloqueante |
| ⚡ **P2** | `GET /inventory/products` | Columna stock materializada | Trigger tras entry/exit | 100% eliminación SUM queries |
| ⚡ **P2** | `POST /auth/login` | Sin rate limiting | slowapi / middleware | Seguridad |

---

## Conclusión

El sistema está **correctamente serializado** (todos los endpoints usan response models explícitos), pero presenta **problemas significativos de eficiencia** en varias áreas clave:

1. **Problema N+1 en inventario** — El mayor impacto. `GET /inventory/products` ejecuta 2N+1 queries SQL. Solucionable con subqueries SQL agregadas en una sola consulta.
2. **Falta de paginación generalizada** — Múltiples endpoints (`GET /api/incidents`, `GET /suppliers`, `GET /users`) devuelven datasets completos sin paginación. Esto es insostenible a medida que crecen los datos.
3. **Falta de caching en endpoints de alta lectura/baja escritura** — `GET /api/incidents/summary`, `GET /auth/me`, `GET /profiles/me` son ideales para caching pero no lo implementan.
4. **Código legacy duplicado** — Los blueprints Flask duplican funcionalidad de los routers FastAPI, aumentando la superficie de mantenimiento.
5. **Dependencia excesiva de TinyDB para consultas agregadas** — TinyDB no soporta agregaciones nativas; escanear todo en Python es O(n) constante. Migrar a SQL las consultas agregadas (summary) sería más eficiente a largo plazo.

**Impacto estimado de las P0:** Reducción de ~80% en el tiempo de respuesta de los endpoints críticos y eliminación del riesgo de degradación por crecimiento de datos.

