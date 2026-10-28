# Endurecimiento de servidor — TrackFlow

**Estado:** guía operativa y baseline del repositorio; el host real no ha sido verificado ni modificado por esta implementación. No es evidencia de que SSH, usuario o firewall estén ya endurecidos.

## Baseline reproducible del repositorio (2026-10-23)

`docker-compose.yml` publica actualmente estos puertos en el host:

| Puerto | Servicio | Política objetivo de producción |
|---:|---|---|
| 8000 | API FastAPI | Enlace `127.0.0.1` para desarrollo; producción privada tras proxy TLS. |
| 8001 | MCP | Sin publicación al host; red interna del agente solamente. |
| 8080 | Keycloak dev | Sin publicación al host; red interna solamente. |
| 3000 / 3001 | Website / backoffice Next dev | Enlace `127.0.0.1`; no exponer modo dev en producción. |
| 6379 | Redis | Enlace `127.0.0.1`; servicio interno solamente. |
| 5555 | Flower | Enlace `127.0.0.1`; acceso administrativo local solamente. |
| 6333 / 6334 | Qdrant HTTP/gRPC | Enlace `127.0.0.1`; servicio interno solamente. |

Verificación de línea base: `grep -nE '^[[:space:]]*ports:|^[[:space:]]*- "?[0-9]+:[0-9]+' docker-compose.yml`.

Compose se identifica en su encabezado como orquestación de **desarrollo local** y ejecuta `next dev`/Keycloak `start-dev`. Sus publicaciones se han restringido a loopback o removido para servicios internos, pero no es una plantilla de producción segura.

## Política del host requerida

- Acceso operativo con usuario individual no-root (por ejemplo `trackflow-ops`) y SSH por clave pública; sudo limitado a tareas autorizadas.
- `PermitRootLogin no` en configuración efectiva de sshd. Mantener abierta una sesión de administración existente y probar una segunda sesión antes de cerrar cambios.
- Firewall de entrada: permitir HTTPS (443) desde Internet y SSH (22) solo desde CIDR administrativa. Permitir HTTP/80 solo si se necesita para redirección ACME/HTTPS, y luego documentarlo. Denegar el resto por defecto; las conexiones service-to-service deben ir por red privada/container network.
- No se debe aplicar una regla al firewall remoto sin ventana de mantenimiento, confirmación de CIDR/puerto SSH y acceso alternativo probado.

## Usuario y permisos esperados

Crear usuario/grupo mediante el procedimiento estándar de la distribución y conceder sudo mínimo. No guardar credenciales privadas SSH en el repositorio.

| Recurso de ejemplo | Propietario/grupo esperado | Modo de referencia | Regla |
|---|---|---:|---|
| `/opt/trackflow/app` | `root:trackflow` | directorios `0750`, archivos `0640` | Proceso puede leer; despliegue controlado modifica. |
| `/var/log/trackflow` | `trackflow-svc:trackflow-ops` | directorio `0750`, archivos `0640` | Solo servicio escribe; ops lee por grupo. |
| `/etc/trackflow` | `root:trackflow-svc` | directorio `0750`, secretos `0640` o más restrictivo | No accesible por usuarios no autorizados; nunca versionar. |
| Socket/directorios de datos | usuario dedicado del servicio | mínimo necesario | No usar permisos globales `0777`. |

Ajustar propietarios y rutas según la unidad systemd o contenedor real. Si Docker necesita bind mounts, conceder acceso al usuario del proceso y evitar permisos globales.

## Comandos de verificación en host Linux autorizado

Ejecutar manualmente por un operador autorizado; los comandos solo consultan estado salvo donde se indique explícitamente. Guardar salida sanitizada, sin IPs internas sensibles ni nombres de usuario no necesarios.

```sh
sudo sshd -T | grep -i '^permitrootlogin'
getent passwd trackflow-ops
id trackflow-ops
sudo namei -l /opt/trackflow/app /var/log/trackflow /etc/trackflow
sudo stat -c '%A %a %U:%G %n' /opt/trackflow/app /var/log/trackflow /etc/trackflow
sudo ufw status verbose             # si el host usa UFW
sudo nft list ruleset               # si el host usa nftables
sudo ss -tulpen
```

Prueba de red desde una máquina externa autorizada: escanear únicamente la IP pública propia y verificar que 443 está disponible, 22 solo desde red ops y no aparecen puertos internos (8000, 8001, 3000/3001, 5555, 6379, 6333/6334, 8080). No ejecutar escaneos sobre terceros.

## Docker Compose y despliegue

Antes de producción, usar un override/manifest de producción que:

1. Publique únicamente el reverse proxy TLS (443 y opcional 80); quite `ports` de API, MCP, Keycloak, Redis, Flower y Qdrant.
2. Use imágenes y dependencias fijadas y escaneadas; builds de producción (no `next dev`, no autoreload).
3. Ejecute procesos como UID/GID no-root, con filesystem de solo lectura cuando sea viable y volúmenes persistentes con permisos limitados.
4. Inyecte secretos desde secret manager/entorno seguro; no poner valores en Compose versionado ni imágenes.
5. Mantenga redes internas y healthchecks sin exposición pública.

Validación local de sintaxis: `docker compose config --quiet`. Esto no valida las reglas del host ni equivale a scan externo.

### Overlay de producción disponible

`docker-compose.production.yml` y `deploy/nginx/trackflow.conf` proporcionan un baseline ejecutable: solo Nginx publica `443`, requiere certificado/clave TLS explícitos, aplica TLS 1.2+, reenvía HTTPS a API/MCP/Keycloak y elimina puertos/volúmenes de desarrollo de los servicios. La API comprueba en startup que `TRACKFLOW_ENV=production` tiene clave de firma, URL de base de datos, secreto del cliente MCP, orígenes CORS HTTPS, URLs públicas HTTPS y Redis con TLS (`rediss://`); ejecuta `PING` y el script Lua del limitador antes de aceptar tráfico. No se incluye certificado ni se declara que DNS, certificados, TLS de Redis, trust chain, secretos ni configuración externa hayan sido comprobados.

Despliegue (en infraestructura autorizada, con valores provisionados por el secret manager, nunca en el repositorio):

```sh
export TRACKFLOW_ENV=production
export TLS_CERT_FILE=/ruta-segura/fullchain.pem TLS_KEY_FILE=/ruta-segura/privkey.pem
export TRACKFLOW_SECRET_FILE=/ruta-segura/api-signing-secret
export SQL_URL_FILE=/ruta-segura/database-url
export MCP_OAUTH_CLIENT_SECRET='...' # obtener del secret manager; no guardar en shell history compartido
export REDIS_URL='rediss://...' # obtenido del gestor de secretos/configuración
export CORS_ALLOWED_ORIGINS='https://app.example.com'
export MCP_PUBLIC_URL='https://mcp.example.com'
export OAUTH_ISSUER_URL='https://auth.example.com/realms/trackflow'
export OAUTH_JWKS_URI='https://auth.example.com/realms/trackflow/protocol/openid-connect/certs'
export KEYCLOAK_PUBLIC_URL='https://auth.example.com'
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

`KEYCLOAK_ADMIN_PASSWORD` también debe inyectarse desde el secret manager. Configure las credenciales cliente MCP y credenciales de base de datos del mismo modo. Si el Redis administrado exige CA privada, inyectar la CA y habilitar validación de certificado en el cliente; no deshabilitarla para hacer pasar el healthcheck. La configuración Compose no valida seguridad de la plataforma/daemon Docker, registros de secretos ni cambios de esquema: aplicar `services/api/data/migrations/003_pending_sku_exit_approvals.sql` antes de desplegar el código que crea la tabla con `create_all`.

El ensayo real del rate limiter se ejecuta con `REDIS_INTEGRATION_URL='rediss://...' pytest services/api/tests/test_agent_rate_limit.py -m integration`. El test crea claves de ventana únicas, ejecuta `PING` + Lua + límite en Redis real y elimina su clave. El startup probe cubre asimismo el endpoint Redis configurado en `REDIS_URL`.

### Aprobación de despacho

`POST /inventory/orders/outbound` ya no contabiliza una salida: crea una solicitud durable `pending_sku_exits` y responde `202`. Una identidad `manager`/`admin` distinta debe decidir en `POST /inventory/orders/outbound/{request_id}/decision` con `approve` o `reject`; al aprobar se vuelve a verificar stock y solo entonces se crea `SKUExit`. La fila conserva solicitante, aprobador, comentario, estado y tiempos. Los controles no sustituyen la autorización del operador: asignar identidades individuales y proteger las cuentas privilegiadas. Este flujo cubre el despacho de inventario representado por esa ruta; no demuestra que haya integración de ejecución con carriers, ni crea capacidades de devolución/cambio de carrier que no están implementadas.

## Estado de verificación

| Control | Estado actual | Evidencia requerida para cerrar |
|---|---|---|
| Login SSH root prohibido | No verificado en host | `sshd -T` y prueba de intento SSH root rechazado, con acceso ops confirmado. |
| Usuario operativo no-root | No verificado en host | `getent`, `id`, membresía/grupos y prueba de sudo limitado. |
| Permisos de carpetas | Definidos como política, no verificados | `namei -l`, `stat` sobre rutas efectivas y revisión de acceso de servicio. |
| Firewall mínimo | No verificado en host | Estado de firewall + scan externo autorizado tras aplicación. |
| Puertos publicados Compose | Baseline detectado; exposición de desarrollo amplia | Configuración de producción validada y scan externo confirmando puertos no permitidos cerrados. |

**No declarar sign-off** hasta verificar todos los controles del host real y restringir exposición de los servicios internos.

## Nota de alcance del ciclo NIST — 2026-10-27

El solicitante confirma que SSH está atendido por Operaciones y excluye esa tarea de esta implementación. Esta exclusión no equivale a verificación técnica del host: la guía anterior sigue marcando SSH, usuario no-root, firewall y exposición productiva como no verificados por esta auditoría. No se han cambiado reglas del host ni se ha ejecutado un escaneo de red.

Para secretos y endpoints agentic, consultar `ai-inventory.es.md` y `nist-ai-security-assessment.es.md`. El limitador Redis protege `/knowledge/query` desde la API; requiere `REDIS_URL`, `AGENT_RATE_LIMIT` y `AGENT_RATE_WINDOW_SECONDS`, y responde fail-closed ante fallo de Redis. Esto no reemplaza TLS ni la política de firewall/proxy.
