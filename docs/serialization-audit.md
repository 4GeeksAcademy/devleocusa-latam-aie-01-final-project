# Auditoría de Serialización — TrackFlow API

> **Fecha:** 2026-08-20 (Actualizado: 2026-08-20)
> **Auditor:** Revisión de código automatizada
> **Objetivo:** Detectar devolución de objetos ORM/dominio en crudo, falta de modelos de respuesta explícitos y exposición de campos sensibles o internos que sobrecarguen al frontend React.

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

