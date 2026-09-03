# Pipeline de Inteligencia Ejecutiva — TrackFlow

## Sección 1: Propósito del Negocio

### 1.1 Stakeholder y Audiencia

| Rol | Nombre | Área | Relación con el pipeline |
|---|---|---|---|
| **Cliente interno principal** | Daniel Espinoza | CEO / Dirección Ejecutiva | Consumidor primario del dashboard y del informe semanal. Necesita visibilidad consolidada del negocio para tomar decisiones estratégicas sin depender de reportes manuales. |
| **Patrocinador técnico** | Andrés Kim | CTO / Tecnología (Zaragoza) | Responsable de viabilizar la infraestructura del pipeline y alinear los contratos de datos con la arquitectura del monorepo. |
| **Fuentes de datos (7 áreas)** | Ana Whitfield, Carlos Vega, Sofía Ramos, Valentina Cruz, Miguel Torres | Operaciones, Última Milla, Logística Inversa, Atención al Cliente, Comercial | Cada directivo consolida manualmente los datos de su área los domingos. Con el pipeline, pasan de *recolectores* a *consumidores* de un subconjunto de métricas validadas. |
| **Audiencia secundaria** | Account Managers y equipo de Desarrollo de Negocio | Comercial | Consumirán los KPIs agregados por cliente para informes automáticos y renovaciones. |

### 1.2 Entregable de Negocio

**Producto:** Informe semanal consolidado de negocio — dashboard ejecutivo con capacidad de consulta en lenguaje natural.

**Cadencia de publicación:** Todos los lunes a las **7:00 AM (hora del Pacífico)**, sin intervención humana.

**Formato:**
- Dashboard interactivo en tiempo real con KPIs globales y desglose por país (EE. UU. / España).
- Informe PDF generado automáticamente con la fotografía semanal del negocio.
- Alertas por umbrales críticos (caída de tasa de entrega, pico de devoluciones, descenso de CSAT).

**¿Qué sustituye?** El proceso manual en el que cada director dedicaba 3–4 horas los domingos a combinar datos de sistemas dispares. Con el pipeline, Daniel Espinoza dispone del informe completo al comenzar su semana laboral, con datos actualizados y trazables.

### 1.3 Métricas y KPIs Obligatorios

El pipeline debe calcular y exponer los siguientes KPIs para el dashboard ejecutivo:

| # | KPI | Definición | Dimensión |
|---|---|---|---|
| 1 | **Volumen global de envíos** | Número total de paquetes enviados en la semana, con desglose por país, transportista y canal (B2B / B2C). | Operaciones / Última Milla |
| 2 | **Tasa de entrega a tiempo (OTD — On-Time Delivery)** | Porcentaje de envíos entregados dentro de la ventana prometida al cliente. Segmentable por país, transportista y ruta. | Última Milla |
| 3 | **Coste operativo** | Coste agregado de la operación logística semanal (almacenamiento + picking + transporte + devoluciones). Medido en valor absoluto (€) y como coste por unidad enviada (€/paquete). | Financiero / Transversal |
| 4 | **Métricas de devoluciones** | Volumen de devoluciones gestionadas en la semana, tasa de devolución sobre envíos totales (%), y clasificación por motivo, cliente y país. | Logística Inversa |
| 5 | **Satisfacción del cliente (CSAT)** | Puntuación media de satisfacción del cliente (escala 1–5), recogida post-entrega o post-interacción. Segmentable por país y canal. | Atención al Cliente / CX |

### 1.4 Por qué el reporte técnico actual no responde a estas preguntas

El módulo `services/telemetry/analysis.py` implementa funciones de análisis operativo sobre eventos de telemetría del sistema (errores por endpoint, latencia por servicio, tasa de fallos de login, eventos por día). Su propósito es **monitorizar la salud técnica de la plataforma**, no medir el rendimiento del negocio.

Las carencias fundamentales son:

1. **Cobertura de dominio:** Las métricas técnicas (error rate, latency, login failures) no guardan relación con los KPIs de negocio. No existe ninguna función que compute volumen de envíos, tasa de entrega a tiempo, coste operativo, devoluciones o CSAT.

2. **Fuente de datos inadecuada:** `analysis.py` opera exclusivamente sobre el DataFrame de eventos de telemetría (`event_type`, `severity`, `tags`). Los datos necesarios para los KPIs de negocio residen en sistemas transaccionales (pedidos, envíos, devoluciones, encuestas CSAT), no en la cola de eventos técnicos.

3. **Ausencia de agregación temporal semanal:** Las funciones actuales agrupan por día o por endpoint. El pipeline ejecutivo requiere agregación semanal (lunes a domingo) con comparativas intermensuales y desglose por país.

4. **Sin modelo de dimensionalidad:** El reporte actual devuelve listas planas de diccionarios sin estructura de hechos y dimensiones. El dashboard ejecutivo necesita un modelo dimensional que permita navegar de lo global (volumen total) a lo particular (envíos de un cliente concreto en Zaragoza con SEUR).

5. **Sin alertas ni umbrales:** `analysis.py` es puramente consultivo — calcula y devuelve. El pipeline ejecutivo debe incorporar un sistema de alertas que notifique cuando un KPI cruza un umbral crítico (ej. OTD < 85 %, CSAT < 3.5).

---

*Fin de la Sección 1. Pendiente de validación por el sponsor del proyecto antes de continuar con las secciones de Arquitectura de Datos, Modelo Dimensional y Orquestación del Pipeline.*

---


## Sección 2: Arquitectura de Datos y Modelo Dimensional

### 2.1 Fuentes de Datos — El Contrato de Lectura

El pipeline de inteligencia ejecutiva utiliza la tabla `telemetry_events` como **única fuente de lectura**, exclusivamente con operaciones SELECT. No está autorizado a leer directamente de los sistemas transaccionales (SGA, ERP, transportistas, CRM), ni de tablas intermedias no consensuadas. Todo el dato de negocio necesario para los 5 KPIs debe llegar a `telemetry_events` a través del endpoint `POST /telemetry/events`.

#### Estructura vigente de `telemetry_events`

| Columna | Tipo | Origen | Descripción |
|---|---|---|---|
| `id` | UUID | `eventId` del productor | Identificador único del evento |
| `event_type` | VARCHAR | `event_type` del productor | Clasificación semántica del evento |
| `timestamp` | TIMESTAMPTZ | `timestamp` del productor | Marca de tiempo ISO 8601 en UTC |
| `payload` | JSONB | `properties` del productor | **Contenedor de campos aditivos de negocio** |
| `tags` | JSONB | `sessionId`, `userId`, `requestId`, `schemaVersion` | Trazabilidad técnica del evento |

#### Campos aditivos requeridos por KPI en `payload`

Los productores de eventos (sistemas internos y adaptadores) deben inyectar los siguientes campos en el dict `properties` del evento, que se persiste en la columna `payload` de `telemetry_events`:

**Volumen global de envíos**

| Campo aditivo | Tipo | Descripción |
|---|---|---|
| `costo_eur` | `numeric(10,2)` | Coste del envío en euros |
| `carrier_id` | `VARCHAR` | Identificador del transportista (ej. `UPS`, `MRW`, `SEUR`, `FEDEX`, `DHL`) |
| `country` | `VARCHAR(2)` | País ISO 3166-1 alpha-2 (`US` o `ES`) |
| `weight_kg` | `numeric(8,3)` | Peso del paquete en kilogramos |

**Tasa de entrega a tiempo (OTD — On-Time Delivery)**

| Campo aditivo | Tipo | Descripción |
|---|---|---|
| `promised_delivery_date` | `DATE` | Fecha prometida al cliente (ISO 8601) |
| `actual_delivery_date` | `DATE` | Fecha real de entrega (ISO 8601) |
| `carrier_id` | `VARCHAR` | Identificador del transportista |
| `country` | `VARCHAR(2)` | País ISO 3166-1 alpha-2 |

**Coste operativo**

| Campo aditivo | Tipo | Descripción |
|---|---|---|
| `costo_eur` | `numeric(10,2)` | Coste unitario del evento en euros |
| `cost_category` | `VARCHAR` | Clasificación del coste (`transporte`, `almacenamiento`, `devolucion`, `manipuleo`) |
| `country` | `VARCHAR(2)` | País ISO 3166-1 alpha-2 |

**Métricas de devoluciones**

| Campo aditivo | Tipo | Descripción |
|---|---|---|
| `return_reason` | `VARCHAR` | Motivo categorizado (`defecto`, `talla incorrecta`, `cambio de opinion`, `producto erroneo`, `otro`) |
| `costo_eur` | `numeric(10,2)` | Coste estimado de la devolución |
| `client_id` | `VARCHAR` | Identificador de la marca cliente |
| `country` | `VARCHAR(2)` | País ISO 3166-1 alpha-2 |

**CSAT (Satisfacción del Cliente)**

| Campo aditivo | Tipo | Descripción |
|---|---|---|
| `csat_score` | `numeric(2,1)` | Puntuación 1.0 a 5.0 (escala Likert) |
| `interaction_channel` | `VARCHAR` | Canal de recogida (`post_entrega`, `post_devolucion`, `post_interaccion_cx`) |
| `client_id` | `VARCHAR` | Identificador de la marca cliente |
| `country` | `VARCHAR(2)` | País ISO 3166-1 alpha-2 |

> **Nota de diseño:** La columna `payload` (JSONB) absorbe estos campos sin modificar el esquema físico de la tabla. El pipeline extraerá los valores con operadores JSONB (`payload->>'costo_eur'`) y validará su presencia antes de la agregación.

#### Reglas del contrato de lectura

1. **Solo SELECT.** El pipeline ejecuta únicamente lecturas sobre `telemetry_events`; nunca escribe en esta tabla.
2. **Ventana semanal:** Cada ejecución lee eventos cuyo `timestamp` cae en la semana natural anterior (lunes 00:00 UTC → domingo 23:59:59 UTC).
3. **Tolerancia a campos ausentes:** Si un evento no porta el campo aditivo necesario para un KPI, se excluye del agregado (no se asume valor cero). El pipeline lo contabiliza en `events_discarded` para auditoría.
4. **No mezclar fuentes:** Prohibido enriquecer con tablas externas a `telemetry_events`. Si un campo no está en `payload`, debe añadirse en el productor del evento.

---

### 2.2 Destino de Datos — El Modelo Dimensional (`reporting`)

Queda **prohibido** almacenar resultados agregados en `telemetry_events`. El pipeline escribe exclusivamente en tablas del nuevo esquema `reporting`, independiente del esquema `public` donde vive `telemetry_events`.

#### `reporting.weekly_executive_metrics`

Fila única por `(semana, país)`. Tabla principal del dashboard ejecutivo y del informe PDF de los lunes.

| Columna | Tipo | Descripción | KPI asociado |
|---|---|---|---|
| `id` | SERIAL | PK autogenerada | — |
| `week_start` | DATE | Inicio de la semana (lunes) | — |
| `week_end` | DATE | Fin de la semana (domingo) | — |
| `country` | VARCHAR(2) | `US` o `ES` | — |
| `total_shipments` | INTEGER | Volumen de envíos en la semana | Volumen global |
| `ontime_delivery_rate` | NUMERIC(5,2) | % de entregas dentro de la ventana prometida | Tasa OTD |
| `total_operational_cost_eur` | NUMERIC(12,2) | Suma de todos los costes operativos semanales | Coste operativo |
| `cost_per_shipment_eur` | NUMERIC(8,2) | `total_operational_cost_eur / total_shipments` | Coste unitario |
| `total_returns` | INTEGER | Volumen de devoluciones en la semana | Devoluciones |
| `return_rate` | NUMERIC(5,2) | `total_returns / total_shipments * 100` | Tasa de devolución |
| `avg_csat_score` | NUMERIC(3,2) | Media ponderada de CSAT semanal | CSAT |
| `csat_survey_count` | INTEGER | Número de encuestas CSAT recibidas | CSAT (volumen) |
| `pipeline_execution_ts` | TIMESTAMPTZ | Marca de tiempo de la última ejecución | Auditoría |
| `events_processed` | INTEGER | Eventos crudos consumidos para este agregado | Auditoría |
| `events_discarded` | INTEGER | Eventos excluidos por campos ausentes | Auditoría |

**Clave primaria compuesta:** (`week_start`, `country`).

#### `reporting.carrier_performance`

Fila única por `(semana, transportista, país)`. Alimenta la sección de rendimiento de transportistas en el dashboard.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL | PK autogenerada |
| `week_start` | DATE | Inicio de la semana |
| `carrier_id` | VARCHAR | Identificador del transportista |
| `country` | VARCHAR(2) | País |
| `total_shipments` | INTEGER | Envíos gestionados por este transportista |
| `ontime_delivery_rate` | NUMERIC(5,2) | % OTD de este transportista |
| `avg_cost_per_shipment_eur` | NUMERIC(8,2) | Coste medio por envío con este transportista |
| `total_returns` | INTEGER | Devoluciones asociadas a este transportista |
| `pipeline_execution_ts` | TIMESTAMPTZ | Marca de tiempo de la última ejecución |

**Clave primaria compuesta:** (`week_start`, `carrier_id`, `country`).

#### `reporting.client_health`

Fila única por `(semana, cliente, país)`. Alimenta alertas de riesgo de renovación y el perfil de salud del cliente para el equipo comercial.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL | PK autogenerada |
| `week_start` | DATE | Inicio de la semana |
| `client_id` | VARCHAR | Identificador de la marca cliente |
| `country` | VARCHAR(2) | País |
| `total_shipments` | INTEGER | Envíos gestionados para este cliente |
| `ontime_delivery_rate` | NUMERIC(5,2) | % OTD para este cliente |
| `return_rate` | NUMERIC(5,2) | % de devoluciones sobre envíos |
| `avg_csat_score` | NUMERIC(3,2) | CSAT medio del cliente |
| `total_operational_cost_eur` | NUMERIC(12,2) | Coste operativo total asociado al cliente |
| `pipeline_execution_ts` | TIMESTAMPTZ | Marca de tiempo de la última ejecución |

**Clave primaria compuesta:** (`week_start`, `client_id`, `country`).

#### `reporting.alert_thresholds`

Tabla de configuración que define los umbrales que disparan notificaciones warning (amarillas) y críticas (rojas). Poblada por el equipo de tecnología/dirección, no por el pipeline.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL | PK autogenerada |
| `metric_name` | VARCHAR | Nombre del KPI (`ontime_delivery_rate`, `return_rate`, `avg_csat_score`, etc.) |
| `warning_threshold` | NUMERIC | Valor que dispara alerta amarilla |
| `critical_threshold` | NUMERIC | Valor que dispara alerta roja |
| `direction` | VARCHAR(4) | `desc` (umbral superior) o `asc` (umbral inferior) |
| `active` | BOOLEAN | Si el umbral está habilitado |

---

### 2.3 Capa de Servicio — Exposición

Los datos del modelo dimensional se exponen a través de un nuevo módulo de servicio dentro del monorepo, **completamente independiente** de `services/telemetry/`:

```
services/
├── telemetry/          ← Salud técnica del sistema (existente — no se modifica)
│   ├── analysis.py
│   ├── models.py
│   └── router.py
│
└── reporting/          ← Inteligencia de negocio (nuevo — este es nuestro dominio)
    ├── __init__.py
    ├── models.py       ← Pydantic models para los schemas de salida
    ├── pipeline.py     ← Lógica de extracción, transformación y carga semanal
    ├── queries.py      ← Consultas SQL parametrizadas sobre el esquema reporting
    └── router.py       ← Endpoints FastAPI para dashboard ejecutivo y PDF
```

**Relación entre módulos:**

| Módulo | Lee de | Escribe en | Propósito |
|---|---|---|---|
| `services/telemetry/` | — | `telemetry_events` (público) | Ingesta y monitoreo técnico |
| `services/reporting/` | `telemetry_events` (SELECT) | `reporting.*` (esquema nuevo) | Agregación de negocio y exposición |

`services/reporting/` no depende funcionalmente de `services/telemetry/`. Comparten la misma base de datos PostgreSQL/Supabase pero operan sobre esquemas distintos sin acoplamiento de código.

---

### 2.4 Frecuencia y Granularidad

#### Ciclo de ejecución semanal

| Propiedad | Valor |
|---|---|
| **Frecuencia** | Semanal (batch) |
| **Ejecución del pipeline** | Domingo, 23:00 UTC (16:00 PT / 01:00 CET+1) |
| **Publicación del informe** | Lunes, 7:00 AM PT |
| **Ventana de datos** | Semana natural anterior: lunes 00:00 UTC → domingo 23:59:59 UTC |
| **Modo** | Batch programado por trigger temporal |

#### Niveles de granularidad del procesamiento

El pipeline transforma los eventos crudos en agregaciones mediante tres niveles progresivos:

1. **Nivel evento (filtrado y validación)**
   - Filtra por `event_type` según el KPI destino.
   - Valida la presencia de los campos aditivos requeridos en `payload`.
   - Descarta eventos incompletos y los contabiliza en `events_discarded`.

2. **Nivel agregación primaria (por dimensión)**
   - Agrupa por `(semana, país)` para `weekly_executive_metrics`.
   - Agrupa por `(semana, transportista, país)` para `carrier_performance`.
   - Agrupa por `(semana, cliente, país)` para `client_health`.

3. **Nivel agregación secundaria (exposición)**
   - Las tablas agregadas se sirven vía `services/reporting/router.py` a los endpoints del dashboard ejecutivo.
   - El informe PDF semanal se genera a partir de la combinación de filas `(semana, 'US') + (semana, 'ES')` de `weekly_executive_metrics`.

#### Estrategia de actualización (upsert idempotente)

| Ventana de tiempo | Comportamiento |
|---|---|
| Semana en curso (D-0) | No se procesa. El pipeline opera solo sobre semanas cerradas. |
| Semana anterior (D-7) | **Upsert:** si existe fila para `(week_start, country)`, se reemplaza; si no, se inserta. |
| Semanas históricas (D-14+) | Inmutables. No se reescriben salvo reprocesamiento manual autorizado. |

> La estrategia upsert garantiza que el pipeline sea **idempotente**: ejecutarlo dos veces sobre la misma ventana produce el mismo resultado sin duplicar filas.

---

*Fin de la Sección 2. Pendiente de validación antes de continuar con la Sección 3: Orquestación del Pipeline y Estrategia de Implementación.*

## Sección 3: Orquestación del Pipeline (Prefect)

### 3.1 Definición del Flujo Principal (Flow)

El pipeline se implementa como un único **Flow** de Prefect que orquesta la extracción, transformación y carga de los KPIs ejecutivos. Este Flow se registra en el servidor de Prefect con una programación (schedule) fija y se ejecuta de forma autónoma cada semana.

#### Identidad del Flow

| Propiedad | Valor |
|---|---|
| **Nombre del Flow** | `weekly-executive-report` |
| **Schedule** | `0 23 * * 0` (cada domingo a las 23:00 UTC) |
| **Timezone** | UTC (la ventana de datos se define en UTC; el informe se publica en PT) |
| **Trigger** | Cron schedule gestionado por Prefect Scheduler |
| **Work Pool** | `trackflow-reporting-pool` (pool dedicado para procesos batch de reporting) |

#### Contrato del Flow

- **Entrada implícita:** Ventana semanal `(week_start, week_end)` calculada automáticamente como la semana natural anterior completa.
- **Salida:** Las cuatro tablas del esquema `reporting` pobladas con los agregados semanales.
- **Efecto secundario:** Notificación de éxito/fallo al canal de Slack del equipo de tecnología en Zaragoza.
- **Garantía:** Idempotencia total — ejecutar el Flow dos veces sobre la misma ventana produce el mismo estado en base de datos.

#### Diagrama lógico del Flow

```
INICIO (Domingo 23:00 UTC)
  │
  ├─ 1. Calcular ventana semanal (week_start, week_end)
  │
  ├─ 2. Extraer eventos de telemetry_events
  │     └─ Filtro: event_type IN (tipos requeridos)
  │     └─ Filtro: timestamp BETWEEN week_start AND week_end
  │
  ├─ 3. Transformar y cargar (en paralelo):
  │     ├─ 3a. weekly_executive_metrics  ─── upsert
  │     ├─ 3b. carrier_performance        ─── upsert
  │     └─ 3c. client_health              ─── upsert
  │
  ├─ 4. Evaluar alertas vs. alert_thresholds
  │
  └─ 5. Notificar resultado (Slack / dashboard)
        └─ FIN (Informe listo para las 7:00 AM PT del lunes)
```

---

### 3.2 Desglose de Tareas (Tasks)

Cada paso del Flow se modela como una **Task** de Prefect con una responsabilidad única y bien definida. Las Tasks se organizan en tres capas: extracción, transformación y carga.

#### 3.2.1 Capa de Extracción (Extract)

| Task | Nombre lógico | Responsabilidad |
|---|---|---|
| `compute_window` | `compute_reporting_window` | Calcula `week_start` (lunes anterior 00:00 UTC) y `week_end` (domingo anterior 23:59:59 UTC). Es puramente determinista: misma fecha → misma ventana. |
| `fetch_events` | `fetch_telemetry_events` | Ejecuta SELECT contra `telemetry_events` con filtro de ventana temporal y lista blanca de `event_type`. Retorna un conjunto de eventos crudos. Implementa paginación para evitar saturar la conexión a la base de datos. |

**Parámetros de `fetch_telemetry_events`:**

| Parámetro | Valor | Justificación |
|---|---|---|
| `event_types` | `['shipment.created', 'shipment.delivered', 'shipment.failed', 'return.requested', 'return.approved', 'return.rejected', 'return.inspected', 'return.processed', 'warehouse.picking.completed', 'csat.survey.submitted']` | Lista blanca que cubre todos los `event_type` necesarios para los 5 KPIs. |
| `batch_size` | 5000 filas por página | Evita timeouts en la conexión a Supabase. |
| `timeout_seconds` | 120 | Timeout máximo para la consulta completa. |

#### 3.2.2 Capa de Transformación (Transform)

Una Task independiente por cada tabla de destino. Cada task recibe el conjunto completo de eventos crudos, filtra los relevantes para su KPI y produce el agregado listo para insertar.

| Task | Tabla destino | Lógica de transformación |
|---|---|---|
| `build_weekly_metrics` | `reporting.weekly_executive_metrics` | Filtra eventos de envío (`shipment.*`), devoluciones (`return.*`), costes (`warehouse.*`) y CSAT (`csat.*`). Agrupa por `(semana, país)`. Calcula los 5 KPIs y los KPIs derivados (`cost_per_shipment_eur`, `return_rate`). |
| `build_carrier_performance` | `reporting.carrier_performance` | Filtra eventos de envío y devolución. Agrupa por `(semana, transportista, país)`. Calcula OTD, coste medio y volumen. |
| `build_client_health` | `reporting.client_health` | Filtra eventos de envío, devolución y CSAT. Agrupa por `(semana, cliente, país)`. Calcula las 5 métricas de salud del cliente. |

**Reglas comunes a todas las Tasks de transformación:**

1. **Validación de campos:** Cada task verifica la presencia de los campos aditivos requeridos. Los eventos incompletos se descartan y se contabilizan en `events_discarded`.
2. **Agregación en memoria:** Las Tasks operan sobre el conjunto de eventos ya extraído (no relanzan consultas a la base de datos).
3. **Salida estructurada:** Cada task retorna una lista de diccionarios con el esquema exacto de la tabla de destino, lista para la capa de carga.

#### 3.2.3 Capa de Carga (Load)

Una Task genérica y reutilizable para ejecutar el upsert en cada tabla de destino.

| Task | Nombre lógico | Responsabilidad |
|---|---|---|
| `upsert_table` | `upsert_reporting_table` | Recibe el nombre de la tabla destino, la lista de filas a insertar y los nombres de las columnas que forman la clave primaria compuesta. Ejecuta una operación **INSERT ... ON CONFLICT ... DO UPDATE** (upsert) para cada tabla. |

**Comportamiento del upsert:**

| Condición | Acción |
|---|---|
| No existe fila con la misma PK `(week_start, country, ...)` | **INSERT** — se crea una nueva fila |
| Ya existe fila con la misma PK | **UPDATE** — se reemplazan todas las columnas de métricas con los valores actuales |
| La PK coincide pero todos los valores son idénticos | **UPDATE** — operación nula (no hay cambio efectivo) |

**Contrato de `upsert_table`:**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `table_name` | `str` | Nombre cualificado de la tabla destino (`reporting.weekly_executive_metrics`, etc.) |
| `rows` | `list[dict]` | Filas a insertar/actualizar |
| `pk_columns` | `list[str]` | Columnas que forman la clave primaria compuesta |
| `schema` | `str` | Esquema de base de datos (siempre `reporting`) |

---

### 3.3 Los 3 Pilares de un Pipeline Robusto

#### 3.3.1 Idempotencia

**Problema:** Si el pipeline falla a los 5 minutos de ejecución por un timeout de red y se relanza automáticamente, los datos no deben duplicarse. Una doble ejecución no debe duplicar el volumen de envíos ni inflar los costes operativos.

**Solución — Doble capa de idempotencia:**

| Capa | Mecanismo | Cómo lo garantiza |
|---|---|---|
| **Upsert en base de datos** | `INSERT ... ON CONFLICT (week_start, country, ...) DO UPDATE` | La clave primaria compuesta impide filas duplicadas. Si la fila ya existe, se actualiza; si no, se inserta. |
| **Flow de Prefect** | Ejecución determinista sobre una ventana fija | El Flow siempre opera sobre la semana natural anterior (D-7), que es un intervalo cerrado e inmutable. La misma ventana + los mismos eventos crudos = el mismo resultado agregado. |

**Escenario de recuperación:**

1. Domingo 23:00 UTC — el Flow comienza la ejecución.
2. La Task `fetch_telemetry_events` extrae 12 000 eventos correctamente.
3. La Task `upsert_table` para `carrier_performance` falla por un bloqueo en la base de datos.
4. Prefect reintenta la Task (hasta 3 veces según la política configurada).
5. Si el reintento falla, todo el Flow se marca como `FAILED`.
6. Un ingeniero revisa la causa raíz y relanza el Flow manualmente desde la UI de Prefect.
7. **Resultado:** El upsert detecta que las filas de `weekly_executive_metrics` y `client_health` ya existen y las sobrescribe con los mismos valores. Las filas de `carrier_performance` se completan. No hay duplicados.

#### 3.3.2 Observabilidad

**Problema:** Hoy, cuando algo falla, el equipo se entera por un mensaje de WhatsApp de alguien en operaciones. El CTO Andrés Kim necesita visibilidad en tiempo real del estado del pipeline sin depender de comunicación informal.

**Solución — Tres capas de observabilidad con Prefect:**

| Capa | Componente Prefect | Qué expone |
|---|---|---|
| **Estados del Flow** | `PrefectState` (`COMPLETED`, `FAILED`, `RUNNING`, `RETRYING`, `CRASHED`) | Estado global de la ejecución semanal visible en el dashboard de Prefect. |
| **Estados de cada Task** | `TaskRun` con metadatos | Visibilidad granular: qué task falló, cuántos reintentos consumió, cuánto tiempo tomó cada transformación. |
| **Logs estructurados** | `get_run_logger()` en cada Task | Logs con formato JSON que registran: número de eventos extraídos, eventos descartados por campos ausentes, filas insertadas/actualizadas en cada tabla. Ver §3.3.2.1 para el esquema completo. |

**Bloques de configuración de Prefect:**

| Bloque | Propósito | Contenido |
|---|---|---|
| **Consecutions Block** | Conexión a Supabase/PostgreSQL | Cadena de conexión (`SQL_URL`) gestionada como secreto de Prefect, no en variables de entorno. |
| **Slack Block** | Notificaciones al equipo | Webhook del canal `#tech-alerts` de Slack en Zaragoza. |
| **Email Block** | Notificaciones a dirección ejecutiva | Fallos críticos notifican además a `andres.kim@trackflow.com` con un resumen del error. |

**¿Qué ve el equipo sin abrir WhatsApp?**

1. **Dashboard de Prefect Server:** Muestra el estado del último run del Flow `weekly-executive-report`. Si está `COMPLETED`, el informe está listo. Si está `FAILED`, el equipo lo sabe antes de que operaciones llame.
2. **Notificación automática a Slack:** Al finalizar el Flow, Prefect envía un mensaje al canal `#tech-alerts`:
   - ✅ Éxito: "Pipeline semanal completado — 15 230 eventos procesados, 3 tablas actualizadas, 0 alertas críticas."
   - ❌ Fallo: "Pipeline semanal FALLIDO — Task `build_carrier_performance` errores tras 3 reintentos. Revisar dashboard de Prefect."
3. **Logs persistentes:** Cada ejecución del Flow queda registrada en la base de datos de Prefect con trazabilidad completa para auditoría posterior.

##### 3.3.2.1 Estructura del log de ejecución

Cada Task instrumentada con `get_run_logger()` emite un documento JSON al finalizar su ejecución. Los siguientes campos son obligatorios para garantizar la auditabilidad del pipeline:

| Campo | Tipo | Justificación operativa |
|---|---|---|
| `events_extracted` | integer | Número de filas leídas de `telemetry_events` en la ventana. Permite detectar caídas o picos inesperados en el volumen de datos. |
| `events_discarded` | integer | Eventos excluidos del agregado por campos ausentes o valores nulos en columnas clave (e.g. `event_type`). Permite monitorizar la calidad del dato fuente. |
| `rows_upserted_weekly_metrics` | integer | Filas insertadas o actualizadas en `reporting.weekly_executive_metrics`. Correlacionable con `events_extracted` para validar el ratio de agregación. |
| `rows_upserted_carrier_performance` | integer | Filas afectadas en `reporting.carrier_performance`. Útil para depurar problemas específicos de transportistas. |
| `rows_upserted_client_health` | integer | Filas afectadas en `reporting.client_health`. Permite rastrear la cobertura de clientes en el informe semanal. |
| `pipeline_execution_ts` | timestamptz | Marca de tiempo UTC de la ejecución. Base para auditoría cronológica y correlación con eventos externos. |
| `flow_run_id` | uuid | Identificador único del run en Prefect. Permite cruzar el log con el estado del Flow y las notificaciones de Slack. |
| `error_message` | text | Mensaje de error si la Task falló. Vacío (`""`) en ejecuciones exitosas. Imprescindible para diagnóstico sin consultar el dashboard de Prefect. |

> **Validación en shadow mode:** Durante la fase de shadow mode (Hito 2, §4.2), el equipo de ingeniería verificará que estos 8 campos se emiten correctamente y que ningún valor es `NULL` no esperado.

#### 3.3.3 Recuperabilidad

**Problema:** La base de datos puede tener un bloqueo momentáneo, la red puede sufrir una latencia anómala, o Supabase puede rate-limit la conexión. El pipeline debe resistir estos fallos transitorios sin intervención humana.

**Solución — Política de reintentos por capa:**

| Task | Reintentos | Retroceso (backoff) | Justificación |
|---|---|---|---|
| `fetch_telemetry_events` | 3 | Exponencial: 10s → 30s → 90s | Fallos de red o rate-limiting de Supabase. El backoff exponencial evita saturar la base de datos. |
| `build_weekly_metrics` | 2 | Fijo: 5s | Fallos de memoria o tipo de dato. El reintento suele ser suficiente tras una validación. |
| `build_carrier_performance` | 2 | Fijo: 5s | Ídem |
| `build_client_health` | 2 | Fijo: 5s | Ídem |
| `upsert_table` | 3 | Exponencial: 5s → 15s → 45s | Bloqueos de base de datos (deadlocks) o conflictos de concurrencia. El backoff da tiempo al motor de base de datos para resolverse. |

**Política global del Flow:**

| Propiedad | Valor |
|---|---|
| `retry_delay_seconds` | Variable por Task (ver tabla superior) |
| `timeout_seconds` | 600 (10 minutos máximo por ejecución completa) |
| `flow_completed` | Notificación a Slack |
| `flow_failed` | Notificación a Slack + email a Andrés Kim |

**Mecanismo de recuperación ante fallo:**

1. Prefect detecta una excepción en la Task (ej. `psycopg2.OperationalError` por timeout de conexión).
2. Prefect consulta la configuración de reintentos de la Task.
3. Si quedan reintentos, Prefect espera el tiempo de backoff y vuelve a ejecutar **solo esa Task** (no todo el Flow).
4. Si la Task se completa en el reintento, el Flow continúa desde donde se quedó.
5. Si se agotan los reintentos, Prefect marca la Task como `FAILED` y todo el Flow como `FAILED`.
6. El equipo recibe la notificación automática y puede relanzar el Flow desde la UI de Prefect con un solo clic.

> **Nota de diseño:** La estrategia de reintentos por Task (en lugar de reintentar todo el Flow) minimiza el tiempo de recuperación y evita reprocesar transformaciones que ya se completaron correctamente.

---

### 3.4 Resumen de la Arquitectura de Orquestación

| Componente | Decisión | Alternativa descartada | Razón |
|---|---|---|---|
| **Orquestador** | Prefect | Apache Airflow, Dagster | Prefect es más ligero, se integra nativamente con serverless, y su modelo de bloques simplifica la gestión de secretos. Para un pipeline semanal con ~10 Tasks, Airflow añade sobrecarga operativa innecesaria. |
| **Programación** | Cron schedule en Prefect Scheduler | Desencadenar por evento (webhook) | El informe debe publicarse a una hora fija (lunes 7:00 AM). Un trigger por evento no garantiza la hora exacta. |
| **Ejecución** | Prefect Work Pool local (`trackflow-reporting-pool`) | Cloud run serverless | El pipeline lee y escribe en la misma base de datos que el monorepo. Ejecutar en el mismo entorno de red reduce latencia y costes de transferencia. |
| **Notificaciones** | Slack Block + Email Block | Solo Slack | El canal de Slack es para el equipo técnico; el email es para el CTO como respaldo. |

---

*Fin de la Sección 3. Pendiente de validación antes de continuar con la Sección 4: Estrategia de Implementación y Roadmap.*

## Sección 4: Estrategia de Implementación y Roadmap

### 4.1 Fases de Desarrollo (Roadmap)

La implementación del pipeline se divide en tres hitos lógicos, cada uno con un entregable tangible y una puerta de validación. Los hitos pueden solaparse parcialmente, pero cada uno debe completar sus criterios de aceptación antes de considerar la fase cerrada.

#### Hito 1: Lógica Core (ETL Base)

**Objetivo:** Construir los módulos de extracción, transformación y carga como funciones Python puras, operando sobre un subconjunto de datos de prueba (sin conexión a base de datos real). Validar que las transformaciones producen los agregados correctos para los 5 KPIs.

**Duración estimada:** 2 semanas

**Entregables:**

| Entregable | Descripción | Criterio de aceptación |
|---|---|---|
| `services/reporting/pipeline.py` | Funciones puras de extracción y transformación sin efectos secundarios | Cada función retorna el esquema exacto definido en la Sección 2. Las agregaciones manuales sobre datos de prueba coinciden con el output de las funciones. |
| `services/reporting/queries.py` | Consultas SQL parametrizadas para upsert idempotente en las 3 tablas de destino (`weekly_executive_metrics`, `carrier_performance`, `client_health`) | Las consultas ejecutadas contra una base de datos local de prueba producen el comportamiento upsert esperado: INSERT en primera ejecución, UPDATE en segunda ejecución, sin duplicados. |
| `data/sample_events.json` | Conjunto de 50–100 eventos sintéticos de ejemplo que cubren todos los `event_type` y todos los campos aditivos | El conjunto incluye al menos un evento válido y un evento incompleto para cada KPI, permitiendo probar la tolerancia a campos ausentes. |

**Dependencias externas:**
- Ninguna. Todo el hito se ejecuta con datos sintéticos y una base de datos PostgreSQL local (Docker) o SQLite en memoria.

**Puerta de validación:**
> El equipo de tecnología (Andrés Kim) revisa que las funciones de transformación producen los agregados correctos para los 5 KPIs. Se firma el hito cuando existe cobertura de prueba unitaria ≥ 80 % sobre `pipeline.py`.

---

#### Hito 2: Orquestación (Prefect)

**Objetivo:** Envolver la lógica del Hito 1 en Tasks y Flows de Prefect, configurar la programación semanal, los reintentos (retries) y las notificaciones automáticas (Slack + Email). Erradicar la dependencia de mensajes de WhatsApp para conocer el estado del pipeline.

**Duración estimada:** 1 semana

**Entregables:**

| Entregable | Descripción | Criterio de aceptación |
|---|---|---|
| `services/reporting/flow.py` | Definición del Flow `weekly-executive-report` con las 7 Tasks orquestadas según el diseño de la Sección 3 | El Flow se ejecuta correctamente en un entorno local de Prefect (Prefect Server o Prefect Cloud con work pool local). |
| `prefect.yaml` | Archivo de configuración de Prefect con definición del work pool, bloques de conexión y schedule cron | Prefect ejecuta el Flow automáticamente según el schedule `0 23 * * 0` sin intervención manual. |
| Configuración de bloques | Slack Block (`#tech-alerts`), Email Block (`andres.kim@trackflow.com`), Consecutions Block (SQL_URL) | Los bloques están registrados en el servidor de Prefect y son referenciables por nombre desde el Flow. |
| Política de reintentos | Configuración de retries por Task según la tabla definida en 3.3.3 (backoff exponencial) | Se simula un fallo temporal en cada capa (extracción, transformación, carga) y Prefect reintenta automáticamente según la política definida. |

**Puerta de validación:**
> Se ejecuta el Flow completo en un entorno de staging conectado a una réplica de `telemetry_events` con datos históricos. El Flow se ejecuta 3 veces consecutivas sobre la misma ventana semanal y se verifica que los datos en `reporting.*` son idénticos en cada ejecución (prueba de idempotencia). Se simula un fallo de red y se verifica la notificación automática a Slack.

---

#### Hito 3: Capa de Exposición (API)

**Objetivo:** Construir el router FastAPI en `services/reporting/` para exponer los datos del esquema `reporting` a la capa visual (dashboard y PDF). Este hito conecta el pipeline con el consumidor final: Daniel Espinoza.

**Duración estimada:** 1 semana

**Entregables:**

| Entregable | Descripción | Criterio de aceptación |
|---|---|---|
| `services/reporting/router.py` | Endpoints FastAPI para consultar las tablas del esquema `reporting` | `GET /reporting/weekly-metrics?week=2026-08-31&country=US` retorna la fila correcta de `weekly_executive_metrics`. |
| `services/reporting/models.py` | Pydantic models para serialización de las respuestas de la API | Los modelos validan que los KPIs devueltos están dentro de rangos esperados (ej. `ontime_delivery_rate` entre 0 y 100). |
| `services/reporting/router.py` — `GET /api/v1/reporting/weekly-metrics` | `queries.get_weekly_metrics(week_start: date, country: str)` → `list[WeeklyExecutiveMetrics]` | Retorna los KPIs agregados para la semana y país indicados. Filtra por `reporting.weekly_executive_metrics.week = :week_start AND country = :country`. |
| `services/reporting/router.py` — `GET /api/v1/reporting/alerts` | `queries.get_active_alerts(week_start: date)` → `list[AlertThresholds]` | Retorna las alertas activas para la semana (KPI que cruzan umbrales definidos en `alert_thresholds`). Se usa para colorear el dashboard ejecutivo. |
| `services/reporting/router.py` — `GET /api/v1/reporting/pipeline/status` | `queries.get_last_pipeline_run()` → `dict` con `flow_run_id`, `state`, `execution_ts`, `error_message` | Expone el estado de la última ejecución del pipeline. Permite al dashboard mostrar un indicador visual de "datos actualizados" o "datos desactualizados". |
| `services/reporting/router.py` — `POST /api/v1/reporting/pipeline/trigger` | `pipeline.trigger_manual_run(week_start: date)` → `dict` con `flow_run_id`, `status: "triggered"` | Dispara una ejecución manual del Flow `weekly-executive-report` para una semana específica. Útil para recuperaciones tras fallos o reprocesos solicitados por el negocio. |
| Integración con el dashboard | Contrato API documentado para el equipo de UI | Los endpoints están disponibles en la misma instancia FastAPI que el resto de servicios del monorepo, bajo el prefijo `/api/v1/reporting/`. Todos los endpoints documentados arriba siguen el patrón `services/reporting/router.py` → `services/reporting/queries.py` → SQL a `reporting.*`. |

**Puerta de validación:**
> Daniel Espinoza (o el equipo de UI en su representación) puede consultar los KPIs de la semana vía endpoints REST. Los datos devueltos coinciden con los agregados almacenados en `reporting.*`. El endpoint de alertas devuelve al menos una alerta de prueba configurada en `alert_thresholds`.

---

#### Mapa de dependencias entre hitos

```
Hito 1 (Core ETL)
    │ Dependencia: base para toda la lógica
    ▼
Hito 2 (Prefect Orchestration)
    │ Dependencia: sin Hito 1 no hay lógica que orquestar
    ▼
Hito 3 (API Exposure)
    │ Dependencia: sin Hito 2 no hay datos agregados que exponer
    ▼
    Producción
```

> **Nota:** Los hitos 2 y 3 pueden solaparse parcialmente. El equipo puede comenzar a diseñar los Pydantic models del Hito 3 mientras Prefect se configura en el Hito 2, siempre que el contrato de datos (esquemas del modelo dimensional) esté congelado.

---

### 4.2 Estrategia de Pruebas (Testing)

#### 4.2.1 Principios

1. **Sin conexión a base de datos real en pruebas unitarias.** Toda prueba que no valide explícitamente el comportamiento del upsert debe ejecutarse contra datos en memoria.
2. **Cobertura mínima del 80 %** en `services/reporting/pipeline.py`.
3. **Una prueba de integración crítica por tabla** que valide el ciclo completo extracción → transformación → upsert contra una base de datos PostgreSQL efímera (creada y destruida por la prueba).

#### 4.2.2 Pirámide de pruebas

```
         ╱╲
        ╱  ╲
       ╱ 3  ╲      ← Pruebas de integración (upsert real contra BD efímera)
      ╱______╲       3 tests: uno por tabla de destino
     ╱        ╲
    ╱    2    ╲     ← Pruebas de transformación (mock de telemetry_events)
   ╱__________╲      9 tests: 3 tablas × 3 escenarios (datos válidos, datos incompletos, datos vacíos)
  ╱            ╲
 ╱      1      ╲    ← Pruebas unitarias (funciones puras)
╱________________╲    12+ tests: validación de campos, cálculo de KPIs, agregación por dimensión
```

**Capa 1 — Pruebas unitarias (funciones puras):**

| Área | Escenario | Validación |
|---|---|---|
| Validación de campos | Evento con todos los campos aditivos presentes | Se acepta y se incluye en el agregado |
| Validación de campos | Evento sin `costo_eur` en un contexto que lo requiere | Se descarta y se incrementa `events_discarded` |
| Cálculo de KPIs | Tres envíos con distintas fechas de entrega | `ontime_delivery_rate` se calcula como (entregas a tiempo / total entregas) × 100 |
| Cálculo de KPIs | Un envío sin `actual_delivery_date` | No se incluye en el numerador ni en el denominador de OTD |
| Agregación por dimensión | Eventos de dos países distintos | Se producen dos filas separadas en `weekly_executive_metrics` |
| Tolerancia a datos vacíos | Conjunto de eventos vacío | Cada función retorna una lista vacía sin lanzar excepción |

**Capa 2 — Pruebas de transformación (mock de `telemetry_events`):**

Cada prueba en esta capa inyecta un DataFrame o lista de eventos simulados directamente en la función de transformación (sin llamar a `fetch_telemetry_events`). El objetivo es validar que la lógica de agregación produce el esquema correcto para cada tabla de destino.

| Test | Input simulado | Output esperado |
|---|---|---|
| `test_build_weekly_metrics_happy_path` | 20 eventos mixtos (envíos, devoluciones, CSAT) de US y ES | 2 filas en `weekly_executive_metrics` con KPIs calculados correctamente |
| `test_build_weekly_metrics_discarded_events` | 20 eventos + 5 eventos sin campos aditivos | `events_discarded = 5`, `events_processed = 20` |
| `test_build_carrier_performance_three_carriers` | Envíos con 3 transportistas distintos (UPS, MRW, DHL) | 3 filas en `carrier_performance` |
| `test_build_client_health_two_clients` | Envíos y CSAT de 2 clientes distintos | 2 filas en `client_health` |

**Capa 3 — Pruebas de integración (upsert contra BD efímera):**

Una sola prueba parametrizada que:

1. Crea una base de datos PostgreSQL temporal (vía `pytest-docker` o `testcontainers`).
2. Crea las tablas del esquema `reporting` con el DDL definido en la Sección 2.
3. Ejecuta la función de upsert para una tabla (ej. `weekly_executive_metrics`) con un conjunto de filas conocido.
4. Verifica que las filas se insertaron correctamente.
5. Vuelve a ejecutar el upsert con los mismos datos.
6. Verifica que las filas se actualizaron sin duplicarse.
7. Destruye la base de datos temporal.

| Test | Propósito |
|---|---|
| `test_upsert_weekly_executive_metrics` | Validar que INSERT + segunda ejecución = UPDATE sin duplicados |
| `test_upsert_carrier_performance` | Validar idempotencia con clave compuesta `(week_start, carrier_id, country)` |
| `test_upsert_client_health` | Validar idempotencia con clave compuesta `(week_start, client_id, country)` |

#### 4.2.3 Mocks

| Dependencia externa | Estrategia de mock | Herramienta |
|---|---|---|
| `telemetry_events` (Supabase) | `unittest.mock.patch` sobre la función `fetch_telemetry_events` para que retorne datos sintéticos en lugar de consultar Supabase | `unittest.mock` / `pytest-mock` |
| Slack API | Mock del Slack Block de Prefect para verificar que se llamó con el mensaje esperado, sin enviar realmente el mensaje | `pytest-mock` + Prefect testing utilities |
| Email | Mock del Email Block de Prefect, análogo a Slack | Prefect testing utilities |
| PostgreSQL (pruebas unitarias) | SQLite en memoria para validar lógica de construcción de consultas SQL sin conexión a Postgres real | `sqlite3` (biblioteca estándar) |
| PostgreSQL (pruebas de integración) | Contenedor Docker PostgreSQL temporal creado y destruido por la prueba | `testcontainers` o `pytest-docker` |

---

### 4.3 Transición a Producción

#### 4.3.1 Estrategia: Shadow Mode (ejecución en paralelo)

El pipeline no reemplazará el proceso manual de los domingos en su primera semana. En lugar de eso, se ejecutará en **shadow mode**: el pipeline corre simultáneamente pero sus resultados no se muestran a Daniel Espinoza hasta que se valide su precisión contra los informes manuales.

**Cronograma del shadow mode:**

| Día | Evento |
|---|---|
| **Jueves (D-3)** | El equipo completa el Hito 2. El Flow `weekly-executive-report` está registrado en Prefect con schedule activo. |
| **Domingo 23:00 UTC** | El pipeline se ejecuta por primera vez en producción. Escribe en `reporting.*` sin que nadie lo consuma todavía. |
| **Domingo 23:30 UTC** | Cada director (Ana, Carlos, Sofía, Valentina, Miguel) prepara su informe manual como siempre. Daniel recibe el informe consolidado manual el lunes a las 7:00 AM. |
| **Lunes 9:00 AM PT** | El equipo de tecnología compara los KPIs del pipeline vs. los KPIs del informe manual. Se documentan las discrepancias. |
| **Lunes 12:00 PM PT** | Reunión post-mortem: si las discrepancias son ≤ 2 % en todos los KPIs, el pipeline se considera validado y se promueve a producción oficial. |

#### 4.3.2 Criterios de validación del shadow mode

| KPI | Diferencia máxima permitida | Acción si se excede |
|---|---|---|
| Volumen global de envíos | 0 % (debe ser exacto) | Revisar la lista blanca de `event_types` |
| Tasa de entrega a tiempo (OTD) | ± 2 puntos porcentuales | Revisar la definición de "ventana prometida" en los eventos |
| Coste operativo | ± 2 % | Revisar la conversión USD/EUR y la clasificación `cost_category` |
| Métricas de devoluciones | ± 2 % | Revisar si hay devoluciones registradas fuera del `event_type` esperado |
| CSAT | ± 0.3 puntos | Revisar si hay encuestas CSAT que no se están capturando |

#### 4.3.3 Plan de despliegue progresivo

| Fase | Duración | Actividad | Riesgo |
|---|---|---|---|
| **Shadow mode** | Semana 1 | Pipeline y proceso manual coexisten. Solo el equipo de tecnología ve los datos del pipeline. | Bajo — Daniel sigue usando el informe manual |
| **Validación** | Semana 2 | Se corrigen las discrepancias identificadas en la fase anterior. Se repite el shadow mode si es necesario. | Medio — pueden requerirse cambios en productores de eventos |
| **Promoción** | Semana 3 | El pipeline se convierte en la fuente oficial del informe semanal. El proceso manual se descontinúa. El dashboard ejecutivo se habilita para Daniel Espinoza. | Alto — primera semana sin respaldo manual |
| **Estabilización** | Semanas 4–6 | Monitoreo intensivo del pipeline, ajuste de umbrales de alerta, optimización de tiempos de ejecución. | Bajo — el pipeline ya es la fuente oficial |

#### 4.3.4 Rollback plan

Si en cualquier momento durante las fases de Promoción o Estabilización se detecta un error crítico en los datos del pipeline:

1. **Inmediato:** El equipo de tecnología desactiva el schedule del Flow en Prefect (un clic en la UI).
2. **En 15 minutos:** Los directores vuelven a preparar el informe manual (proceso conocido, sin automatización).
3. **En 24 horas:** Se corrige la causa raíz, se ejecuta el pipeline manualmente sobre la(s) semana(s) afectada(s) y se rehabilita el schedule.
4. **Compromiso:** Daniel Espinoza nunca recibe un informe con datos incorrectos. Prefiere recibir el informe manual un par de horas tarde antes que un informe automático incorrecto.

---

### 4.4 Resumen del Roadmap

| Hito | Duración | Dependencia | Entregable clave | Puerta de validación |
|---|---|---|---|---|
| **Hito 1** — Core ETL | 2 semanas | Ninguna | `services/reporting/pipeline.py` + queries de upsert | Cobertura de tests ≥ 80 % |
| **Hito 2** — Prefect | 1 semana | Hito 1 | `services/reporting/flow.py` + configuración de bloques | Idempotencia probada (3 ejecuciones → mismo resultado) |
| **Hito 3** — API | 1 semana | Hito 2 | `services/reporting/router.py` + Pydantic models | Endpoints funcionales, datos coinciden con `reporting.*` |
| **Shadow mode** | 1 semana | Hito 2 | Ejecución en paralelo con informe manual | Discrepancias ≤ 2 % en todos los KPIs |
| **Promoción** | Semana 3 | Shadow mode validado | Pipeline como fuente oficial | Daniel Espinoza consume el dashboard |

**Duración total estimada:** 4–6 semanas desde el inicio del Hito 1 hasta la promoción a producción.

---

*Fin de la Sección 4. Esta sección completa el documento de diseño del Pipeline de Inteligencia Ejecutiva de TrackFlow.*

---

## Sección 5: Operación del Pipeline

### 5.1 Ciclo de Reporting Ejecutivo

| Aspecto | Detalle |
|---|---|
| **Frecuencia** | Semanal |
| **Ventana de datos** | Lunes 00:00 UTC — Domingo 23:59 UTC |
| **Ejecución programada** | Lunes a las **7:00 AM (hora del Pacífico / PT)** — equivalente a 14:00 UTC |
| **Consumidor principal** | Daniel Espinoza (CEO) — informe semanal consolidado listo al iniciar la semana laboral |
| **Objetivo de negocio** | Sustituir el proceso manual de los domingos por la noche y entregar KPIs frescos sin intervención humana |
| **Ventana de tolerancia** | Si el pipeline falla, se reintenta automáticamente (3 reintentos con 10s de espera). Si falla de forma permanente, el equipo de tecnología dispone de hasta 15 minutos para activar el plan de contingencia y volver al informe manual. |

**Alineación con Dirección Ejecutiva:** El horario elegido (lunes 7:00 AM PT) garantiza que Daniel Espinoza encuentre el dashboard actualizado con los KPIs de la semana anterior al llegar a la oficina en Los Ángeles. Esto elimina la necesidad de que los 7 directivos dediquen su domingo a consolidar datos manualmente.

### 5.2 Comando de Ejecución

El pipeline está diseñado para ejecutarse directamente desde la terminal. No requiere servicios externos ni servidores Prefect persistentes para el modo de desarrollo y validación.

```bash
# Desde la raíz del repositorio
python data/pipelines/pipeline.py

# O usando uv (entorno virtual gestionado automáticamente)
cd data/pipelines && uv run python pipeline.py
```

> **Nota:** En producción, el flow se registrará en un bloque `Schedule` de Prefect Cloud con la expresión cron `0 14 * * 1` (lunes a las 14:00 UTC = 7:00 AM PT). Durante la fase de desarrollo y pruebas, se ejecuta manualmente con los comandos indicados.

### 5.3 Dependencias

- Python >= 3.11
- Prefect >= 3 (instalado automáticamente vía `uv add "prefect>=3"`)

El entorno virtual se encuentra en `data/pipelines/.venv/` y se gestiona con `uv`:

```bash
cd data/pipelines
uv sync          # Sincroniza dependencias del pyproject.toml
uv add "prefect>=3"   # Añade o actualiza Prefect
```

### 5.4 Flujo de Ejecución (Fases 1–3)

| Paso | Tarea | Decorador | Característica |
|---|---|---|---|
| 1 | `extraer_telemetria()` | `@task(retries=3, retry_delay_seconds=10)` | Resiliencia ante fallos de red de los almacenes |
| 2 | `transformar_a_kpis()` | `@task(cache_key_fn=..., cache_expiration=1h)` | Caché para evitar recálculos en la misma hora |
| 3 | `cargar_resultados()` | `@task(retries=3, retry_delay_seconds=10)` | Upsert idempotente sobre (fecha_reporte, id_corrida) |
| 4 | `notificar_estado()` | `@task` (invocada con `return_state=True`) | Snapshot no crítico — falla sin romper el pipeline |

### 5.5 KPIs Generados

| KPI | Valor (ejemplo) |
|---|---|
| Volumen de envíos (total) | 2 |
| Volumen Los Ángeles / Zaragoza | 1 / 1 |
| Tasa de entrega a tiempo | 50.0 % |
| Devoluciones (volumen) | 2 |
| Tasa de devoluciones | 100.0 % |

---

*Fin de la Sección 5. Esta sección completa la documentación operativa del Pipeline de Inteligencia Ejecutiva de TrackFlow e incluye el ciclo de reporting, el comando de ejecución y la alineación con la Dirección Ejecutiva.*
