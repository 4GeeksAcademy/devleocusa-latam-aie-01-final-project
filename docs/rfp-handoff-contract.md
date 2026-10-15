# Contrato de handoff RFP → Parte 2

Este documento define el contrato por el cual el flujo de **recepción y enrutamiento de RFPs (Parte 1)** entrega un ticket analizado al siguiente tramo del flujo agéntico (generación de la propuesta, Parte 2).

**No existe un segundo API.** La cola es la propia PostgreSQL (Supabase): la Parte 2 debe tomar tickets pendientes con una query y marcarlos como despachados.

## Cola (fuente de verdad)

```sql
SELECT id, handoff_payload
FROM rfp_tickets
WHERE status = 'analisis_completo'
  AND dispatched_at IS NULL
ORDER BY created_at;
```

Al tomar un ticket, la Parte 2 lo marca:

```sql
UPDATE rfp_tickets SET dispatched_at = now() WHERE id = :ticket_id;
```

El flag `dispatched_at` evita que dos consumidores tomen el mismo ticket (claim atómico con `UPDATE ... WHERE dispatched_at IS NULL RETURNING id`).

## Payload (`rfp_tickets.handoff_payload`, JSON)

```jsonc
{
  "ticket_id": "uuid-del-ticket",
  "markdown_path": "data/raw/<ticket_id>/<nombre>.md",   // referencia; NO re-parsear el PDF
  "synthesizer_summary": "Resumen para Ventas: qué pide el cliente, a qué plazo, qué le toca a cada departamento y a quién pedírselo.",
  "contradicciones": [
    { "tema": "volumen mensual", "version_a": "Operaciones leyó 5.000 pedidos/mes", "version_b": "Comercial leyó 10.000 paquetes/mes" }
  ],
  "workstreams": [
    {
      "department": "operaciones_almacen",          // clave del catálogo (7 deptos de TrackFlow)
      "contact_name": "Ana Whitfield",              // responsable interno del CONTEXT
      "contact_role": "Directora de Operaciones de Almacen",
      "key_aspects": {
        "resumen_requisitos": "...",
        "entregables": ["..."],
        "cifras_citadas": [ { "valor": "15.000 SKUs", "contexto": "alcance, sección 2" } ],
        "restricciones_exclusiones": ["No se requiere gestión de transportistas"],
        "preguntas_abiertas": ["¿Volumen mensual de pedidos?"],
        "missing_data": ["Volumen mensual de pedidos"],
        "prioridad": "alta"
      }
    }
  ]
}
```

## Garantías del contrato

1. **Sin reparsear el PDF**: `workstreams[].key_aspects` y `synthesizer_summary` contienen todo lo necesario. `markdown_path` existe y apunta al Markdown convertido (MarkItDown) si se necesita profundizar.
2. **Cifras literales**: `cifras_citadas[].valor` es texto copiado literalmente del documento. Los huecos están en `missing_data`, nunca inventados.
3. **Contactos**: `contact_name` / `contact_role` son el responsable interno de TrackFlow (catálogo del CONTEXT-company.md), no el contacto del cliente. El contacto del cliente vive en `rfp_documents` (`contact_name`, `contact_email`).
4. **Contradicciones**: nunca se fusionan cifras en conflicto; se listan en `contradicciones` para que Ventas/la Parte 2 las resuelva.
5. **Idempotencia**: reprocesar un ticket (CLI `scripts/rfp_intake.py reprocess`) limpia y reescribe `rfp_documents` y `rfp_department_sections` antes de persistir; `handoff_payload` se sobrescribe.

## Estados del ticket (Parte 1)

| Estado | Significado |
| --- | --- |
| `analizando` | Subida aceptada; conversión + agentes en curso |
| `descartado` | El clasificador rechazó el documento (o error de proceso; ver `error_detail`) |
| `analisis_completo` | El synthesizer terminó; Ventas puede leer los aspectos clave por departamento |

> `esperando_aprobacion` pertenece a la Parte 2 y NO existe en esta fase.
