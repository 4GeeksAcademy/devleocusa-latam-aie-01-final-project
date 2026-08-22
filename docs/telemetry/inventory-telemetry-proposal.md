# 📡 Propuesta de Telemetría — TrackFlow

> **Autor:** Lead Data Engineer · Unidad TrackFlow Tech  
> **Fecha:** 2026-08-22  
> **Contexto:** El equipo técnico de Zaragoza descubre los fallos de producción por WhatsApp. No existe telemetría centralizada. Este documento define qué instrumentar, por qué y para qué.

---

## 1. Mapa del flujo de gestión de inventario

A continuación se describe el flujo extremo a extremo (login → orden de entrada/salida) que recorre un operario en el Backoffice de TrackFlow. Cada paso numerado es un **punto de instrumentación candidato**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FLUJO DE GESTIÓN DE INVENTARIO                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [A] Login → [B] AuthGuard → [C] Dashboard Inventario              │
│       │              │              │                               │
│       │         (token KO)     (carga prod.)                        │
│       ▼              ▼              ▼                               │
│  [D] Crear SKU → [E] Entrada Stock → [F] Salida Stock              │
│       │              │              │                               │
│       │         (SKU no existe)  (stock insuficiente → rechazo)     │
│       ▼              ▼              ▼                               │
│  [G] Historial de Órdenes                                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1. Desglose detallado del flujo

| Paso | Acción | Endpoint / Componente | Validaciones |
|------|--------|----------------------|--------------|
| **A** | Login (`POST /auth/login`) | `login/page.tsx` → `services/authApi.ts` | Email y password obligatorios; token devuelto |
| **B** | AuthGuard (verificación JWT) | `components/auth/AuthGuard.tsx` | 3 segmentos JWT; payload decodificable |
| **C** | Dashboard inventario | `components/inventory/InventoryDashboard.tsx` | `GET /inventory/products`, `GET /inventory/orders` |
| **D** | Creación de SKU | `POST /inventory/products` → `routes/inventory.py` | Nombre, sku_code no vacíos; almacén válido |
| **E** | Entrada de stock (inbound) | `POST /inventory/orders/inbound` → `routes/inventory.py` | SKU existe; quantity ≥ 1 |
| **F** | Salida de stock (outbound) | `POST /inventory/orders/outbound` → `routes/inventory.py` | SKU existe; stock suficiente (validación crítica) |
| **G** | Historial de órdenes | `GET /inventory/orders` → `backoffice/inventory/orders/page.tsx` | — |

---

## 2. Eventos de telemetría — Obligatorios

Estos eventos constituyen la **instrumentación mínima viable**. Sin ellos, el equipo sigue ciego.

### 2.1. Flujo de login

**Evento:** `auth.login.attempt`  
**Disparador:** Usuario hace clic en "Entrar al sistema"  
**Payload mínimo:**
```json
{
  "event_type": "auth.login.attempt",
  "timestamp": "2026-08-22T10:15:30Z",
  "user_email_hash": "sha256...",
  "ip_address": "192.168.x.x",
  "warehouse_context": "Zaragoza",
  "user_agent": "Mozilla/5.0..."
}
```
**Formato estricto:**  
Capturamos `auth.login.attempt` porque necesitamos saber **cuántos intentos de login fallan frente a exitosos por almacén y turno**, lo que nos permite tomar la decisión **de bloquear cuentas tras N intentos fallidos y detectar accesos anómalos fuera del horario laboral**.

---

**Evento:** `auth.login.success`  
**Disparador:** Login exitoso, token JWT almacenado en localStorage  
**Payload mínimo:**
```json
{
  "event_type": "auth.login.success",
  "timestamp": "2026-08-22T10:15:32Z",
  "user_uuid": "uuid",
  "warehouse_context": "Los Angeles",
  "session_id": "jti..."
}
```
**Formato estricto:**  
Capturamos `auth.login.success` porque necesitamos saber **qué usuarios están accediendo al sistema, desde qué almacén y con qué frecuencia**, lo que nos permite tomar la decisión **de auditar la trazabilidad de cada movimiento de inventario vinculado a una sesión**.

---

### 2.2. Creación de SKU

**Evento:** `sku.create.attempt`  
**Disparador:** Usuario rellena formulario y pulsa "Guardar producto"  
**Payload mínimo:**
```json
{
  "event_type": "sku.create.attempt",
  "timestamp": "2026-08-22T10:20:00Z",
  "user_uuid": "uuid",
  "sku_code": "WH-LA-001",
  "warehouse": "Los Angeles"
}
```
**Formato estricto:**  
Capturamos `sku.create.attempt` porque necesitamos saber **si hay colisiones de SKU o errores de duplicado en la creación de productos**, lo que nos permite tomar la decisión **de alertar al operario antes de que persista un duplicado y notificar al equipo de datos para consolidar el catálogo**.

---

**Evento:** `sku.create.success` / `sku.create.failure`  
**Disparador:** Respuesta 201 del backend o error de validación  
**Payload mínimo:**
```json
{
  "event_type": "sku.create.failure",
  "timestamp": "2026-08-22T10:20:01Z",
  "user_uuid": "uuid",
  "sku_code": "WH-LA-001",
  "error_detail": "SKU code already exists",
  "http_status": 409
}
```
**Formato estricto:**  
Capturamos `sku.create.failure` porque necesitamos saber **con qué frecuencia falla la creación de SKU y por qué motivo**, lo que nos permite tomar la decisión **de identificar si el problema es de datos duplicados, de UX (el operario no ve el catálogo) o de consistencia entre almacenes**.

---

### 2.3. Entrada de stock (inbound)

**Evento:** `inbound.order.created`  
**Disparador:** `POST /inventory/orders/inbound` → 201 Created  
**Payload mínimo:**
```json
{
  "event_type": "inbound.order.created",
  "timestamp": "2026-08-22T10:30:00Z",
  "user_uuid": "uuid",
  "sku_id": "sku-uuid",
  "sku_code": "WH-LA-001",
  "warehouse": "Los Angeles",
  "quantity": 100,
  "stock_before": 50,
  "stock_after": 150,
  "latency_ms": 234
}
```
**Formato estricto:**  
Capturamos `inbound.order.created` porque necesitamos saber **cada cuánto reponen stock los almacenes, en qué productos y en qué volúmenes**, lo que nos permite tomar la decisión **de ajustar umbrales de stock mínimo y anticipar órdenes de compra antes de que se agote un SKU**.

---

### 2.4. Salida de stock rechazada (CRÍTICO)

**Evento:** `outbound.order.rejected`  
**Disparador:** `POST /inventory/orders/outbound` → 400 — stock insuficiente (la regla de negocio en `routes/inventory.py` línea 187 lanza `HTTPException` si `current_stock - payload.quantity < 0`)  
**Payload mínimo:**
```json
{
  "event_type": "outbound.order.rejected",
  "timestamp": "2026-08-22T11:00:00Z",
  "user_uuid": "uuid",
  "sku_id": "sku-uuid",
  "sku_code": "WH-ZG-042",
  "warehouse": "Zaragoza",
  "quantity_requested": 200,
  "stock_available": 15,
  "latency_ms": 45
}
```
**Formato estricto:**  
Capturamos `outbound.order.rejected` porque necesitamos saber **con qué frecuencia el sistema rechaza salidas de stock por inventario insuficiente, qué SKU y almacén están implicados**, lo que nos permite tomar la decisión **de activar una alerta inmediata al equipo de operaciones para que verifique si hay un problema de inventario físico, un error de registro o una necesidad urgente de reposición**.

---

**Evento:** `outbound.order.created`  
**Disparador:** Salida exitosa, stock decrementado  
**Payload mínimo:**
```json
{
  "event_type": "outbound.order.created",
  "timestamp": "2026-08-22T11:05:00Z",
  "user_uuid": "uuid",
  "sku_id": "sku-uuid",
  "sku_code": "WH-LA-003",
  "warehouse": "Los Angeles",
  "quantity": 10,
  "stock_before": 80,
  "stock_after": 70,
  "latency_ms": 180
}
```
**Formato estricto:**  
Capturamos `outbound.order.created` porque necesitamos saber **qué productos salen del almacén, en qué volumen y a qué ritmo**, lo que nos permite tomar la decisión **de calcular rotación de inventario por SKU y almacén, y detectar picos anómalos de salida que podrían indicar un error de picking o un pedido fraudulento**.

---

### 2.5. Validación de stock — cruce de datos crítico

**Evento:** `stock.validation.discrepancy`  
**Disparador:** Diferencia entre el stock computado por la API (`sum(entries) - sum(exits)`) y el stock esperado según el ERP/SGA del almacén  
**Payload mínimo:**
```json
{
  "event_type": "stock.validation.discrepancy",
  "timestamp": "2026-08-22T12:00:00Z",
  "sku_id": "sku-uuid",
  "sku_code": "WH-ZG-017",
  "warehouse": "Zaragoza",
  "api_stock": 120,
  "sga_stock": 95,
  "difference": 25
}
```
**Formato estricto:**  
Capturamos `stock.validation.discrepancy` porque necesitamos saber **cuándo el stock digital no coincide entre los dos sistemas (API TrackFlow vs SGA local)**, lo que nos permite tomar la decisión **de conciliar inventarios antes de que una discrepancia cause un envío fallido o una orden de compra errónea**.

---

## 3. Eventos de telemetría — Oportunidad

Estos eventos aportan **visibilidad adicional** y habilitan capacidades de análisis predictivo y mejora continua.

### 3.1. Gestión de incidencias en operaciones

**Evento:** `incident.created`  
**Disparador:** El operario registra una incidencia en `/operaciones/incidencias`  
**Payload mínimo:**
```json
{
  "event_type": "incident.created",
  "timestamp": "2026-08-22T14:00:00Z",
  "user_uuid": "uuid",
  "warehouse": "Los Angeles",
  "category": "stock_discrepancy",
  "severity": "high",
  "related_sku": "WH-LA-017"
}
```
**Formato estricto:**  
Capturamos `incident.created` porque necesitamos saber **qué tipos de incidencias se registran con más frecuencia y en qué almacén**, lo que nos permite tomar la decisión **de priorizar mejoras de proceso o formación en los puntos críticos del almacén**.

---

**Evento:** `incident.resolution_time`  
**Disparador:** Incidencia cambia de estado abierto → cerrado  
**Payload mínimo:**
```json
{
  "event_type": "incident.resolution_time",
  "timestamp": "2026-08-22T16:30:00Z",
  "incident_id": "uuid",
  "elapsed_minutes": 150,
  "category": "carrier_delay",
  "warehouse": "Zaragoza"
}
```
**Formato estricto:**  
Capturamos `incident.resolution_time` porque necesitamos saber **cuánto tarda el equipo en resolver cada tipo de incidencia**, lo que nos permite tomar la decisión **de establecer SLA realistas por categoría y detectar cuellos de botella en la resolución**.

---

### 3.2. Gestión de proveedores

**Evento:** `supplier.contacted`  
**Disparador:** El operario accede a un proveedor en `/operaciones/proveedores`  
**Payload mínimo:**
```json
{
  "event_type": "supplier.contacted",
  "timestamp": "2026-08-22T09:15:00Z",
  "user_uuid": "uuid",
  "supplier_id": "uuid",
  "supplier_name": "DHL España",
  "action": "view_contact",
  "warehouse": "Zaragoza"
}
```
**Formato estricto:**  
Capturamos `supplier.contacted` porque necesitamos saber **a qué transportistas acceden los operarios y con qué frecuencia**, lo que nos permite tomar la decisión **de identificar qué transportistas del directorio están infrautilizados o cuáles generan más consultas por problemas recurrentes**.

---

### 3.3. Autenticación y seguridad

**Evento:** `auth.password_reset.requested`  
**Disparador:** Usuario solicita restablecer contraseña (`/forgot-password`)  
**Payload mínimo:**
```json
{
  "event_type": "auth.password_reset.requested",
  "timestamp": "2026-08-22T08:00:00Z",
  "user_email_hash": "sha256...",
  "ip_address": "192.168.x.x"
}
```
**Formato estricto:**  
Capturamos `auth.password_reset.requested` porque necesitamos saber **si hay un patrón de usuarios que olvidan su contraseña con frecuencia**, lo que nos permite tomar la decisión **de mejorar el flujo de onboarding o implementar un SSO corporativo para reducir fricción**.

---

**Evento:** `auth.session.expired`  
**Disparador:** Token JWT expira y el AuthGuard redirige a `/login`  
**Payload mínimo:**
```json
{
  "event_type": "auth.session.expired",
  "timestamp": "2026-08-22T13:45:00Z",
  "user_uuid": "uuid",
  "session_duration_minutes": 480
}
```
**Formato estricto:**  
Capturamos `auth.session.expired` porque necesitamos saber **cuánto duran las sesiones activas de los operarios**, lo que nos permite tomar la decisión **de ajustar el TTL del token JWT para equilibrar seguridad con productividad (evitar cierres de sesión en medio de una entrada de stock)**.

---

### 3.4. Navegación y UX

**Evento:** `ui.page.view`  
**Disparador:** El operario navega a una página del backoffice  
**Payload mínimo:**
```json
{
  "event_type": "ui.page.view",
  "timestamp": "2026-08-22T10:00:00Z",
  "user_uuid": "uuid",
  "page": "/backoffice/inventory/products",
  "warehouse": "Los Angeles",
  "referrer": "/backoffice/inventory/orders"
}
```
**Formato estricto:**  
Capturamos `ui.page.view` porque necesitamos saber **qué pantallas del backoffice se usan más y en qué orden las visitan los operarios**, lo que nos permite tomar la decisión **de rediseñar la navegación para que las rutas más frecuentes estén a un clic y reducir el tiempo medio por tarea**.

---

**Evento:** `ui.action.error`  
**Disparador:** El frontend captura un error no controlado (try/catch en componentes React)  
**Payload mínimo:**
```json
{
  "event_type": "ui.action.error",
  "timestamp": "2026-08-22T11:20:00Z",
  "user_uuid": "uuid",
  "component": "InventoryDashboard",
  "action": "createInboundOrder",
  "error_message": "No fue posible conectar con el servidor de inventario",
  "http_status": 0
}
```
**Formato estricto:**  
Capturamos `ui.action.error` porque necesitamos saber **qué operaciones fallan en el frontend, aunque la API responda correctamente**, lo que nos permite tomar la decisión **de diagnosticar problemas de conectividad de red, errores de serialización o bugs de estado en el cliente antes de que el operario abandone la tarea**.

---

### 3.5. Caché y rendimiento

**Evento:** `cache.inventory.hit` / `cache.inventory.miss`  
**Disparador:** Acceso a `TTLCache` en `cache.py` para productos o listado de SKU  
**Payload mínimo:**
```json
{
  "event_type": "cache.inventory.hit",
  "timestamp": "2026-08-22T10:00:01Z",
  "cache_key": "all",
  "ttl_seconds": 30,
  "query_latency_saved_ms": 120
}
```
**Formato estricto:**  
Capturamos `cache.inventory.hit` porque necesitamos saber **la efectividad de la cache TTL en los endpoints de inventario**, lo que nos permite tomar la decisión **de ajustar el tiempo de vida de la caché para equilibrar frescura de datos con rendimiento en horas pico**.

---

### 3.6. Candidates y leads (procesos comerciales)

**Evento:** `candidate.stage.changed`  
**Disparador:** Un candidato cambia de etapa en `/candidaturas`  
**Payload mínimo:**
```json
{
  "event_type": "candidate.stage.changed",
  "timestamp": "2026-08-22T15:00:00Z",
  "user_uuid": "uuid",
  "candidate_id": "uuid",
  "from_stage": "review",
  "to_stage": "technical_interview",
  "elapsed_days": 5
}
```
**Formato estricto:**  
Capturamos `candidate.stage.changed` porque necesitamos saber **cuánto tiempo permanecen los candidatos en cada etapa del proceso de selección**, lo que nos permite tomar la decisión **de identificar cuellos de botella en el funnel de contratación y agilizar las transiciones**.

---

**Evento:** `lead.conversion.rate`  
**Disparador:** Un lead pasa de prospecto a cliente en el módulo de leads  
**Payload mínimo:**
```json
{
  "event_type": "lead.conversion.rate",
  "timestamp": "2026-08-22T17:00:00Z",
  "user_uuid": "uuid",
  "lead_id": "uuid",
  "source": "web_form",
  "country": "US",
  "deal_value": 45000
}
```
**Formato estricto:**  
Capturamos `lead.conversion.rate` porque necesitamos saber **qué canales de captación generan más clientes y de mayor valor**, lo que nos permite tomar la decisión **de redirigir el presupuesto comercial hacia los canales con mejor retorno por país**.

---

## 4. Resumen de la instrumentación

### Tabla consolidada — Obligatorios

| # | Evento | Dónde se instrumenta | Gatillo |
|---|--------|---------------------|---------|
| 1 | `auth.login.attempt` | `services/authApi.ts` — antes de `fetch` | Submit del formulario de login |
| 2 | `auth.login.success` | `login/page.tsx` — después de `setSessionToken` | Login exitoso |
| 3 | `sku.create.attempt` | `InventoryDashboard.tsx` — `handleCreateProduct` | Click en "Guardar producto" |
| 4 | `sku.create.failure` | `routes/inventory.py` — en el handler 201 | Error de base de datos o validación |
| 5 | `inbound.order.created` | `routes/inventory.py` — después de `db.commit` | POST inbound exitoso |
| 6 | `outbound.order.rejected` | `routes/inventory.py` — en el `if current_stock - quantity < 0` | Validación de stock fallida |
| 7 | `outbound.order.created` | `routes/inventory.py` — después de `db.commit` | POST outbound exitoso |
| 8 | `stock.validation.discrepancy` | Proceso batch programado (cada hora) | Comparación API vs SGA |

### Tabla consolidada — Oportunidad

| # | Evento | Módulo | Gatillo |
|---|--------|--------|---------|
| 9 | `incident.created` | Incidencias | Nuevo registro de incidencia |
| 10 | `incident.resolution_time` | Incidencias | Cambio de estado a cerrado |
| 11 | `supplier.contacted` | Proveedores | Acceso a ficha de proveedor |
| 12 | `auth.password_reset.requested` | Auth | Solicitud de reset |
| 13 | `auth.session.expired` | Auth | Token expirado |
| 14 | `ui.page.view` | Frontend global | Cada cambio de ruta |
| 15 | `ui.action.error` | Frontend global | Error capturado en component |
| 16 | `cache.inventory.hit`/`miss` | `cache.py` | Cada acceso a TTLCache |
| 17 | `candidate.stage.changed` | Candidaturas | Cambio de etapa |
| 18 | `lead.conversion.rate` | Leads | Conversión de lead |

---

## 5. Recomendaciones de implementación

### Stack sugerido
- **OpenTelemetry** para la instrumentación estándar en Python (FastAPI) y JavaScript (Next.js)
- **Exporters** hacia un backend de observabilidad: **Grafana + Tempo (trazas) + Loki (logs) + Mimir (métricas)**
- **Agente OTel Collector** desplegado como sidecar en el contenedor de la API y como servidor central para agregar telemetría de ambos almacenes

### Prioridad de implantación
1. **Fase 1 (día 1):** Eventos obligatorios 1–8 → Alertas en tiempo real para `outbound.order.rejected` y `auth.login.failure`
2. **Fase 2 (semana 1):** Eventos de oportunidad 9–16 → Dashboard de operaciones y UX
3. **Fase 3 (mes 1):** Eventos 17–18 → Visibilidad comercial y de RRHH

### Arquitectura de alertas
```
                    ┌──────────────────┐
                    │  WhatsApp        │ ← NOTIFICACIÓN INMEDIATA
                    │  + Slack         │    (stock rechazado, error 5xx)
                    └────────┬─────────┘
                             │
┌──────────┐   ┌────────────▼─────────┐   ┌──────────────┐
│ Backend  │──▶│ OpenTelemetry        │──▶│ Grafana      │
│ FastAPI  │   │ Collector            │   │ + Loki       │
│ Next.js  │   │                      │   │ + Mimir      │
└──────────┘   └──────────────────────┘   │ + Tempo      │
                                           └──────────────┘
```

### Conclusión

Con esta instrumentación, el equipo de Zaragoza **deja de enterarse por WhatsApp**. Cada `outbound.order.rejected` dispara una alerta automática al canal de Slack de operaciones. Cada `auth.login.attempt` desde una IP no reconocida genera un evento de seguridad. Cada discrepancia de stock entre API y SGA queda registrada para conciliación.

La telemetría no es un proyecto de reporting: es el sistema nervioso central que permite a TrackFlow operar con los dos almacenes como si fueran uno.

---

## 6. Clasificación Stream vs Batch

Cada evento del catálogo se procesa por uno de dos canales. La asignación depende de la **ventana de decisión** que cada evento exige.

### 6.1. Eventos Stream (tiempo real)

Estos eventos requieren un SLA de procesamiento **< 5 segundos** porque su consumo desencadena una acción inmediata sobre las operaciones del almacén o la experiencia del operario.

| Evento | SLA | Consumidor | Razón operativa |
|--------|-----|-----------|-----------------|
| `outbound.order.rejected` | 1 s | Alerta Slack + notificación in-app | 70 operarios no pueden completar una salida sin saber por qué el sistema la rechazó. Si el stock físico existe pero el digital no, deben conciliar en el momento, no esperar al parte de fin de turno. |
| `warehouse.stock_alert` | 2 s | Alerta Slack + email al responsable de almacén | Un SKU por debajo del umbral mínimo puede detener picking de pedidos urgentes. Ana Whitfield necesita saberlo antes de que un cliente reclame. |
| `api.error.server` | 1 s | Alerta Slack #ops-tech + PagerDuty | El equipo de Zaragoza se entera hoy por WhatsApp. Con stream, Andrés Kim recibe una notificación estructurada con trace ID y contexto del endpoint. |
| `auth.login.failure` (≥3 intentos) | 5 s | Alerta de seguridad | Si un usuario acumula 3+ fallos en 15 min desde una IP desconocida, el equipo de sistemas debe poder bloquear la cuenta antes de que sea un acceso no autorizado. |
| `stock.validation.discrepancy` | 10 s | Dashboard en tiempo real | Mientras el proceso batch ejecuta la conciliación cada hora, las discrepancias individuales se emiten en stream para que un operario pueda verificarlas antes de que se acumulen. |
| `ui.action.error` | 5 s | Log centralizado + métrica | Si el frontend deja de conectar con la API en medio de la jornada, el equipo técnico lo detecta en segundos, no cuando el operario abre un ticket. |

**Pipeline stream propuesto:**

```
Emisor (frontend/backend)
    │
    ▼
Kafka / Redpanda topic: trackflow.events.raw
    │  ┌─────────────────────────────┐
    ├──│ outbound.order.rejected    │───▶ Alerta Slack #ops-warehouse
    ├──│ api.error.server           │───▶ PagerDuty + Slack #ops-tech
    ├──│ auth.login.failure (3+)    │───▶ Alerta seguridad
    └──│ warehouse.stock_alert      │───▶ Email + Slack
       └─────────────────────────────┘
    │
    ▼
Flink / Kafka Streams: enriquecer con datos de SKU y usuario
    │
    ▼
    Sink a OpenSearch para dashboards en tiempo real
```

### 6.2. Eventos Batch (lotes)

Estos eventos no requieren acción inmediata. Se acumulan y procesan en ventanas de **1 hora a 24 horas** para alimentar dashboards, informes y modelos analíticos.

| Evento | Ventana | Consumidor | Razón operativa |
|--------|---------|-----------|-----------------|
| `auth.login.attempt` | 1 h | Dashboard seguridad | No necesitas saber en tiempo real que alguien intentó loguearse. Lo que importa es la tasa de éxito/fallo agregada por hora y por almacén. |
| `auth.login.success` | 1 h | Dashboard audit trail | La sesión del operario se asocia a movimientos posteriores. Con batch es suficiente para trazabilidad. |
| `sku.create.attempt` | 1 h | Dashboard catálogo | Saber cuántos SKU se intentan crear por hora ayuda a dimensionar el crecimiento del catálogo, pero no es urgente. |
| `sku.create.success` / `sku.create.failure` | 1 h | Dashboard catálogo | Ídem anterior. |
| `inbound.order.created` | 15 min | Dashboard inventario + pipeline analítico | Las entradas se consolidan cada cuarto de hora. La rotación de inventario se calcula con datos agregados, no evento a evento. |
| `outbound.order.created` | 15 min | Dashboard inventario + pipeline analítico | Ídem anterior. La velocidad de salida de un SKU concreto se analiza en ventanas, no en tiempo real. |
| `sku.list.requested` | 1 h | Dashboard rendimiento | Tasa de acierto de caché vs consulta a DB. Se monitoriza por hora. |
| `auth.password_reset.requested` | 24 h | Informe semanal seguridad | Los patrones de olvido de contraseña se analizan semanalmente. No hay urgencia. |
| `auth.password_reset.completed` | 24 h | Informe semanal seguridad | Ídem. |
| `auth.session.expired` | 1 h | Dashboard sesiones | La distribución de duración de sesión se analiza por hora. Útil para ajustar TTL del JWT, pero no crítico. |
| `auth.register.completed` | 24 h | Informe RRHH | Nuevos registros de usuario se revisan diariamente. |
| `api.error.client` | 1 h | Dashboard errores | Los errores 4xx se agregan por hora para detectar patrones de mal uso de la API. |
| `performance.api.latency` | 5 min | Dashboard rendimiento | La latencia se muestrea al 10% y se agrega en ventanas de 5 minutos. Suficiente para detectar degradación sin saturar el pipeline. |
| `cache.inventory.hit` / `cache.inventory.miss` | 5 min | Dashboard rendimiento | La tasa de acierto de caché es una métrica de rendimiento que se evalúa en ventanas. |
| `incident.created` | 1 h | Dashboard incidencias | La frecuencia de creación de incidencias es una métrica de proceso que se revisa por hora. |
| `incident.resolved` | 1 h | Dashboard incidencias + SLA | El tiempo de resolución se calcula sobre datos agregados. |
| `incident.status_changed` | 1 h | Dashboard incidencias | Los cambios de estado agrupados permiten ver el flujo del pipeline. |
| `carrier.assigned` | 15 min | Dashboard transportistas | Carlos Vega necesita ver las asignaciones del día, pero no en tiempo real. Batch cada 15 min es suficiente. |
| `supplier.viewed` | 1 h | Dashboard transportistas | El acceso a fichas de proveedor se analiza por hora para detectar tendencias. |
| `ui.page.view` | 1 h | Dashboard UX | Los patrones de navegación se analizan por hora. Aunque la frecuencia es alta, se procesa en batch para evitar saturación. Ver throttling en sección 7. |
| `ui.form.validation_error` | 1 h | Dashboard UX | Los errores de formulario se agrupan para identificar campos problemáticos. |
| `candidate.stage.changed` | 24 h | Dashboard RRHH | El proceso de selección es asíncrono. Un informe diario es suficiente. |
| `lead.converted` | 24 h | Dashboard comercial | Las conversiones de lead se registran a diario para el informe de Miguel Torres. |

**Pipeline batch propuesto:**

```
Eventos en buffer (memoria / Redis / archivo local)
    │
    ▼ (cada ventana)
Flush al topic Kafka: trackflow.events.batch
    │
    ▼
Spark Structured Streaming / Airflow DAG diario
    │
    ▼
    ├──▶ OpenSearch (dashboards agregados)
    ├──▶ PostgreSQL / ClickHouse (tablas analíticas)
    └──▶ Google Sheets (informe semanal ejecutivo)
```

---

## 7. Estrategia de Throttle / Debounce

Ciertos eventos pueden dispararse cientos de veces por minuto en condiciones normales de operación. Sin control de frecuencia, saturarían el pipeline y dispararían alertas falsas.

### 7.1. Eventos con throttling obligatorio

| Evento | Frecuencia estimada | Estrategia | Configuración |
|--------|-------------------|------------|---------------|
| `ui.page.view` | ~200-400/día por operario (~70 ops = 14k-28k/día) | **Debounce** en frontend: si el operario navega entre 2 páginas en menos de 500 ms (ej. cambios rápidos de pestaña), solo se emite el último evento. | `debounce(500ms)` en el router `usePathname()` |
| `sku.list.requested` | ~50-100/día por operario (~3500-7000/día total) | **Throttle**: el endpoint responde desde caché TTL (30 s). No emitir evento si la respuesta vino de caché con edad < 30 s. | `emit_if = response.from_cache && cache.age > 30` |
| `performance.api.latency` | ~2000-5000/día (todos los endpoints) | **Sampleo**: solo 1 de cada 10 peticiones genera este evento. El sample rate se configura por variable de entorno. | `sampling_rate = 0.1` (10%), configurable |
| `ui.form.validation_error` | ~30-100/día total | **Aggregation**: no enviar un evento por cada error. Acumular contadores en el frontend y emitir un evento agregado cada 5 minutos. | Ventana de 5 min, `count` + `field` como dimensión |
| `ui.action.error` | ~10-50/día total | Sin throttle. Cada error merece ser capturado individualmente. | Sin restricción |

### 7.2. Reglas globales de throttling

Se aplican a nivel del **OpenTelemetry Collector** para evitar que un cliente defectuoso o un ataque de fuerza bruta sature el pipeline:

```
Regla 1: Máximo 100 eventos/segundo por sessionId
Regla 2: Máximo 1000 eventos/segundo por userId
Regla 3: Máximo 5000 eventos/segundo global
Regla 4: Si se excede cualquiera de los 3 umbrales, el exceso se descarta y se emite
         un evento de alerta: "telemetry.throttle.activated"
```

### 7.3. Algoritmo de debounce para `ui.page.view`

```typescript
// Pseudocódigo del debounce en frontend (Next.js usePathname)
let debounceTimer: ReturnType<typeof setTimeout> | null = null;  
let lastEmittedPage: string | null = null;

function onRouteChange(page: string, referrer: string) {
  if (debounceTimer) clearTimeout(debounceTimer);
  
  // Si es la misma página que la última emitida, ignorar
  if (page === lastEmittedPage) return;
  
  debounceTimer = setTimeout(() => {
    emitTelemetry({
      event_type: 'ui.page.view',
      properties: { page, referrer }
    });
    lastEmittedPage = page;
  }, 500); // 500 ms de ventana
}
```

---

## 8. Riesgos y Exclusiones de Datos

### 8.1. Riesgo 1 — Ruido de eventos de alta frecuencia

**Escenario:** Un operario que recarga el dashboard de productos 30 veces en un minuto por impaciencia genera 30 eventos `sku.list.requested` y 30 `ui.page.view`.

**Mitigación:**
- Throttling en frontend (debounce 500 ms para cambios de ruta).
- Cache TTL en backend (30 s para listado de productos). Si la respuesta se sirve desde caché, el evento `sku.list.requested` solo se emite si la edad de caché supera 30 s.
- El OpenTelemetry Collector descarta eventos duplicados con misma `eventId`.

### 8.2. Riesgo 2 — Tormenta de eventos por error en cascada

**Escenario:** La base de datos se cae y cada petición a la API genera un `api.error.server`. 70 operarios haciendo peticiones simultáneas → cientos de eventos por segundo.

**Mitigación:**
- Circuit breaker en el middleware de errores: si se emiten más de 10 `api.error.server` en 10 segundos desde el mismo endpoint, se activa **modo silencio**: solo se emite 1 evento cada 30 segundos resumiendo el error.
- La regla global `max 100 eventos/segundo por userId` en el Collector descarta el exceso automáticamente.

### 8.3. Riesgo 3 — Datos PII en logs de error

**Escenario:** Un error inesperado incluye en el mensaje un email, un número de teléfono o un identificador personal que el código no sanitizó.

**Mitigación:**
- El middleware de errores en FastAPI aplica una expresión regular de barrrido antes de emitir el evento: busca patrones de email (`\S+@\S+\.\S+`), teléfono (`\+\d+`) y los reemplaza por `[REDACTED]`.
- El `error_traceback` se procesa con `STRIP_FILE_PATHS` (política documentada en `sensitiveDataPolicy`).
- Los mensajes se truncan a 300 caracteres para limitar la exposición accidental.

### 8.4. Riesgo 4 — Falsa alarma en `outbound.order.rejected`

**Escenario:** Un operario introduce por error una cantidad de salida de 10.000 unidades cuando solo hay 5 en stock. El evento se emite como `outbound.order.rejected`, pero no es un problema real de inventario, sino un error humano.

**Mitigación:**
- El evento se emite **siempre** — es mejor una falsa alarma que un falso negativo.
- Pero se añade un campo contextual `user_error_probability` calculado como `|stock_available - quantity_requested| / stock_available`. Si es > 100 (el operario pidió 100x más del stock disponible), la alerta se marca como "baja prioridad" y se omite el envío a Slack, aunque el evento queda registrado.
- El dashboard permite filtrar alertas por `stock_deficit / stock_available` ratio para separar errores humanos de problemas sistémicos.

### 8.5. Exclusiones explícitas de datos

Por política de TrackFlow Tech, los siguientes datos **nunca deben ser capturados** por ningún evento de telemetría:

| Dato excluido | Motivo | Excepción |
|--------------|--------|-----------|
| **Contraseñas en texto plano** | Credenciales. El evento `auth.login.attempt` se emite antes de incluir el password en el body del fetch. | Ninguna. |
| **JWT completo** | El token contiene claims de usuario y firma. Solo se extrae el `jti` (JWT ID). | Análisis forense con orden judicial — requiere extracción manual con autorización del CISO. |
| **Payload completo del body de peticiones HTTP** | Podría contener datos PII (direcciones de envío, nombres de clientes). Solo se capturan campos explícitamente listados en la allowlist del schema. | Ninguna. |
| **Documentos de identidad (DNI, NIF, SSN)** | PII de alto riesgo GDPR. El sistema de TrackFlow no maneja estos datos, pero se excluyen por si un error de integración los expusiera. | Ninguna. |
| **Geolocalización precisa (GPS)** | Solo se almacena la ciudad/almacén inferido. Coordenadas exactas nunca. | Investigación de paquetes perdidos — requiere autorización del responsable de almacén y only para el caso concreto. |
| **Números de tarjeta de crédito** | TrackFlow no procesa pagos directamente, pero las integraciones con transportistas podrían exponer datos de facturación. Bloqueo a nivel de schema. | Ninguna. |
| **Datos de salud o categorías especiales GDPR Art. 9** | TrackFlow maneja ropa y electrónica, no datos sanitarios. Exclusión preventiva. | Ninguna. |
| **Contenido de mensajes de WhatsApp o emails de clientes** | Solo se capturan eventos de sistema, no comunicaciones. El agente de CX opera sobre su propia base de conocimiento. | Ninguna. |

### 8.6. Retención de datos

| Tipo de evento | Retención en hot storage (OpenSearch) | Retención en cold storage (S3/Glacier) | Destrucción |
|---------------|--------------------------------------|----------------------------------------|-------------|
| Eventos stream (críticos) | 90 días | 1 año | Eliminación segura tras 1 año + 30 días de gracia |
| Eventos batch | 30 días | 6 meses | Eliminación tras 6 meses |
| Eventos con PII (email hash, IP) | 30 días | No se archivan | Eliminación tras 30 días |
| Logs de error con traceback | 90 días | 1 año | Eliminación tras 1 año |

### 8.7. Compliance GDPR / CCPA

- Los eventos con `user_email_hash` se consideran datos pseudónimos. El mapeo hash → email real solo está disponible en la base de datos de usuarios de TinyDB, con acceso restringido al equipo de sistemas.
- Cualquier ciudadano de la UE puede solicitar la eliminación de sus eventos de telemetría mediante el DPO. El proceso se ejecuta borrando los eventos cuyo `userId` coincida con el solicitante en el hot storage.
- Los eventos con IP enmascarada (`MASK_LAST_OCTET`) caen fuera del alcance de PII según la guía del WP29. La versión completa de la IP solo se almacena si el usuario ha consentido explícitamente en la política de cookies/datos del backoffice.

---

## 9. Implementación de Mitigaciones — Código Existente

Tras auditar el código fuente de la plataforma, se confirma que **las mitigaciones definidas en las secciones 7 y 8 ya están implementadas** en los siguientes componentes:

### 9.1. Backend — `services/api/src/telemetry.py`

| Mitigación | Estado | Detalle |
|-----------|--------|---------|
| **PII Sanitization** | ✅ Implementado | 7 regexes: emails, teléfonos, rutas absolutas, tarjetas crédito, GPS, DNI español, SSN. Recursivo sobre dicts y listas. Truncado a 300 caracteres. |
| **Exclusion enforcement** | ✅ Implementado | `EXCLUDED_KEYS` (18 keys) elimina datos prohibidos del payload. `build_envelope()` emite `telemetry.exclusions.enforced` automáticamente cuando detecta una clave excluida. |
| **Circuit Breaker** | ✅ Implementado | Clase `CircuitBreaker` con threshold configurable, ventana de tiempo, cooldown. Cuando >10 errores/10s desde un mismo endpoint → modo silencio 30s. Contador `dropped_count` para eventos suprimidos. |
| **Middleware FastAPI** | ✅ Implementado | `TelemetryMiddleware` registrado en `fastapi_server.py` con `app.add_middleware(TelemetryMiddleware)`. Intercepta 4xx/5xx, inyecta `requestId` en `request.state`, aplica circuit breaker en 5xx. |
| **Emisión de `telemetry.throttle.activated`** | ✅ Implementado | Cuando el circuit breaker se abre, emite evento con `dropped_count`, `endpoint`, `reason` y `original_event_type`. |
| **Falsa alarma en `outbound.order.rejected`** | ✅ Implementado | `routes/inventory.py` calcula `user_error_probability` como `|stock_available - quantity_requested| / stock_available`. Si ratio > 100, la alerta se marca como baja prioridad. |

### 9.2. Frontend — `uis/backoffice/lib/telemetry.ts`

| Mitigación | Estado | Detalle |
|-----------|--------|---------|
| **Debounce `ui.page.view`** | ✅ Implementado | `debouncedPageView()` con 500ms de ventana. Evita eventos duplicados para la misma página. |
| **Throttle `sku.list.requested`** | ✅ Implementado | Salta el evento si la respuesta vino de caché y la edad es < 30s. |
| **Sampling `performance.api.latency`** | ✅ Implementado | Tasa de muestreo del 10% (`PERFORMANCE_SAMPLE_RATE = 0.1`). |
| **Exclusion enforcement (frontend)** | ✅ Implementado | `EXCLUDED_KEYS` incluye password, jwt, access_token, etc. Emite `telemetry.exclusions.enforced` con `source: "frontend"`. |
| **PII sanitization (cliente)** | ✅ Implementado | Regexes para email, teléfono y tarjeta crédito. Truncado a 300 caracteres. |
| **Envío con `sendBeacon`** | ✅ Implementado | Usa `navigator.sendBeacon()` para fiabilidad en page unload. Fallback a `fetch` con `keepalive: true`. |

### 9.3. Mapeo Riesgo → Código

| Riesgo (Sección 8) | Archivo(s) | Líneas clave |
|--------------------|-----------|-------------|
| R1 — Ruido alta frecuencia | `lib/telemetry.ts` | `debouncedPageView()`, `throttledSkuListRequest()`, `CONFIG.PAGE_VIEW_DEBOUNCE_MS` |
| R2 — Tormenta 5xx | `telemetry.py` | `CircuitBreaker.record_error()`, `_breaker.is_silent()`, `count_dropped()` |
| R3 — PII en logs | `telemetry.py` | `sanitize_value()`, `sanitize_properties()`, `EXCLUDED_KEYS` |
| R3 — PII en frontend | `lib/telemetry.ts` | `sanitizeString()`, `sanitizeProps()`, `EXCLUDED_KEYS` (frontend) |
| R4 — Falsa alarma | `routes/inventory.py` | Lógica `user_error_probability` en endpoint `outbound.order` |

### 9.4. Estado de Validación

| Componente | Linter/Compiler | Errores |
|-----------|----------------|---------|
| `services/api/src/telemetry.py` | ✅ Python (no errors) | 0 |
| `services/api/src/fastapi_server.py` | ✅ Python (no errors) | 0 |
| `uis/backoffice/lib/telemetry.ts` | ✅ TypeScript (no errors) | 0 |