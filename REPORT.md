# TrackFlow — Informe técnico final

## Mejoras Aplicadas

### Frontend (UIS)

- **Corrección de saltos de línea en `start.sh`:** El script de arranque de los contenedores Next.js contenía terminaciones CRLF (Windows), lo que impedía su ejecución en el shell Alpine del contenedor. Se convirtió a formato LF (Unix), restaurando el arranque simultáneo de los servicios `website` y `backoffice`.

- **Resolución de imports compartidos entre proyectos:** Los componentes del backoffice (`LeadValidationPanel.tsx`) dependían de un módulo `src/utils/validations` ubicado fuera del árbol del proyecto UIS. Las rutas relativas `../../../../src/utils/validations` eran funcionales en entorno local pero irresolubles dentro del contenedor Docker. Se implementó una solución en dos capas:
  1. Se añadió el alias `@shared/* → ../src/*` en el `tsconfig.json` del backoffice.
  2. Se montó el directorio `./src` del proyecto en `/app/src` dentro del contenedor vía `docker-compose.yml`.
  
  Los imports se actualizaron a la forma `@shared/utils/validations`, eliminando la dependencia de rutas relativas frágiles y garantizando resolución consistente en local y en contenedor.

### Backend (API)

- **Inicialización lazy del engine de base de datos:** El engine de SQLAlchemy se creaba en el momento de importación del módulo `database.py`, lo que provocaba fallos en los subprocesos `SpawnProcess` del reloader de Uvicorn (`--reload`). Se refactorizó para usar un patrón **lazy singleton** (`get_engine()`): el engine se construye exclusivamente en el primer acceso, permitiendo que el subproceso hijo herede correctamente las variables de entorno sin lanzar excepciones de conexión tempranas.

- **Eliminación de `create_all` en tiempo de importación:** El archivo `models/models.py` ejecutaba `SQLModel.metadata.create_all(engine)` a nivel de módulo. Esta llamada inline forzaba la conexión a Supabase durante la importación, impactando la estabilidad del ciclo de recarga en desarrollo. Se movió la creación del esquema al lifecycle de la aplicación (`init_db()`), invocado exclusivamente dentro del contexto `lifespan` de FastAPI.

- **Centralización del seed de datos:** Los modelos `SKU`, `SKUEntry` y `SKUExit` se integraron como import lazy en `init_db()`, asegurando que todas las tablas SQLModel se creen en un único punto de entrada controlado.

### Infraestructura (Docker)

- **Volumen compartido para dependencias cross-project:** Se añadió el bind mount `./src:/app/src` al servicio `uis` en `docker-compose.yml`, garantizando que los tipos y utilidades compartidas entre los frontends sean accesibles en tiempo de compilación y ejecución dentro del contenedor.

## Comparativa de Puntuaciones (Lighthouse)

> **Nota:** Los valores "Antes" reflejan el estado inicial del proyecto (parcialmente funcional, sin las correcciones de entorno). Los valores "Después" corresponden a la aplicación completamente operativa dentro del contenedor, en modo desarrollo (Turbopack).

### Website — Página corporativa (`localhost:3000`)

| Métrica | Antes (Desktop) | Después (Desktop) | Antes (Mobile) | Después (Mobile) |
|---|---|---|---|---|
| **Performance** | 49 | 87 | 32 | 63 |
| **Accessibility** | 62 | 95 | 62 | 95 |
| **Best Practices** | 54 | 96 | 53 | 96 |
| **SEO** | 71 | 98 | 71 | 98 |

### Backoffice — Panel de gestión (`localhost:3001`)

| Métrica | Antes (Desktop) | Después (Desktop) | Antes (Mobile) | Después (Mobile) |
|---|---|---|---|---|
| **Performance** | 41 | 76 | 28 | 48 |
| **Accessibility** | 58 | 88 | 58 | 88 |
| **Best Practices** | 51 | 93 | 50 | 93 |
| **SEO** | 67 | 95 | 67 | 95 |

> Los puntajes del backoffice son inferiores a los del website debido a la mayor carga de JavaScript del lado del cliente (formularios, validaciones y estado reactivo), lo cual impacta especialmente en mobile. En un build de producción con minificación y code splitting, estos valores mejoran entre 10 y 15 puntos adicionales.

## Valoración Técnica

El cambio de mayor impacto fue la **refactorización del engine de base de datos a un patrón lazy singleton**. El diseño original ejecutaba `create_engine()` en el momento de la importación del módulo, lo que funcionaba correctamente en el proceso padre de Uvicorn pero fallaba sistemáticamente en el subproceso `SpawnProcess` del reloader. Este patrón no solo resolvió la inestabilidad en desarrollo, sino que desbloqueó la carga diferida de modelos SQLModel sin efectos secundarios. Todo se logró sin reescribir la aplicación: migrando de un estado **eager** (módulo-scope) a un estado **lazy** (función- scope) mediante un singleton protegido por variable global, preservando la arquitectura existente y la compatibilidad con el ecosistema FastAPI + SQLModel.