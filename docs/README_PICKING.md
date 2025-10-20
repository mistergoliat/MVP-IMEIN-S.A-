# Picking App Overview

Este documento resume los componentes principales de la solución de picking basada en FastAPI, Postgres y una interfaz HTMX/Jinja.

## Servicios

- **picking-api**: Servicio FastAPI encargado de autenticación, operaciones de inventario (ingresos, salidas, traslados), auditoría y cola de impresión.
- **ui**: Frontend en Python (FastAPI + Jinja + HTMX) que consume la API y entrega la experiencia de picking en español (es-CL).
- **db**: Contenedor Postgres 15 con el esquema definido en `db/init.sql`.
- **n8n**: Flujo existente que genera los archivos ABC–XYZ consumidos por la API y UI.

## Flujo de datos ABC–XYZ

1. n8n genera los archivos dentro de `project/output/`.
2. El servicio `picking-api` monta `project/output/` como `/data/abcxyz` y ejecuta la importación usando `/import/abcxyz/from-local`.
3. La UI expone un botón "Sincronizar ABC–XYZ" que dispara la importación.
4. El agente de impresión en Windows consume la cola de impresión (`print_jobs`) mediante el endpoint `/print/jobs`.

## Puesta en marcha rápida

```bash
docker compose -f ops/docker-compose.yml up --build
```

1. Crear un archivo `.env` en la raíz copiando `samples/env/.env` (o basándose en él).
2. Ejecutar el comando anterior para levantar los contenedores.
3. Iniciar sesión con usuario `admin` (contraseña definida en base de datos) y realizar una importación inicial.
4. Configurar el agente de impresión en Windows según `host/print-agent/README`.

### Aprovisionamiento del rol `app`

- El contenedor de Postgres ejecuta `db/create-app-role.sh` durante la inicialización para crear (o actualizar) el rol `app` con la contraseña definida en `APP_ROLE_PASSWORD` (o, en su defecto, `PGPASSWORD`) y opcionalmente traspasar la propiedad de la base de datos `picking`.
- Para entornos existentes donde ya se creó el volumen de datos, ejecute manualmente el script dentro del contenedor para recrear el rol:

  ```bash
  docker compose --env-file ops/.env -f ops/docker-compose.yml run --rm db \
    bash /docker-entrypoint-initdb.d/create-app-role.sh
  ```

- Alternativamente, reciclar los volúmenes (`docker compose --env-file ops/.env -f ops/docker-compose.yml down -v`) volverá a ejecutar todos los scripts de inicialización.

## Estructura de carpetas

- `services/picking-api`: Código de la API, modelos y routers de FastAPI.
- `services/ui`: Aplicación HTMX/Jinja que consume la API.
- `host/print-agent`: Agente Windows que imprime etiquetas en la Zebra ZD888t.
- `docs`: Documentación funcional y técnica.
- `samples`: Recursos de ejemplo.

## Integración con SAP/Odoo

La API expone endpoints de exportación (`/export/...`) que facilitan integraciones futuras con ERPs como SAP Business One u Odoo.

## Seguridad

- Autenticación JWT con expiración de 8 horas.
- Intentos fallidos limitados (5 en 15 minutos).
- Roles con control de acceso: operator, supervisor, admin.
- Auditoría de eventos críticos en la tabla `audit`.
