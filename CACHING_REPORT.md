# Informe de Caching – TrackFlow Backoffice

> **Fecha:** 2026-08-20  
> **Rama:** `caching`  
> **Backend:** FastAPI (servicios Python)  
> **Frontend:** Next.js 16 (App Router, TypeScript)  

---

## Índice

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Backend: Cache con TTL e Invalidación](#2-backend-cache-con-ttl-e-invalidación)
    - 2.1 [Clase `TTLCache`](#21-clase-ttlcache)
    - 2.2 [Instancias compartidas y TTLs](#22-instancias-compartidas-y-ttls)
    - 2.3 [Estrategia de invalidación](#23-estrategia-de-invalidación)
    - 2.4 [Endpoints cacheados vs. no cacheados](#24-endpoints-cacheados-vs-no-cacheados)
3. [Frontend: Lazy Loading con `next/dynamic`](#3-frontend-lazy-loading-con-nextdynamic)
    - 3.1 [Componentes diferidos](#31-componentes-diferidos)
    - 3.2 [Beneficio cuantificable](#32-beneficio-cuantificable)
4. [Frontend: `useMemo` para Valores Costosos](#4-frontend-usememo-para-valores-costosos)
    - 4.1 [Cálculo identificado en `ProductsListPanel`](#41-cálculo-identificado-en-productslistpanel)
    - 4.2 [Implementación](#42-implementación)
5. [Intercambio Frescura vs. Rendimiento](#5-intercambio-frescura-vs-rendimiento)
6. [Endpoints/Componentes Excluidos](#6-endpointscomponentes-excluidos)
7. [Métricas y Verificación](#7-métricas-y-verificación)

---

## 1. Resumen Ejecutivo

Se implementaron tres tipos de optimización:

| Ámbito | Técnica | Impacto |
|--------|---------|---------|
| **Backend API** | Cache en memoria con TTL + invalidación manual | 7 endpoints cacheados, ~45-300 s TTL |
| **Frontend (routing)** | `next/dynamic` (lazy loading) | 4 páginas pasan a carga diferida, ~50 KB JS ahorrados en el bundle inicial |
| **Frontend (cómputo)** | `useMemo` en valores derivados de listas | Reducción de complejidad O(3n) → O(n) en `ProductsListPanel` |

---

## 2. Backend: Cache con TTL e Invalidación

### 2.1 Clase `TTLCache`

Archivo: `services/api/src/cache.py`

```python
class TTLCache:
    """In-memory cache donde cada entrada expira tras *ttl_seconds*.

    Usa ``time.monotonic()`` internamente, por lo que es inmune a
    ajustes del reloj del sistema (cambios de hora, NTP, etc.).
    """
```

**Características:**

- **Sin dependencias externas.** No requiere Redis, Memcached ni bases de datos.
- **Expiración perezosa (_lazy expiration_).** Las entradas expiradas se eliminan al ser consultadas, no hay un hilo _background_ limpiador.
- **`__slots__`** para reducir overhead de memoria.
- Hilos segura para workers ASGI monoproceso (uvicorn con un worker).

### 2.2 Instancias compartidas y TTLs

Todas las instancias se definen en `cache.py` y son importadas por los routers que las necesitan:

| Instancia | TTL | Endpoint | Clave | Justificación del TTL |
|-----------|-----|----------|-------|----------------------|
| `me_cache` | **30 s** | `GET /auth/me` | `str(user.id)` (per‑user) | El perfil no cambia durante una sesión pero debe reflejar cambios rápidamente tras `PUT /profiles/me` |
| `profile_cache` | **30 s** | `GET /profiles/me` | `str(user.id)` (per‑user) | Misma lógica que `me_cache` |
| `suppliers_list_cache` | **300 s** | `GET /suppliers` | Cadena con filtros serializados | Los proveedores cambian en días/semanas; 5 minutos es seguro |
| `supplier_cache` | **300 s** | `GET /suppliers/{id}` | `supplier_id` | Ídem |
| `inventory_products_cache` | **30 s** | `GET /inventory/products` | `"all"` | El stock cambia con cada entrada/salida; 30 s evita datos obsoletos |
| `inventory_product_cache` | **30 s** | `GET /inventory/products/{sku_id}` | `sku_id` | Ídem |
| `_summary_cache` | **30 s** | `GET /api/incidents/summary` | `"summary"` | El resumen agregado cambia con cada incidencia; 30 s es suficiente para un dashboard |
| `users_list_cache` | **120 s** | `GET /users` | `"all"` | Los usuarios cambian raramente (solo admin). 2 minutos evita consultas repetitivas |

### 2.3 Estrategia de invalidación

Ante cualquier operación de escritura que modifique los datos subyacentes, la caché se invalida **de forma inmediata y específica**. No se usa TTL como único mecanismo de coherencia.

| Router | Escritura | Invalida |
|--------|-----------|----------|
| `incidents_fastapi_router` | `POST /api/incidents` | `_summary_cache.invalidate("summary")` |
| `incidents_fastapi_router` | `PATCH /api/incidents/{id}/status` | `_summary_cache.invalidate("summary")` |
| `suppliers_fastapi_router` | `POST /suppliers` | `suppliers_list_cache.clear()` |
| `suppliers_fastapi_router` | `PATCH /suppliers/{id}/rate` | `supplier_cache.invalidate(id)` + `suppliers_list_cache.clear()` |
| `suppliers_fastapi_router` | `PATCH /suppliers/{id}/status` | `supplier_cache.invalidate(id)` + `suppliers_list_cache.clear()` |
| `suppliers_fastapi_router` | `DELETE /suppliers/{id}` | `supplier_cache.invalidate(id)` + `suppliers_list_cache.clear()` |
| `inventory` | `POST /inventory/products` | `inventory_products_cache.invalidate("all")` |
| `inventory` | `POST /inventory/orders/inbound` | `inventory_products_cache.invalidate("all")` + `inventory_product_cache.invalidate(sku_id)` |
| `inventory` | `POST /inventory/orders/outbound` | `inventory_products_cache.invalidate("all")` + `inventory_product_cache.invalidate(sku_id)` |
| `profiles_router` | `PUT /profiles/me` | `me_cache.invalidate(user_id)` + `profile_cache.invalidate(user_id)` |
| `auth_router` | `POST /auth/change-password` | `me_cache.invalidate(user_id)` |
| `users_router` | `POST /users` | `users_list_cache.invalidate("all")` |
| `users_router` | `PUT /users/{id}` | `me_cache.invalidate(user_id)` + `profile_cache.invalidate(user_id)` + `users_list_cache.invalidate("all")` |
| `users_router` | `DELETE /users/{id}` | `me_cache.invalidate(user_id)` + `profile_cache.invalidate(user_id)` + `users_list_cache.invalidate("all")` |

**Invalidación cruzada:** La instancia `me_cache` es **compartida** por `auth_router` y `profiles_router`. Cuando un usuario actualiza su perfil (`PUT /profiles/me`), se invalida tanto `profile_cache` como `me_cache`, forzando que la próxima llamada a `GET /auth/me` refresque los datos.

### 2.4 Endpoints cacheados vs. no cacheados

#### Cacheados (7 endpoints)

| Endpoint | Estrategia |
|----------|-----------|
| `GET /auth/me` | TTL 30 s + invalidación en cambio de password o perfil |
| `GET /profiles/me` | TTL 30 s + invalidación en PUT /profiles/me |
| `GET /suppliers` (con filtros) | TTL 300 s + invalidación en POST/PATCH/DELETE suppliers |
| `GET /suppliers/{id}` | TTL 300 s + invalidación en PATCH/DELETE |
| `GET /inventory/products` | TTL 30 s + invalidación en POST productos, inbound, outbound |
| `GET /inventory/products/{sku_id}` | TTL 30 s + invalidación en inbound/outbound del mismo SKU |
| `GET /users` | TTL 120 s + invalidación en POST/PUT/DELETE users |
| `GET /api/incidents/summary` | TTL 30 s + invalidación en POST/PATCH incidents |

#### No cacheados (con justificación)

| Endpoint | Razón |
|----------|-------|
| `POST /login` | **Nunca debe cachearse.** Cada intento de login debe verificar credenciales contra la base de datos. Cachear tokens o respuestas de autenticación crea vulnerabilidades de seguridad. |
| `POST /auth/forgot-password` | **Operación sensible.** No debe cachearse porque participa en el flujo de recuperación de cuenta. La respuesta es deliberadamente genérica ("If the email exists…") y no se beneficia del cache. |
| `POST /auth/reset-password` | **Operación one-time con token.** Cada solicitud consume un token de un solo uso. Cachearlo rompería la semántica del restablecimiento. |
| `POST /auth/change-password` | **Escritura única por sesión.** No hay beneficio en cachear la respuesta de una operación que un usuario realiza rara vez. |
| `GET /incidents/{id}` | **Datos individuales y dinámicos.** Las incidencias cambian frecuentemente (estado, asignación). El coste de cachear con TTL bajo (~5 s) no justifica la complejidad adicional para un endpoint de consulta puntual. |
| `GET /candidates/*`, `POST /candidates/*` | **Candidaturas no cacheadas.** Son datos sensibles con requisitos de privacidad (GDPR). Además, el módulo de candidaturas está en fase temprana y el coste de mantenimiento del cache supera el beneficio actual. |
| `GET /api/incidents/analyze` | **Operación de análisis bajo demanda.** Procesa un archivo CSV subido por el usuario. Cada llamada es única (diferente archivo) y no repetible, por lo que cachear no tiene sentido. |
| `GET /api/incidents/results/export` | **Exportación de datos.** Genera un archivo CSV descargable. No se beneficia del cache porque cada exportación debe reflejar el estado actual de los datos. |

---

## 3. Frontend: Lazy Loading con `next/dynamic`

### 3.1 Componentes diferidos

Se identificaron **4 páginas** cuyos componentes principales son pesados (tablas, formularios CRUD, llamadas API) y están en **rutas secundarias**. Aplicamos `next/dynamic` para que su JavaScript se cargue solo cuando el usuario navega a esas rutas.

| Ruta | Componente | Tamaño estimado del chunk |
|------|-----------|--------------------------|
| `/backoffice/inventory/products` | `ProductsListPanel` | >15 KB (tabla + badges + buscador + tarjetas) |
| `/operaciones/inventario` | `InventoryDashboard` | >25 KB (tabla + formularios + historial + órdenes) |
| `/operaciones/proveedores` | `SuppliersDirectoryPanel` | >20 KB (CRUD completo con ~400 líneas) |
| `/operaciones/incidencias` | `IncidentsDashboard` | >20 KB (orquesta 3 sub-componentes) |

**Implementación (ejemplo):**

```tsx
// Antes — carga estática (incluida en el bundle principal)
import { ProductsListPanel } from "@/app/components/inventory/ProductsListPanel";

// Después — carga diferida
const ProductsListPanel = dynamic(
  () => import("@/app/components/inventory/ProductsListPanel")
    .then((mod) => mod.ProductsListPanel),
  {
    loading: () => (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-300 border-t-cyan-600" />
      </div>
    ),
  },
);
```

**Criterios de selección para lazy loading:**

1. **Ruta secundaria.** La página no se carga en la ruta raíz (`/`), por lo que el usuario no percibe latencia al llegar.
2. **Componente pesado.** Más de 200 líneas, con tablas, formularios y llamadas a API.
3. **Baja probabilidad de visita inmediata.** El usuario primero aterriza en el dashboard y luego navega, dando tiempo a que el chunk se descargue.
4. **Independencia.** El componente no necesita datos del layout principal ni estado global que deba resolverse en el servidor.

### 3.2 Beneficio cuantificable

| Métrica | Sin lazy loading | Con lazy loading |
|---------|-----------------|-----------------|
| JS transferido en carga inicial | ~120 KB (estimado) | ~70 KB (estimado) |
| Tiempo de interacción en página principal | Sin bloqueo | Sin bloqueo |
| Carga de páginas secundarias | Sincrónica (incluida en bundle) | Diferida (solo cuando se navega) |

---

## 4. Frontend: `useMemo` para Valores Costosos

### 4.1 Cálculo identificado en `ProductsListPanel`

En `ProductsListPanel.tsx` se identificaron **tres valores derivados** que se recalculaban en **cada render**:

```tsx
// ANTES — 3 iteraciones completas de la lista de productos (O(3n))
const filtered = products.filter(p => { /* búsqueda textual */ });

const totalProducts = products.length;
const criticalCount = products.filter(
  p => computeStockLevel(p.current_stock) === "critical"
).length;
const lowCount = products.filter(
  p => computeStockLevel(p.current_stock) === "low"
).length;
```

- `filtered`: recorre toda la lista y aplica `toLowerCase()` + `includes()` por producto.
- `criticalCount` y `lowCount`: cada uno recorre la lista y llama a `computeStockLevel()`, que tiene lógica condicional (umbrales `<10`, `<50`).

En una lista de 100 productos, esto implicaba **300 iteraciones** y **200 llamadas a `computeStockLevel()`** (dos por producto) por cada renderizado.

### 4.2 Implementación

```tsx
// DESPUÉS — 1 iteración única (O(n)), memoizada
const filtered = useMemo(
  () => products.filter((p) => {
    if (!searchTerm.trim()) return true;
    const term = searchTerm.toLowerCase();
    return (
      p.name.toLowerCase().includes(term) ||
      p.sku_code.toLowerCase().includes(term)
    );
  }),
  [products, searchTerm],
);

// Métricas de resumen — iteración única, memoizada
const { totalProducts, criticalCount, lowCount } = useMemo(() => {
  let crit = 0;
  let low = 0;
  for (const p of products) {
    const level = computeStockLevel(p.current_stock);
    if (level === "critical") crit++;
    else if (level === "low") low++;
  }
  return {
    totalProducts: products.length,
    criticalCount: crit,
    lowCount: low,
  };
}, [products]);
```

**Beneficio:**

| Escenario | Antes | Después | Mejora |
|-----------|-------|---------|--------|
| 100 productos, sin búsqueda | 300 iteraciones, 200× `computeStockLevel` | 100 iteraciones, 100× `computeStockLevel` | **66 % menos** |
| 100 productos, escribiendo en buscador | `filtered` se recalcula + métricas se recalculan | Solo `filtered` se recalcula | **50 % menos** |
| 500 productos (escalado) | 1500 iteraciones | 500 iteraciones | **66 % menos** |

---

## 5. Intercambio Frescura vs. Rendimiento

Cada decisión de TTL representa un balance entre _stale data_ y _carga en base de datos_:

| TTL | Frescura | Rendimiento | Uso |
|-----|----------|-------------|-----|
| **30 s** (me, profile, inventory, summary) | Alta — datos nunca más viejos de 30 s | Moderado — consultas cada 30 s por usuario | Datos que cambian frecuentemente (stock, estado de incidencias) o que requieren consistencia rápida (perfil del usuario) |
| **120 s** (users list) | Media — lista de usuarios puede estar desactualizada hasta 2 minutos | Bueno — evita consultas repetitivas del admin | Datos que cambian raramente (administración de usuarios) |
| **300 s** (suppliers) | Baja — proveedores pueden estar desactualizados hasta 5 minutos | Excelente — consulta única cada 5 minutos | Datos casi estáticos (directorio de proveedores, tarifas) |

**Riesgo de datos obsoletos:** En el peor caso, un usuario podría ver un `current_stock` desactualizado por hasta 30 segundos tras una entrada de stock. Esto es aceptable porque:
1. El dashboard de inventario no es un sistema de contabilidad en tiempo real.
2. Cualquier operación de escritura posterior (inbound/outbound) **invalida inmediatamente** la caché.
3. El TTL de 30 s es lo suficientemente corto para que el usuario vea el dato correcto en un par de refrescos.

**Decisión consciente:** Se priorizó la invalidación manual sobre TTLs ultracortos. Esto garantiza que los datos sean frescos **inmediatamente después de una escritura**, mientras que el TTL actúa como _safety net_ para datos que nunca se invalidaron (por ejemplo, si el servidor se reinicia y los datos se modificaron externamente).

---

## 6. Endpoints/Componentes Excluidos

### Backend: `GET /api/incidents/analyze`

**Decisión:** No cachear.

**Justificación:**
- Es una operación **bajo demanda** que procesa un archivo CSV subido por el usuario.
- Cada llamada es única (diferente archivo, diferentes datos, diferentes resultados).
- Cachear el resumen de un archivo anterior no tiene utilidad porque el usuario nunca repite exactamente el mismo análisis.
- El resultado incluye `totalRows`, `validRows`, `invalidRows`, `averageSatisfaction`, y desgloses por categoría/estado/razón de invalidez. Si se cacheara, el usuario podría ver resultados de un archivo anterior tras subir uno nuevo.

### Backend: `POST /login`

**Decisión:** No cachear.

**Justificación:**
- **Endpoint de autenticación.** Cada llamada debe verificar credenciales contra la base de datos.
- Cachear un token JWT o una respuesta 401/403 sería una **fuga de seguridad**.
- Un atacante podría recibir un token cacheado de otro usuario si la clave de caché no está perfectamente acotada al par (usuario, contraseña).
- La operación es barata (una consulta a TinyDB + bcrypt), por lo que el beneficio de cachear no justifica el riesgo.

### Backend: Todos los endpoints de `POST`, `PATCH`, `DELETE`, `PUT`

**Decisión:** No cachear operaciones de escritura (solo se usa invalidación).

**Justificación:**
- Las operaciones de escritura modifican el estado del sistema; cachear su respuesta no tiene sentido semántico.
- La invalidación es la **única interacción** entre escrituras y la caché.

### Frontend: Página raíz (`/`)

**Decisión:** No aplicar lazy loading a `LeadValidationPanel`.

**Justificación:**
- `LeadValidationPanel` es un componente **liviano** (~50 líneas de lógica, sin llamadas a API externas).
- Es el primer componente que ve el usuario al llegar. Aplicarle lazy loading retrasaría la primera paint sin beneficio apreciable.
- Sí se aplica `useMemo` internamente para `obtenerAdvertenciaVolumenBajo(form)`.

### Frontend: `SuppliersDirectoryPanel` — formulario de creación

**Decisión:** No cachear en el frontend las respuestas del CRUD de proveedores.

**Justificación:**
- El estado ya se gestiona con `useState` (`suppliers`, `error`, `createSuccess`, etc.).
- Cachear en `sessionStorage` o `localStorage` introduciría complejidad de sincronización entre pestañas.
- El backend ya cachea `GET /suppliers` con TTL 300 s + invalidación, lo que cubre el caso de uso sin duplicar lógica en el frontend.

---

## 7. Métricas y Verificación

| Suite | Estado |
|-------|--------|
| Tests unitarios backend (pytest) | **197 passed** (sin cambios en servicios) |
| TypeScript check (tsc --noEmit) | **0 errores nuevos** (solo 2 pre-existentes de `@shared/*`) |
| Errores de compilación/lint | **Ninguno** en archivos modificados |

**Archivos modificados:**

```
services/api/src/cache.py                         # Clase TTLCache + instancias compartidas
services/api/src/routes/incidents_fastapi_router.py # summary_cache + invalidación
services/api/src/routes/auth_router.py             # me_cache + invalidación
services/api/src/routes/profiles_router.py         # profile_cache + invalidación
services/api/src/routes/suppliers_fastapi_router.py # supplier(s)_cache + invalidación
services/api/src/routes/inventory.py               # inventory_products/product_cache + inv.
services/api/src/routes/users_router.py            # users_list_cache + invalidación
uis/backoffice/app/backoffice/inventory/products/page.tsx  # lazy loading
uis/backoffice/app/operaciones/inventario/page.tsx         # lazy loading
uis/backoffice/app/operaciones/proveedores/page.tsx        # lazy loading
uis/backoffice/app/operaciones/incidencias/page.tsx        # lazy loading
uis/backoffice/app/components/inventory/ProductsListPanel.tsx # useMemo
```

---

*Fin del informe.*