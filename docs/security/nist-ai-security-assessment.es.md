# Evaluación de seguridad de IA — NIST CSF para TrackFlow

**Fecha:** 2026-10-27. **Estado:** auditoría de código/documentación y pruebas locales; no pentest externo ni verificación de producción. El endurecimiento SSH queda fuera de este ciclo, por estar atendido por Operaciones según el responsable del proyecto. Véase `ai-inventory.es.md` para inventario y responsables; `owasp-audit.es.md` para evidencias OWASP y `server-hardening.es.md` para estado de red/host.

## Contexto regulatorio y datos

- **RGPD (España/UE):** TrackFlow opera entre Zaragoza y Los Ángeles. Ante una brecha de datos personales que probablemente suponga riesgo para derechos y libertades, evaluar y notificar a la **AEPD dentro de 72 horas** desde que se tenga constancia, conforme a las obligaciones aplicables; documentar también brechas aunque no se notifiquen.
- **CCPA/CPRA (California):** atender derechos aplicables de acceso, eliminación y opt-out; preparar notificación de brechas de forma razonablemente rápida según ley aplicable y asesoría legal.
- Datos de mayor sensibilidad: contacto y direcciones de destinatarios B2C; contratos, tarifas/volúmenes e incidentes confidenciales de marcas B2B; credenciales de couriers y tokens.
- Validar base legal, roles responsable/encargado, transferencias internacionales, contratos y excepciones con Legal/Privacidad. Esta evaluación técnica no es asesoría jurídica.

## Resumen de estado

Hay guardrails explícitos en el agente, prompts con separación de roles y contenido marcado como no confiable, validación de salida, tools MCP con OAuth y trazas con metadatos sin pregunta/respuesta. Se añadieron barreras por rol: RAG/chat para `ADMIN`/`MANAGER`; lectura/cambio de estado de incidencias para operadores y rol `SERVICE` dedicado (con scopes MCP por tool); alta de incidencia/análisis CSV solo para operadores. Los usuarios `USER` reciben denegación. Esto limita acceso de cuentas de cliente, pero **no constituye aislamiento B2B por tenant**: no existen relaciones usuario–tenant ni etiquetas de tenant en incidencias/corpus, y los roles permitidos conservan alcance global. Sign-off sigue **bloqueado**: aislamiento B2B/B2C end-to-end no demostrado; las acciones logísticas irreversibles del briefing no están implementadas/demostradas con aprobación humana; y entorno productivo/TLS/secret manager y pruebas reales de Redis requieren validación.

## NIST CSF: acciones y brechas priorizadas

| Función | Estado/evidencia | Acción concreta priorizada | Responsable | Prioridad |
|---|---|---|---|---|
| **Govern** | Inventario y responsables propuestos en `ai-inventory.es.md`; terceros/proveedores se asignan como responsabilidad compartida. | Aprobar política de IA, owners y matriz de autorización; establecer aprobación humana autenticada y auditable como gate obligatorio para cada acción irreversible. No habilitar la acción si el gate no existe. | CTO + Compliance + Operaciones | P0 |
| **Identify** | Inventario de agentes, RAG, MCP, memoria, workflows, API y dashboard documentado; clasificación de datos B2C/B2B y límites de implementación anotados. | Completar mapa de flujo de datos/tenant por endpoint, cada courier/proveedor y repositorio; verificar aislamiento con pruebas negativas B2C y B2B. | Plataforma + Datos + Privacidad | P0 |
| **Protect** | Gates por rol en API de incidencias, RAG y WebSocket; `USER` recibe 403. `SERVICE` es rol explícito para MCP y no se asigna automáticamente. No hay scoping tenant. Además: guardrails, salida validada, rate limit y `SECRET_KEY` requerida. | Modelar identidad y pertenencia a tenant de fuente autoritativa, etiquetar registros y filtrar en origen antes de recuperar/usar; mantener permisos de herramienta mínimos y HITL para impacto. | Plataforma/SRE + Seguridad | P0 |
| **Detect** | Trazas estructuradas por `run_id`, nodos, rutas, número de resultados y eventos guardrail; logs no guardan pregunta/respuesta. Resumen guardrail en memoria es local al proceso. | Enviar eventos de seguridad a colector duradero con alertas por abuso, 429, denegaciones, acceso multi-tenant y errores OAuth; definir retención y redacción de PII. | SRE + Seguridad | P1 |
| **Respond** | Hay métricas de guardrail pero no se acreditó un runbook completo específico para IA. | Crear playbook para fuga B2C/B2B, compromiso de secreto/courier, prompt injection con tool call y abuso de coste; incluir contención, preservación de evidencia y análisis RGPD/AEPD 72h y CCPA/CPRA. | Seguridad + Compliance + CTO | P0 |
| **Recover** | No se verificó prueba de restauración ni RTO/RPO de Postgres, Qdrant, trazas o memoria en producción. | Definir RTO/RPO, backups cifrados e inmutables, revocación/rotación de credenciales y prueba periódica de restauración con reindexado del RAG y revisión de memoria contaminada. | SRE + Datos | P1 |

## Hallazgos abiertos y mitigación

| Brecha | Riesgo | Mitigación priorizada | Estado |
|---|---|---|---|
| No se demostró ACL de pedido B2C por usuario ni aislamiento de datos/documentos B2B por tenant en todo el recorrido del agente. Los gates por rol añadidos no cambian este hecho. | Exposición de direcciones, contactos, incidentes o contratos entre clientes/tenant; usuarios autorizados de operador mantienen acceso global. | P0: ACL en backend/tool antes de recuperar; tenant derivado de identidad autorizada, nunca del prompt; migrar relaciones/etiquetas y ejecutar tests A→B con IDs directos y retrieval. | Abierta; no anunciar lookup B2C ni aislamiento entre marcas como existente. |
| No se identificó motor de aprobación automática de devoluciones ni se demostraron gates para despacho alto valor/cambio carrier en tránsito/divulgación entre marcas. | Pérdida económica, fraude o incumplimiento contractual. | P0: bloquear implementación/activación hasta contar con policy engine determinista + aprobador humano explícito con identidad, umbral, motivo y auditoría; pruebas de denegación por defecto. | Requisito pendiente; no afirmar confirmado. |
| Revisión exhaustiva de todos los secretos no certificada por escáner; `.env.example` existe y se amplía; SQL/reset secret van por env. | Toma de cuentas, courier/API o acceso a datos. | P0: escaneo SAST/secret scan del historial; rotar toda credencial expuesta; vault en producción, permisos mínimos, sin secretos en build/log. | Pendiente escaneo completo; un patrón antiguo conocido fue eliminado del código activo de reset. |
| Rate limiting es Redis compartido, pero no hay evidencia aún de integración/despliegue operativo ni prueba real contra Redis. | Loops/coste de modelo y denegación de servicio. | P0: desplegar variables Redis/límites, observar 429 y 503 fail-closed, probar concurrencia/multiworker. | Código y pruebas locales añadidos; ejecución pendiente en este reporte. |
| Trazas en archivo/local y resumen guardrail en memoria del proceso no proporcionan retención/alertas multiworker. | No detectar abuso o pérdida de evidencia. | P1: colector persistente, acceso restringido, retención mínima y alertas sin almacenar contenido sensible. | Parcial. |
| TLS, vault, headers en edge, dependencias, SSRF y backup/restore productivos no verificados aquí. | Interceptación, explotación de dependencia, acceso a servicios internos o recuperación fallida. | P1: validar entorno de staging/producción, escaneo SCA/SAST, pruebas SSRF controladas, restauración y evidencia del proxy TLS. | Pendiente. |

## Evidencias reproducibles previstas/añadidas

- Prompt injection directo en `services/api/tests/test_knowledge_router_agent.py`: comprueba que “Ignora tus instrucciones…” obtiene respuesta de rechazo y no llega a clasificador, retrieval ni generación. Ejecutar la suite para confirmar el resultado.
- Rate limit: pruebas del endpoint que comprueban `429` + `Retry-After`, fallo del limiter `503`, y ventana/per-usuario en `test_agent_rate_limit.py`. Requiere ejecutar tests; integración con Redis real aún pendiente.
- Trazabilidad del agente: `services/api/tests/test_agent_invocation.py` ya verifica nodos, tool route y ausencia de pregunta/respuesta/datos de ticket en la traza. Ejecutar como parte del sign-off.
- Gestión de `SECRET_KEY`: test nuevo de fail-closed en reset y pruebas existentes de auth.

**Validación de esta implementación (2026-10-27):** pruebas dirigidas API (conocimiento, WebSocket, incidencias y auth): **116 passed**; MCP: **9 passed**. La suite completa API produjo **322 passed, 1 failed** porque `services/api/tests/test_agent_graph.py` espera el URL por defecto OpenAI, mientras que el `.env` local establece `GENERATION_BASE_URL=https://llm.4geeks.ai`; no es una regresión de autorización. `git diff --check` y `docker compose config --quiet` finalizaron correctamente. Estas pruebas por rol no prueban acceso cruzado entre tenants.

**Sign-off:** no conceder hasta completar P0 de ACL tenant, confirmar aprobación humana en cada acción irreversible habilitada, cerrar resultados de tests y revisión de secretos; además verificar el despliegue productivo correspondiente. SSH se excluye de esta auditoría técnica por instrucción del solicitante; no se certifica aquí.
