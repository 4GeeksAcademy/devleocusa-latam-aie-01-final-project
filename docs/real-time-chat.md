# Chat en tiempo real — Parte 2

## Qué se implementó

- Se añadió `WebSocket /chat/ws/{session_id}?token=<JWT>` al backend FastAPI. Reutiliza el JWT de la API, valida el identificador y la propiedad de la sesión antes de aceptar mensajes.
- La conexión utiliza el agente existente `first_line_cx` mediante `invoke_agent`; no se creó un agente paralelo ni se sustituyó su routing, memoria, guardrails o herramientas. El mismo `session_id` se pasa como `run_id` y, por tanto, como `thread_id` de LangGraph.
- La generación JSON existente ahora puede ejecutarse en modo stream para el chat. Un parser incremental extrae el campo `answer` y publica únicamente texto del usuario, sin exponer fragmentos JSON de `proposal`.
- Se incorporó pub/sub por sesión en memoria: un productor comparte eventos con todas las conexiones suscritas, sin que cada socket vuelva a invocar el agente.
- Sesiones e historial de mensajes se guardan en TinyDB. El snapshot de conexión devuelve el historial; si hay una respuesta `streaming`, devuelve el parcial con su watermark `sequence` y el cliente reemplaza su copia local en vez de duplicar texto.
- La UI `/knowledge` usa WebSocket, conserva `session_id` en `localStorage`, representa los chunks incrementalmente, reconecta con backoff y permite enviar una nueva pregunta mientras se genera una respuesta.
- En una redirección se fija la señal de cancelación, se cierra la respuesta activa del proveedor si está disponible y se espera a que la generación anterior termine antes de emitir `generation_interrupted` e iniciar el nuevo turno. El parcial queda persistido con estado `interrupted`.

## Contrato de eventos

Todos los frames usan `{ "event": "...", "data": { ... } }`.

- Entradas: `user_message` (`session_id`, `text`) e `interrupt_requested` (`session_id`, `new_input`).
- Salidas: `session_snapshot`, `user_message`, `interrupt_requested`, `token_chunk`, `generation_interrupted`, `generation_completed` y `chat_error`.
- `token_chunk` identifica `message_id` y `sequence`; en la reanudación de un parcial incluye `replace: true` para reemplazar el texto de ese mensaje.

## Preguntas de Diseño — decisiones y respuestas

1. **¿Por qué WebSocket y no SSE?** El flujo es bidireccional: el servidor envía chunks mientras el cliente necesita poder enviar una interrupción/redirección en esa misma conversación persistente. SSE es unidireccional servidor→cliente y requeriría otro canal de entrada.
2. **¿Cómo se evita duplicar invocaciones con varios sockets?** Hay un productor por sesión y un canal pub/sub `chat.<session_id>`. Los sockets suscritos son consumidores; la suscripción no crea una invocación adicional del agente.
3. **¿Cómo se autentica y aísla una sesión?** El handshake acepta el mismo JWT de la API mediante `?token=`. Antes de aceptar, se valida token, formato de `session_id` y propiedad de la sesión. La entidad usa `agent_id="first_line_cx"`; `client_id` se iguala al usuario autenticado porque no existe una entidad de cliente separada en el modelo actual.
4. **¿Cómo se recupera el contexto al reconectar?** `session_id` es también el `thread_id` de LangGraph. TinyDB proporciona el snapshot durable local de mensajes; una respuesta activa se rehidrata como parcial con secuencia. El runtime LangGraph de producción usa su checkpointer PostgreSQL para estado del grafo. El historial TinyDB por sí solo no sustituye ese checkpointer ni reconstruye estado semántico.
5. **¿Cómo funciona una interrupción y por qué no es HITL?** No se usa `LangGraph interrupt()` (HITL/pausa para reanudación). La redirección señala cancelación al stream, solicita cerrar la respuesta activa y espera la salida de la generación; conserva el texto parcial, emite `generation_interrupted` y solo entonces comienza el turno nuevo.
6. **¿Qué garantías y límites de escalado tiene pub/sub?** El mecanismo en memoria distribuye eventos entre sockets del mismo proceso y cumple el despliegue de una instancia. No sincroniza workers ni réplicas; para escalar horizontalmente hay que sustituirlo por Redis u otro backplane compartido.
7. **¿Qué se persiste y qué protección se aplica?** TinyDB conserva las entidades de sesión y los mensajes, incluyendo estado y secuencia; se reutiliza el JWT, no un token nuevo del chat. El token de query string es sensible: no debe registrarse y se requiere `wss` fuera de desarrollo local.

## Cómo probar streaming e interrupción manualmente

### Preparación

1. Configura las variables de entorno habituales del API, incluyendo las credenciales/base URL/modelo del proveedor de generación.
2. Arranca API y backoffice según el flujo de desarrollo del repositorio; inicia sesión en el backoffice y abre `/knowledge`.
3. En el navegador, abre DevTools → Network → WS y selecciona `/chat/ws/<session_id>?token=...`. Confirma que el primer frame recibido sea `session_snapshot`.

### Streaming incremental

1. Envía una pregunta TrackFlow que requiera una respuesta sustantiva (por ejemplo, sobre la política de devoluciones o SLAs).
2. En Frames/Messages del WebSocket y en la UI, observa varios `token_chunk` para el mismo `message_id`, con `sequence` creciente; el texto debe aparecer antes de que termine la generación.
3. Confirma al final `generation_completed` y que el mensaje persista con `status="completed"`.

### Interrupción y redirección

1. Envía una pregunta que produzca una respuesta suficientemente larga; espera a ver los primeros `token_chunk`.
2. Antes de `generation_completed`, envía otra pregunta desde el campo de chat. La UI detecta que hay generación activa y transmite `interrupt_requested` con `new_input`.
3. Confirma que el mensaje anterior conserva su texto parcial y termina en `generation_interrupted`/`status="interrupted"`; luego llega el `user_message` del nuevo turno y una respuesta asociada a la redirección.
4. No debe haber chunks de la respuesta anterior después de `generation_interrupted`. El nuevo turno debe comenzar después de detener la generación anterior.

### Reconexión, múltiples consumidores y autenticación

- Reconexión: durante una respuesta activa, recarga/reconecta manteniendo la misma sesión. `session_snapshot` debe contener el parcial `streaming` y después llega `token_chunk` con `replace: true` y el watermark persistido. También revisa que el hilo continúe con el mismo `session_id`/`thread_id`.
- Múltiples consumidores: abre una segunda conexión autenticada con el mismo `session_id`, envía una sola pregunta y confirma que ambos reciben los mismos chunks sin una segunda ejecución del agente.
- Autenticación: prueba token ausente/inválido/expirado y una sesión propiedad de otro usuario. El servidor debe rechazar el handshake antes de `session_snapshot`.

## Pruebas automatizadas

Desde `services/api`:

```bash
pytest tests/test_chat_pubsub.py tests/test_chat_websocket.py tests/test_auth.py -q
```

Las pruebas cubren el parser incremental, la entrega pub/sub, handshake/snapshot, la restauración real del parcial en la conexión WebSocket, persistencia del parcial al interrumpir y el orden `original_stopped → generation_interrupted → redirect_started`. La prueba de orden usa una generación controlable; no es una prueba contra el proveedor LLM externo.

Desde `uis/backoffice`:

```bash
npm run lint && npm run build
```

## Limitaciones conocidas

El cierre del stream síncrono del SDK detiene la lectura local y solicita cerrar la respuesta activa. La suite demuestra la coordinación y el orden con generadores controlables, pero no garantiza que el proveedor externo cancele inmediatamente el cómputo remoto: validar ese comportamiento con el proveedor/configuración de despliegue. El pub/sub solo cubre un proceso. El `client_id` permanece ligado al `user_id` hasta que el modelo incorpore una entidad cliente explícita.
