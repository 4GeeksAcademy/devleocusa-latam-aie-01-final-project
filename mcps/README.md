# TrackFlow MCP Server

Servidor MCP independiente por Streamable HTTP para las herramientas de incidencias e inventario de TrackFlow. El servidor usa FastMCP para MCP y `mcpauth` como OAuth resource server. FastMCP auth helpers no se usan.

## Tools

| Tool | Scope | Entrada | Salida y efecto |
| --- | --- | --- | --- |
| `create_incident` | `incidents:create` | `title` (1–160), `description`, `category`, `status`, `origin`, `branch` | Incidencia creada por `POST /api/incidents`, con ID y timestamps. |
| `update_incident_status` | `incidents:status:write` | `incident_id`, `status` | Resultado mínimo `{id, status, updated_at}`. Usa `PATCH /api/incidents/{id}/status`; el API valida transiciones. |
| `get_incident` | `incidents:read` | ID exacto de la incidencia | Registro de Incidents Manager. |
| `list_incidents` | `incidents:read` | Al menos uno de `status`, `origin`, `branch`, `category` | `{incidents: [...]}` filtrado por el API. |
| `search_inventory` | `inventory:read` | `query`: nombre/SKU parcial o ID exacto | `{products: [...]}` con `id`, `name`, `sku_code`, `warehouse`, `current_stock` live. Solo hace GET a `/inventory/products`. |
| `request_inventory_change` | `inventory:read` | `operation` y, opcionalmente, `sku_id`, `quantity` | Siempre falla con `READ_ONLY`; jamás llama un endpoint de escritura. |

Enums de incidencias del API: categorías `Almacen`, `Ultima_Milla`, `Logistica_Inversa`, `CX`, `Comercial`, `Tecnologia`; estados `open`, `in_progress`, `resolved`, `discarded`; origen `customer`, `branch`, `internal`; sucursales `Los Ángeles`, `Zaragoza`, `Central`.

La descripción y el input schema de cada tool se anuncian a través de `tools/list`; pueden inspeccionarse desde cualquier cliente MCP autenticado sin acceder al código.

## OAuth y errores

El endpoint `/.well-known/oauth-protected-resource` publica el resource URI, el authorization server, scopes y método de bearer. Es metadata pública del protocolo; no lista tools. Todas las peticiones MCP, incluidas `tools/list` y `tools/call`, requieren bearer JWT con firma válida, `iss` y audience correctos y scope base `trackflow:mcp`. Clientes OIDC interactivos también deben solicitar `openid` para que Keycloak incluya el claim `sub` que `mcpauth` valida.

| Situación | HTTP/MCP | Código | Mensaje |
| --- | --- | --- | --- |
| Bearer ausente | HTTP 401 | `missing_auth_header` | Indica que se necesita un bearer y aporta `WWW-Authenticate` con resource metadata. |
| Bearer inválido, firma/issuer/audience incorrectos | HTTP 401 | `invalid_token`, `invalid_issuer` o `invalid_audience` | El token no es válido para TrackFlow MCP. |
| Falta el scope base | HTTP 403 | `missing_required_scopes` | El access token no incluye `trackflow:mcp`. |
| Falta scope de una tool | Resultado MCP `isError` | `INSUFFICIENT_SCOPE` | Identifica el scope requerido por esa operación. |
| Argumento ausente, enum no admitido o inválido | JSON-RPC `-32602` o resultado MCP `INVALID_ARGUMENT` | `INVALID_ARGUMENT` / `Invalid params` | Describe que el input no satisface el schema de la tool. |
| ID inexistente | Resultado MCP `isError` | `NOT_FOUND` | El registro no existe en el API de TrackFlow. |
| Transición no permitida | Resultado MCP `isError` | `INVALID_TRANSITION` | El lifecycle del API rechazó el cambio. |
| API no disponible/timeout | Resultado MCP `isError` | `UPSTREAM_UNAVAILABLE` / `UPSTREAM_TIMEOUT` | La herramienta no pudo completar la consulta. |
| Escritura de inventario solicitada | Resultado MCP `isError` | `READ_ONLY` | La operación no se realizó; inventario es solo lectura. |

Cada petición `tools/call` deja un log con `client`, `tool`, `result` y código si falla. No se registran tokens, secretos ni argumentos completos.

## Configuración local

1. Copiar los placeholders relevantes de `mcps/.env.example` al `.env` ignorado en la raíz del monorepo y completar URLs públicas, contraseñas y secretos localmente.
	`KEYCLOAK_ADMIN_PASSWORD` es obligatoria; usa una contraseña fuerte y no publiques el archivo `.env`. Keycloak conserva realm y clientes en el volumen `trackflow_keycloak_data`.
2. Crear una cuenta técnica de TrackFlow en el API, con acceso de lectura/escritura a incidencias. Configurar su email y contraseña como `TRACKFLOW_SERVICE_USERNAME` y `TRACKFLOW_SERVICE_PASSWORD`; MCP obtiene y cachea el JWT local para las llamadas internas. Nunca se reenvía el token OAuth del cliente al API.
3. Arrancar `docker compose up --build -d keycloak mcp api`. Keycloak importa el realm `trackflow`. En Admin Console, obtener el secret de `trackflow-agent` y asignarlo en `MCP_OAUTH_CLIENT_SECRET` del entorno del servicio API. Scopes del cliente agente usados por defecto: `trackflow:mcp incidents:read inventory:read`. Añadir scopes de escritura solo si la política del agente los requiere.
4. En el cliente público `trackflow-mcp-playground`, registrar en Keycloak el redirect URI de OAuth que muestra MCP Playground. Usar Authorization Code + PKCE S256 y solicitar `openid trackflow:mcp` junto con los scopes de las tools a probar. Crear una cuenta de usuario de desarrollo en el realm si no existe.
5. Releer las variables con `docker compose up -d --force-recreate api mcp` tras cambiarlas.

Variables principales: `MCP_PUBLIC_URL`, `MCP_AUDIENCE`, `OAUTH_ISSUER_URL`, `OAUTH_JWKS_URI`, `TRACKFLOW_API_BASE_URL`, `TRACKFLOW_SERVICE_USERNAME`, `TRACKFLOW_SERVICE_PASSWORD`, `MCP_OAUTH_TOKEN_URL`, `MCP_OAUTH_CLIENT_ID`, `MCP_OAUTH_CLIENT_SECRET`, `MCP_OAUTH_SCOPES`.

En Compose, MCP alcanza el API como `http://api:8000` y descarga JWKS como `http://keycloak:8080/...`; los tokens deben conservar el issuer público exacto anunciado por Keycloak. Si se usa un issuer externo, configurar su `iss`, token/JWKS endpoints y audience mediante entorno.

## MCP Playground en Codespaces

1. Arrancar los servicios y esperar a que `docker compose ps` muestre `keycloak`, `mcp` y `api` saludables.
2. En la pestaña **Ports** de Codespaces, hacer públicos temporalmente los puertos `8001` (MCP) y `8080` (Keycloak). El puerto `8080` también expone la consola admin: usa una contraseña fuerte, limita el tiempo público y vuelve el puerto a privado al acabar. No conectar con `localhost` desde Playground.
3. Configurar `MCP_PUBLIC_URL` con la URL reenviada de `8001`; `KEYCLOAK_PUBLIC_URL` y `OAUTH_ISSUER_URL` con la URL reenviada de `8080`; `OAUTH_JWKS_URI` puede seguir usando DNS interno para que lo consuma el contenedor MCP. Recrear los servicios.
4. Conectar Playground al endpoint reenviado `https://<codespace>-8001.app.github.dev/mcp`. Configurar OAuth contra `https://<codespace>-8080.app.github.dev/realms/trackflow`, con client ID `trackflow-mcp-playground`, el redirect URI que muestra Playground, audience `trackflow-mcp` y scopes `openid trackflow:mcp` más los scopes operativos requeridos.
5. En Playground, descubrir las tools y ejecutar al menos: alta → consulta → transición de una incidencia; búsqueda de SKU; y `request_inventory_change`, que debe devolver `READ_ONLY`. Probar además una llamada sin bearer (401) y una sin scope base (403).

Los resultados de estas pruebas remotas deben anotarse después de ejecutarlas; las pruebas pytest locales no sustituyen la validación real de Playground.

## Pruebas

```bash
uv run --project mcps pytest -q mcps/tests
docker compose config --quiet
```