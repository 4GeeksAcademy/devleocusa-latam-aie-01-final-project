# Notificaciones RFP en tiempo real

## Contrato y activación

El endpoint autenticado `GET /rfp/events` emite `event: rfp_ticket_created` después de que el clasificador existente confirma que el PDF es una RFP válida. El `data:` es un objeto JSON plano con `ticket_id`, `rfp_id`, `client_name`, `client_country`, `services_requested`, `status: "analyzing"` y `created_at`. Los valores de identificación y metadatos se extraen del ticket o de la metadata de ingesta; si un campo opcional no aparece en el documento, se envía `null` en lugar de inventarlo. La fuente de verdad de tickets continúa siendo PostgreSQL de Supabase, a través de SQLModel.

La conexión requiere el mismo JWT que el backoffice (`Authorization: Bearer ...`). El cliente usa `fetch` y `ReadableStream`, pues `EventSource` no permite de forma limpia añadir ese header.

## Reconexión y recuperación

El cliente reintenta fallos usando backoff exponencial, desde 1 segundo hasta un máximo de 30 segundos. Cada reconexión refetch la lista desde la API/Supabase y la combina con la UI usando el identificador `ticket_id`/`id` como clave única. Los eventos recibidos por SSE también se deduplican por ese identificador. Así los tickets creados durante una caída se recuperan y el mismo ticket no aparece dos veces. Los eventos SSE son avisos de alta; el estado de procesamiento de tickets se refresca separadamente.

## Conexiones y escalabilidad

Cada navegador mantiene una conexión SSE independiente; cada API replica mantiene sus streams locales y una suscripción Redis al canal `trackflow:rfp:events:v1`. Redis Pub/Sub propaga cada aviso entre procesos/replicas, y cada proceso lo distribuye a sus conexiones SSE locales. El evento lleva un identificador de origen para no volver a entregar en la instancia que lo publicó. Redis se usa como transporte efímero y no como fuente durable.

La API usa la variable existente `REDIS_URL` y reconecta el suscriptor Redis cuando Redis está temporalmente inaccesible. Si Redis se cae, los SSE se cierran para que el dashboard aplique backoff y recupere la lista desde Supabase al reabrir. El publicador intenta distribuir en Redis sin bloquear la persistencia: si Redis falla, la instancia local aún puede avisar a sus propios clientes y los demás clientes recuperan tickets mediante la lectura durable de Supabase.

Las colas locales tienen capacidad finita. Un cliente lento puede perder avisos transitorios; la recuperación por lista de tickets en Supabase cubre ese caso. Al abrir (inicial o reconexión), el cliente primero establece la suscripción SSE y luego consulta la lista durable antes de empezar a consumir frames; así cubre los tickets creados antes y durante el snapshot, deduplicando por ID. La implementación ofrece recuperación de estado/tickets, no garantía de entrega individual de cada mensaje (para ello se necesitaría un outbox y broker durable como Redis Streams).

La API inicia/cierra el cliente Redis dentro del lifespan de FastAPI. En Docker Compose ya se define `REDIS_URL=redis://redis:6379/0`; para despliegues fuera de Compose, configurar `REDIS_URL` hacia el servicio Redis compartido. No se requiere cambiar la configuración de Supabase: PostgreSQL sigue siendo la fuente de verdad.

## SSE frente a WebSockets

SSE es adecuado porque el flujo es unidireccional: el servidor avisa al dashboard de una RFP nueva. HTTP estándar, reconexión del cliente y eventos nombrados satisfacen el caso. Si los usuarios tuvieran que aceptar, reclamar o cambiar el ticket en el mismo canal bidireccional, WebSockets podría ser más apropiado; las mutaciones de negocio actuales deben seguir protegidas por endpoints HTTP autenticados.

## Verificación manual de recuperación

1. Iniciar sesión y abrir la bandeja RFP; confirmar el indicador de conexión SSE.
2. Interrumpir la red del navegador o bloquear temporalmente la API. El indicador debe mostrar reconexión.
3. Mientras el navegador está desconectado, registrar una RFP válida desde otro cliente.
4. Restaurar la conexión. El cliente debe reintentar con backoff y refetch la lista.
5. Confirmar que el nuevo ticket aparece una vez y que los eventos nuevos posteriores también se incorporan sin recargar la página.
6. Confirmar en el panel de red que `GET /rfp/events` lleva `Authorization: Bearer ...`.

La implementación no invoca modelos ni agentes nuevos para notificar: se engancha al resultado de clasificación ya producido por el pipeline.