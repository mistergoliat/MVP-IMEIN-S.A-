# Sample `.env` bundle

Este directorio contiene un ejemplo completo de variables de entorno para levantar la solución con `docker compose`.

## Uso

1. Copia `samples/env/.env` a la raíz del repositorio y renómbralo a `.env`.
2. Ajusta los valores sensibles (por ejemplo `API_JWT_SECRET`, credenciales de Postgres) según tu entorno.
3. Ejecuta `docker compose -f ops/docker-compose.yml up --build`.

El archivo incluye las variables esperadas por los servicios `db`, `picking-api`, `ui` y `n8n`. El flujo de autenticación del navegador debe apuntar al servicio de UI, que a su vez delega las credenciales a la API interna.
