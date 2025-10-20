# Impresora Zebra ZD888T - Picking

Sistema monorepo para renderizar, previsualizar y enviar etiquetas ZPL hacia impresoras Zebra ZD888T.
Incluye API FastAPI, UI FastAPI + Jinja y scripts operativos.

## Servicios principales
- **services/picking-api**: backend FastAPI encargado de autenticacion, movimientos y generacion/imprension de etiquetas.
- **services/ui**: interfaz web que consume la API y permite previsualizar/imprimir etiquetas.
- **ops/**: definiciones de docker-compose y variables para los contenedores.

## Variables de entorno clave
Definir en ops/.env (ver ops/.env.example):

- PRINTER_MODE: local para QZ Tray o 
etwork para enviar RAW 9100.
- PRINTER_LAYOUT: 1col o 2across (por defecto 2across).
- PRINTER_DUPLICATE_SINGLE: True duplica cuando solo se solicita 1 etiqueta en rollos dobles.
- PRINTER_HOST: host de la impresora de red (modo network).
- PRINTER_PORT: puerto TCP (por defecto 9100).

La UI solo requiere PICKING_API_URL y PICKING_API_TIMEOUT para localizar la API.

## Analytics ABC–XYZ (MVP)

- Tabla SQL: `abcxyz_results` creada por `db/init.sql`.
- Backend:
  - POST `/analytics/abcxyz/ingest` (multipart): `file` (XLSX/CSV) + `period`.
  - GET `/analytics/abcxyz/latest`: resumen (kpis, matriz 3×3) y filas.
  - GET `/analytics/abcxyz/item/{code}`: última clasificación del SKU.
- UI:
  - Página `/analytics/abcxyz`: uploader, KPIs, matriz y tabla con filtros.
  - Badge ABC–XYZ y política al seleccionar SKU en `/print`.

Formato mínimo de archivo: columnas `item_code, abc, xyz, class, policy`.
Opcionales: `stock, turnover, revenue`.

## Flujo de impresion
1. La UI llama a POST /labels/preview para obtener ZPL y plantilla seleccionada.
2. La API normaliza datos (item_code, item_name, echa) y selecciona plantilla segun PRINTER_LAYOUT y copies.
3. Si el rollo es 2-across y solo se solicita 1 etiqueta, se usa etiqueta_50x30_2across_duplicada para imprimir izquierda/derecha en una pasada.
4. Para multiples copias en 2-across, la API agrupa de a pares y genera pasadas completas sin celdas vacias.
5. POST /labels/print:
   - **Modo local**: devuelve el ZPL; la UI lo envia a QZ Tray con la impresora seleccionada.
   - **Modo network**: la API abre socket RAW (9100) y envia el ZPL directamente.

## Plantillas ZPL
Ubicadas en services/picking-api/app/templates/zpl/:
- etiqueta_50x30.zpl.j2 (50x30, 1 columna).
- etiqueta_50x30_2across.zpl.j2 (pares izquierda/derecha por pasada).
- etiqueta_50x30_2across_duplicada.zpl.j2 (duplica cuando hay 1 etiqueta solicitada).

## Configuracion QZ Tray (modo local)
1. Instalar QZ Tray desde https://qz.io/download/ y mantenerlo en ejecucion.
2. Aceptar el certificado autogenerado o configurar certificados firmados.
3. Abrir la UI (/print) y usar **Actualizar lista** para buscar impresoras que contengan "ZDesigner" o "ZD888".
4. La UI solo habilita el selector cuando la API reporta PRINTER_MODE=local.

## Capturas requeridas
Agregar en docs/:
- docs/preview-example.png: captura de la previsualizacion mostrando la plantilla seleccionada.
- docs/label-photo.png: fotografia de la etiqueta duplicada impresa en rollo 2-across.

*(Este repositorio incluye las rutas esperadas; reemplazar por material real durante la puesta en marcha.)*

## Desarrollo rapido
`ash
# Backend
cd services/picking-api
uvicorn app.main:app --reload

# UI
cd services/ui
uvicorn app.main:app --reload
`

Con Docker: docker compose --env-file ops/.env up --build.
