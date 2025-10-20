# Contrato de la API de Picking

> **Nota**: Este documento actúa como guía inicial de endpoints y estructuras de datos. Ajustes posteriores deben sincronizarse con la UI y el agente de impresión.

## Autenticación

- `POST /auth/login` → `{ "access_token": str, "token_type": "bearer" }`
- `POST /auth/logout`

## Importación ABC–XYZ

- `GET /import/abcxyz/probe` → `{ "available": bool, "path": str }`
- `POST /import/abcxyz/from-local` → `{ "imported": int }`

## Documentos

- `POST /doc/scan` → `{ "doc_type": "PO|SO|TR", "doc_number": str }`
- `POST /moves` → crea movimiento y devuelve `{ "id": uuid, ... }`
- `POST /moves/{id}/confirm` → confirma líneas de picking.

## Stock & Auditoría

- `GET /stock` → listado de inventario disponible.
- `GET /audit` → registros auditados con filtros opcionales.
- `GET /health` → chequeo simple (`{"status":"ok"}`).

## Impresión

- `POST /print/product` → encola ZPL.
- `GET /print/jobs` → parámetros `status`, `limit`.
- `POST /print/jobs/{id}/ack` → marca como enviado/erro.

## Exportaciones

- `GET /export/products.xlsx`
- `GET /export/stock.xlsx`
- `GET /export/moves/{doc_type}/{doc_number}.pdf`

## Errores estándar

```json
{
  "detail": "mensaje descriptivo",
  "code": "error_code"
}
```
