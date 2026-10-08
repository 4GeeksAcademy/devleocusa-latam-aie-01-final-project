# Memoria del agente TrackFlow

## Política y alcance

La política funcional está definida por [`MEMORY-trackflow.es.md`](../MEMORY-trackflow.es.md). La memoria es episódica, por usuario autenticado, de capacidad pequeña y con consentimiento explícito. No es el RAG corporativo ni una fuente autoritativa de verdad operativa. Se almacena en tablas PostgreSQL dedicadas (`agent_memory_proposals`, `agent_approved_memories`, `agent_memory_decisions`), separadas del checkpoint y de Qdrant/colecciones `*_knowledge`.

Solo se admiten estas categorías:

1. **Correcciones de carrier**: cambio de cobertura o asignación, agrupado por carrier + país y, cuando importe, zona. La clave estable identifica la regla, no el ticket.
2. **Contexto de incidencias recurrentes**: patrón contextual respaldado por más de un caso, con `repetition_count >= 2`. No se registra el incidente puntual ni su identificador de paquete.
3. **Preferencias de reporte B2B recurrente**: formato, orden o métricas de informes mensuales para la cuenta B2B correspondiente.

Nunca se guardan direcciones exactas ni ubicaciones sensibles de clientes B2B o B2C, rutas internas de almacén, incidencias aisladas de un paquete, ni información de contratos/negociaciones comerciales activos. Tampoco credenciales, contactos o identificadores gubernamentales. Consultas puntuales de tracking, cierres conversacionales y traducciones de un solo uso no generan propuestas.

## Anti-envenenamiento y validación

La generación estructurada limita la propuesta a la taxonomía anterior. El validador de servidor vuelve a comprobar categoría, señales de alcance, recurrencia y patrones prohibidos; la propuesta del LLM no constituye autorización. El usuario debe aprobar explícitamente el texto pendiente. Rechazo, incertidumbre, cambio de tema o fallo del clasificador cierran sin consolidar; las ediciones se retiran y requieren una nueva aprobación.

Las afirmaciones sobre cobertura o causas de incidentes son aportes no verificados del usuario. Se recuperan como contexto de memoria, nunca como evidencia corporativa: antes de presentarlas como hecho o ejecutar una decisión operativa se deben contrastar con RAG/MCP y las fuentes vigentes. No se debe permitir que el contenido memorístico modifique políticas compartidas, SLA, tarifas o controles de seguridad. La persistencia no escribe en Qdrant.

Se guardan decisiones/auditoría sin retener texto original libre de usuario; se limita y sanea el motivo de propuesta. Una clave de memoria debe ser estable y no puede incluir tracking, contactos o datos de ubicación sensible. Restricciones SQL aíslan cada entrada por `user_id`, limitan a una propuesta pendiente y consolidan por `memory_key`, preservando cada propuesta/decisión como historial de auditoría. El mismo turno que ofrece una propuesta pregunta en el mismo canal de conversación si debe recordarla, antes de persistirla como pendiente.

## Ciclo de vida y retención

La misma llamada estructurada produce respuesta y propuesta opcional, sin escritura inmediata. La capa de invocación persiste la propuesta después de generar la respuesta. En el turno siguiente se clasifica explícitamente frente a la única propuesta pendiente del usuario. Solo `approve` crea o actualiza el recuerdo aprobado.

- Propuestas: vencen por defecto a los 7 días (`AGENT_MEMORY_PROPOSAL_TTL_DAYS`).
- Recuerdos aprobados: vencen por defecto a los 180 días (`AGENT_MEMORY_TTL_DAYS`).
- Máximo: 20 recuerdos activos por usuario; los expirados se eliminan de la tabla activa.
- La auditoría de propuesta/decisión permanece. Una consolidación actualiza la entrada lógica por `memory_key` y conserva los eventos vinculados a sus propuestas. La clave canónica es por usuario y tipo/entidad: carrier+país+zona; cuenta B2B para reportes; región/patrón recurrente para incidentes.
- Las entradas legadas de la versión provisional quedan fuera de recuperación tras la migración de esquema.

## Casos representativos

**Proponibles:** “SEUR ya no cubre esa zona rural de Zaragoza; usar el carrier local” (ámbito ES, clave SEUR+país+zona); “tres tickets muestran retrasos por la huelga portuaria” (incidente recurrente); “el cliente B2B recurrente prefiere devoluciones primero en su reporte mensual”.

**No proponibles:** “¿Dónde está el paquete XJ4471?”, “Perfecto, ya quedó resuelto”, “Tradúceme esto”, una sola queja por un paquete, una dirección de destinatario, una ruta de pasillo/almacén o un término de renovación todavía en negociación.

Las tres categorías proponibles y los cinco ejemplos negativos anteriores son también los ejemplos de evaluación funcional de la taxonomía; el generador debe emitir `proposal=null` para los negativos.

## Ciclos de evidencia de aceptación

Estos ciclos se ejecutaron contra Supabase con `PostgresAgentMemoryStore`, dentro de un esquema aislado creado en una transacción que terminó en `ROLLBACK`. Se verificaron escritura, resolución, recuperación y auditoría sin dejar filas ni objetos persistentes. La prueba llama al store con la decisión ya clasificada; no ejercita el LLM clasificador ni el endpoint HTTP completo.

### Ciclo aprobado
1. En una conversación, el agente identifica una corrección candidata: «SEUR ya no cubre la zona rural de Zaragoza; usa carrier local».
2. En la misma respuesta informa la regla normalizada y pregunta si debe recordarla; crea una propuesta `pending` asociada al `user_id`, con ámbito carrier/ES/zona.
3. El usuario contesta «Sí, guarda esa regla». El clasificador estructurado devuelve `approve` y `explicit_confirmation=true` únicamente si se refiere inequívocamente a esa propuesta.
4. En transacción se actualiza estado `approved`, se inserta evento `approved` en `agent_memory_decisions` y se crea/actualiza la clave lógica. En turnos futuros se recupera solo para ese usuario, como contexto no autoritativo.

### Ciclo rechazado
1. En la misma conversación el agente propone una preferencia B2B segura de orden de informe y pregunta si debe recordarla; queda `pending`.
2. El usuario responde «No, no la guardes». El clasificador devuelve `reject`.
3. La propuesta pasa a `rejected`, se inserta evento `rejected` con timestamp y no se modifica `agent_approved_memories`.

Silencio no produce un evento inmediato; al vencer los 7 días, limpieza pasa la propuesta a `expired` y añade resultado `rejected` por defecto. Ambigüedad o error de clasificación se cierra como `rejected` sin persistencia aprobada.

### Resultado de ejecución en Supabase (2026-10-08)
- Aprobado: estado final `approved`, recuerdo recuperable para el mismo usuario y evento `approved` en `agent_memory_decisions`.
- Rechazado: estado final `rejected`, ningún recuerdo nuevo aprobado y evento `rejected` en `agent_memory_decisions`.
- Aislamiento: tablas e índices se crearon en un esquema de prueba; la transacción completa se revirtió al terminar.
- No cubierto por esta prueba: clasificación LLM/HTTP completa, migración sobre una instalación legada poblada, concurrencia del índice único ni limpieza de datos vencidos reales.

## Restricciones corporativas

No se encontró `CONTEXT-company.md` en el repositorio inspeccionado. Por ello, las restricciones concretas disponibles en esta entrega se derivan del guardrail explícito [`MEMORY-trackflow.es.md`](../MEMORY-trackflow.es.md): no memorizar direcciones/ubicaciones de clientes B2B o B2C ni rutas internas de almacén; tampoco casos de paquete sin patrón ni negociaciones comerciales activas. Al incorporarse `CONTEXT-company.md`, se debe cotejar y ampliar esta lista antes de cambiar la allowlist. Ninguna regla de la memoria sustituye los controles de seguridad de empresa.

## Límite de validación

Las expresiones de servidor son controles deterministas de defensa en profundidad, no detección semántica completa. La generación debe descartar lo dudoso. Antes de producción aún se recomienda probar el flujo completo clasificador/HTTP, migración desde el esquema legado, concurrencia de propuestas y expiración con datos de integración.
