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
