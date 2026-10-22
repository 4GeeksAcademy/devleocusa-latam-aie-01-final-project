# Chat en tiempo real (Parte 2)

Pruebas backend específicas:

```bash
cd services/api
pytest tests/test_chat_pubsub.py tests/test_chat_websocket.py tests/test_auth.py -q
```

La suite específica cubre extracción incremental del `answer`, publicación pub/sub, autenticación/snapshot, rehidratación del parcial en un WebSocket reconectado, persistencia del texto parcial y orden de parada antes del turno redirigido. Para la prueba manual, inicia sesión en `/knowledge`, verifica los `token_chunk` crecientes en DevTools → Network → WS y envía otra pregunta antes de que termine la respuesta; debe llegar `generation_interrupted` antes de que empiece el turno nuevo. Las pruebas automatizadas no garantizan que un proveedor externo detenga inmediatamente el cómputo remoto al cerrar el stream.

# Guía de Pruebas - TrackFlow Tech

Este documento define la estrategia de pruebas unitarias para nuestros sistemas, garantizando la fiabilidad de las operaciones logísticas y de usuario.

## 1. Módulo de Autenticación (AUTH-088)
*   **Cobertura Objetivo:** 70%
*   **Enfoque:** Lógica de negocio pura (tokens, hashing), sin serialización HTTP.
*   **Comando:** `uv run pytest tests/auth/ -v --cov=app.auth`

## 2. API del Backoffice (API-042)
*   **Cobertura Objetivo:** 60%
*   **Módulos Evaluados:** Endpoints de Gestión de Inventario (SGA) y Asignación de Transportistas.
*   **Enfoque:** 
    *   *Camino Feliz:* Retorno correcto de stock por SKU, asignación exitosa de ruta.
    *   *Casos Límite:* Consultas de stock masivas, SKU con caracteres especiales.
    *   *Modos de Fallo:* Solicitud de stock en almacén inexistente, transportista no disponible.
*   **Comando:** `uv run pytest tests/backoffice/ -v --cov=app.backoffice`

## 3. Utilidades del Frontend (FE-019)
*   **Cobertura Objetivo:** 80% (Funciones de alta reutilización)
*   **Módulos Evaluados:** Validadores de formularios, formateadores de fechas logísticas, parsers de respuestas de la API.
*   **Enfoque:** Pruebas de camino feliz y modo de fallo por cada helper.
*   **Comando:** `npx jest --coverage`