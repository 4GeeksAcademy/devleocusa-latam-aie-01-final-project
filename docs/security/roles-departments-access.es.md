# Matriz de acceso por rol y departamento

La autorización combina **capacidad del rol** y **alcance departamental**. Una petición solo se permite si cumple ambos ejes. Los roles conservan sus valores de API (`admin`, `manager`, `user`, `service`): Admin, Supervisor, Empleado y Servicio técnico. `service` es una identidad no humana y no hereda permisos de empleados o supervisores. Los usuarios sin departamento asignado fallan de forma cerrada en recursos departamentales. Admin es el único rol con alcance global.

## Departamentos oficiales

- Operaciones de Almacén (`WAREHOUSE_OPERATIONS`)
- Última Milla y Gestión de Carriers (`LAST_MILE_CARRIERS`)
- Logística Inversa (Devoluciones) (`RETURNS`)
- Experiencia del Cliente (CX) (`CUSTOMER_EXPERIENCE`)
- Comercial y Relación con Clientes (`COMMERCIAL`)
- Personas (`PEOPLE`)
- Tecnología (`TECHNOLOGY`)
- Dirección Ejecutiva (`EXECUTIVE`)

## Matriz de rutas implementadas

| Recurso/rutas | Empleado | Supervisor | Admin | Departamento |
|---|---:|---:|---:|---|
| `/inventory/products`, SKU, movimientos/órdenes | lectura y operaciones permitidas por endpoint | crear SKU y decidir salidas | global | Operaciones de Almacén |
| `/api/incidents`, `/api/incidents/{id}` | lectura/alta | cambios de estado y análisis CSV | global | Última Milla y Gestión de Carriers |
| `/suppliers` | lectura | cambios administrativos | global | Última Milla y Gestión de Carriers |
| `/knowledge/query`, `/knowledge/guardrails/summary` | uso y resumen | idem | global | Experiencia del Cliente (CX) |
| `/chat/ws/{session_id}` | no | acceso de chat | global | Experiencia del Cliente (CX) |
| `/people/records/{id}` | solo registro propio | lectura de Personas | global | Personas |
| `PUT /people/records/{id}` | no | escritura | global | Personas |
| `/commercial/renewals` | lectura | lectura y alta | global | Comercial y Relación con Clientes |
| `/leads` | lectura | CRUD | global | Comercial y Relación con Clientes |
| `/rfp/tickets`, `/rfp/events` | lectura/eventos | carga y lectura | global | Comercial y Relación con Clientes |
| `/rfp/tickets/{id}/final-document` | no | no | global | Administración |
| `/reporting/status`, `/reporting/kpis`, `/tasks/{id}` | lectura | lectura | global | Dirección Ejecutiva |
| `/reporting/run`, `/reports/generate` | no | ejecución | global | Dirección Ejecutiva |
| `/telemetry/report` | lectura | lectura e ingesta | global | Tecnología |
| `/telemetry/events` | no | ingesta | global | Tecnología |
| `/users/departments`, listado y eliminación de usuarios | no | no | administración | Administración |
| `/users/{id}` | lectura/actualización propia sin cambiar privilegios | ídem | administración global | Perfil propio / Admin |
| `/profiles/me`, `/auth/me` | perfil propio | perfil propio | perfil propio | Identidad |

Las rutas públicas de login, registro, recuperación de contraseña y envío público de leads no exponen datos internos. Las rutas de incidencias continúan aplicando además el `tenant_id`; ese control no reemplaza la comprobación departamental.

## Reglas de implementación

- El backend es la autoridad. Ocultar navegación o controles en el backoffice es solo una mejora de UX.
- No confiar en departamento, rol, tenant o usuario objetivo suministrado por el cliente para conceder acceso.
- Rechazar explícitamente con HTTP 403 las combinaciones rol/departamento no autorizadas.
- Para Dirección Ejecutiva, el administrador puede consultar vistas consolidadas; ningún otro departamento recibe automáticamente acceso agregado.
- Cambios de rol y departamento se administran separadamente y son exclusivos de Admin.
