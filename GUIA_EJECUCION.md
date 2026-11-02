# Guía de ejecución y verificación

Esta guía resume cómo levantar TrackFlow y verificar los proyectos principales del monorepo en desarrollo local. Los comandos asumen Linux/macOS y que Docker, Node.js, npm y Python 3.11+ están instalados.

## 1. Configuración

1. Crea un `.env` local si todavía no existe y completa las variables necesarias para los servicios que vayas a iniciar:

   ```bash
   touch .env
   ```

2. Completa los valores locales requeridos en `.env` (por ejemplo, secretos de desarrollo y conexión de base de datos). No compartas ni comitees este archivo.
3. Instala dependencias del proyecto que vayas a ejecutar, si no se instalaron ya. En los frontends, ejecuta `npm install` dentro de `uis/website` y/o `uis/backoffice`. Para la API, usa su entorno virtual e instala `services/api/requirements.txt` (o el entorno reproducible basado en `services/api/uv.lock`).

## 2. Levantar el entorno con Docker Compose

Desde la raíz:

```bash
docker compose up --build
```

La configuración de desarrollo expone el sitio web en `http://localhost:3000`, el backoffice en `http://localhost:3001` y la API en `http://localhost:8000`. La documentación OpenAPI de FastAPI está disponible en `http://localhost:8000/docs`.

Para detener los servicios:

```bash
docker compose down
```

Usa `docker-compose.production.yml` solo con las variables y secretos de despliegue descritos en ese archivo; no es una configuración local sin preparación.

## 3. Ejecutar cada aplicación por separado

### API FastAPI

Desde `services/api`, activa el entorno virtual del proyecto y ejecuta:

```bash
python -m pip install -r requirements.txt
uvicorn src.fastapi_server:app --reload --host 0.0.0.0 --port 8000
```

### Sitio web

```bash
cd uis/website
npm install
npm run dev
```

### Backoffice

```bash
cd uis/backoffice
npm install
npm run dev
```

En cada frontend, define `NEXT_PUBLIC_API_BASE_URL` apuntando a la URL accesible desde el navegador donde esté publicada la API (localmente, normalmente `http://localhost:8000`). La API debe permitir el origen del navegador en `CORS_ALLOWED_ORIGINS`.

## 4. Flujo Leads

1. Envía una solicitud desde el formulario público del sitio web. Se registra solo si el endpoint `POST /leads` responde correctamente.
2. Inicia sesión en el backoffice con un usuario de rol `ADMIN` o `MANAGER` y abre **Comercial → Gestión de prospectos** (`/leads`).
3. Busca por empresa, contacto o email; filtra por estado; actualiza la etapa comercial o elimina registros.
4. La API expone `GET /leads`, `GET /leads/{id}`, `PUT /leads/{id}`, `PATCH /leads/{id}/status` y `DELETE /leads/{id}` para personal autorizado.

El almacenamiento de leads sigue el patrón TinyDB local del servicio API. La bandeja es compartida por el personal autorizado: el modelo actual no implementa aislamiento por tenant. Para despliegues con múltiples réplicas/alta concurrencia, sustituir TinyDB por un almacén transaccional antes de escalar.

## 5. Verificación

### API

Desde `services/api`:

```bash
pytest -q tests/test_leads.py
python -m compileall -q src
```

### Frontends

Desde `uis/website` y `uis/backoffice`, respectivamente:

```bash
npm run lint
npm run build
```

### Diff de Git

Desde la raíz:

```bash
git diff --check
git status --short
```
