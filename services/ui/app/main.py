import os
from pathlib import Path
from typing import Any
from datetime import datetime

import httpx
from pydantic import BaseModel, Field
from fastapi import FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
API_BASE_URL = os.getenv("PICKING_API_URL", "http://picking-api:8000")
API_TIMEOUT = float(os.getenv("PICKING_API_TIMEOUT", "10"))
API_SERVICE_TOKEN = os.getenv("PRINT_SERVICE_TOKEN")

# Cookie settings (allow overriding for non-HTTPS deployments)
SECURE_COOKIES = os.getenv("UI_COOKIE_SECURE", "1").lower() in {"1", "true", "yes", "on"}
COOKIE_DOMAIN = os.getenv("UI_COOKIE_DOMAIN") or None

app = FastAPI(title="Picking UI", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


OPERATIONS = [
    {
        "slug": "inv",
        "doc_type": "INV",
        "name": "Inventario (Movs + Saldos)",
        "description": "Movimientos sin número de documento y vistas rápidas.",
        "cta": "Abrir inventario",
        "href": "/inventory",
        "status": "Disponible",
    },
    {
        "slug": "po",
        "doc_type": "PO",
        "name": "Entrada (PO)",
        "description": "Registra el ingreso de mercaderí­a al inventario y actualiza existencias.",
        "cta": "Crear entrada",
        "href": "/moves/new?type=PO",
        "status": "Disponible",
    },
    {
        "slug": "so",
        "doc_type": "SO",
        "name": "Salida (SO)",
        "description": "Confirma pedidos de salida y descuenta stock en tiempo real.",
        "cta": "Crear salida",
        "href": "/moves/new?type=SO",
        "status": "Disponible",
    },
    {
        "slug": "tr",
        "doc_type": "TR",
        "name": "Traslado (TR)",
        "description": "Gestiona traslados entre ubicaciones manteniendo trazabilidad de los movimientos.",
        "cta": "Crear traslado",
        "href": "/moves/new?type=TR",
        "status": "Disponible",
    },
    {
        "slug": "rt",
        "doc_type": "RT",
        "name": "Devolución (RT)",
        "description": "Procesa devoluciones de clientes y reincorpora los productos al stock.",
        "cta": "Crear devoluciÃƒÂ³n",
        "href": "/moves/new?type=RT",
        "status": "Disponible",
    },
]

# Feature flags for modules on the dashboard
_UI_ENABLE_PO = os.getenv("UI_ENABLE_PO", "0").lower() in {"1", "true", "yes", "on"}

def _enabled_operations():
    ops = OPERATIONS
    if not _UI_ENABLE_PO:
        ops = [op for op in ops if op.get("doc_type") != "PO"]
    return ops


async def _api_request(method: str, path: str, token: str | None, **kwargs: Any) -> httpx.Response:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if API_SERVICE_TOKEN and "X-Service-Token" not in headers:
        headers["X-Service-Token"] = API_SERVICE_TOKEN
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=API_TIMEOUT) as client:
        response = await client.request(method, path, headers=headers, **kwargs)
    return response

def _require_token(request: Request) -> str | None:
    token = request.cookies.get("auth_token")
    if not token:
        return None
    return token


def _safe_detail(response: httpx.Response, default: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return default
    detail = data.get("detail") if isinstance(data, dict) else None
    return detail if isinstance(detail, str) else default


def _dashboard_context(request: Request) -> dict:
    return {
        "request": request,
        "operations": _enabled_operations(),
        "username": request.cookies.get("username"),
    }


@app.get("/", response_class=HTMLResponse, name="dashboard")
async def dashboard(request: Request):
    if _require_token(request) is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("dashboard.html", _dashboard_context(request))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_alias(request: Request):
    return await dashboard(request)


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "form_error": None,
            "username": request.cookies.get("username", ""),
            "login_action": str(request.url_for("login_submit")),
        },
    )


@app.post("/login")
async def login_submit(request: Request):
    content_type = (request.headers.get("content-type") or "").lower()
    is_json_request = "application/json" in content_type

    username = None
    password = None

    if is_json_request:
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            username = payload.get("username")
            password = payload.get("password")
    else:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

    if not username or not password:
        message = "Completa usuario y contraseña para continuar."
        if is_json_request:
            return JSONResponse({"detail": message}, status_code=status.HTTP_400_BAD_REQUEST)
        context = {
            "request": request,
            "form_error": message,
            "username": username,
            "login_action": str(request.url_for("login_submit")),
        }
        return templates.TemplateResponse("login.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        api_response = await _api_request(
            "POST",
            "/auth/login",
            token=None,
            json={"username": username, "password": password},
        )
    except httpx.RequestError:
        message = "No se pudo contactar la API de picking."
        if is_json_request:
            return JSONResponse({"detail": message}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        context = {
            "request": request,
            "form_error": message,
            "username": username,
            "login_action": str(request.url_for("login_submit")),
        }
        return templates.TemplateResponse("login.html", context, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if api_response.status_code != 200:
        default_message = "Credenciales inválidas" if api_response.status_code in {400, 401} else "Error autenticando"
        message = _safe_detail(api_response, default_message)
        if is_json_request:
            return JSONResponse({"detail": message}, status_code=api_response.status_code)
        context = {
            "request": request,
            "form_error": message,
            "username": username,
            "login_action": str(request.url_for("login_submit")),
        }
        return templates.TemplateResponse("login.html", context, status_code=api_response.status_code)

    try:
        payload = api_response.json()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Respuesta inválida del servicio de autenticación")

    token = payload.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Token inválido devuelto por la API de autenticación")

    redirect_url = str(request.url_for("dashboard"))
    if is_json_request:
        response = JSONResponse({"access_token": token, "redirect_to": redirect_url})
    else:
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    # Ajusta 'secure' y 'domain' en producción
    response.set_cookie("auth_token", token, httponly=True, samesite="lax", secure=SECURE_COOKIES, domain=COOKIE_DOMAIN, path="/", max_age=60*60*8)
    response.set_cookie("username", username, samesite="lax", secure=SECURE_COOKIES, domain=COOKIE_DOMAIN, path="/", max_age=60*60*8)
    return response

@app.get("/moves/new", response_class=HTMLResponse)
async def moves_new(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    selected_type = request.query_params.get("type")
    selected = next((op for op in OPERATIONS if op["doc_type"] == selected_type), None)
    context = {
        "request": request,
        "operations": OPERATIONS,
        "selected": selected,
        "form_error": None,
        "doc_number": "",
    }
    return templates.TemplateResponse("moves_new.html", context)


@app.post("/moves/new")
async def moves_create(
    request: Request,
    doc_type: str = Form(...),
    doc_number: str = Form(...),
):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)

    payload = {"doc_type": doc_type, "doc_number": doc_number}
    api_response = await _api_request("POST", "/moves", token, json=payload)
    if api_response.status_code != status.HTTP_201_CREATED:
        selected = next((op for op in OPERATIONS if op["doc_type"] == doc_type), None)
        context = {
            "request": request,
            "operations": OPERATIONS,
            "selected": selected,
            "form_error": _safe_detail(api_response, "No se pudo crear el movimiento"),
            "doc_number": doc_number,
        }
        return templates.TemplateResponse("moves_new.html", context, status_code=api_response.status_code)

    move = api_response.json()
    return RedirectResponse(
        url=request.url_for("move_detail", move_id=move["id"]),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/moves/{move_id}", response_class=HTMLResponse, name="move_detail")
async def move_detail(request: Request, move_id: str):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)

    api_response = await _api_request("GET", f"/moves/{move_id}", token)
    if api_response.status_code == 404:
        context = {
            "request": request,
            "move": None,
            "error": "Movimiento no encontrado",
        }
        return templates.TemplateResponse("move_detail.html", context, status_code=404)
    if api_response.status_code != 200:
        context = {
            "request": request,
            "move": None,
            "error": "No se pudo cargar el movimiento",
        }
        return templates.TemplateResponse("move_detail.html", context, status_code=api_response.status_code)

    move = api_response.json()
    context = {
        "request": request,
        "move": move,
        "error": None,
        "success_message": request.query_params.get("success"),
    }
    return templates.TemplateResponse("move_detail.html", context)


@app.post("/moves/{move_id}/confirm")
async def move_confirm(request: Request, move_id: str):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)

    move_response = await _api_request("GET", f"/moves/{move_id}", token)
    if move_response.status_code != 200:
        return templates.TemplateResponse(
            "move_detail.html",
            {
                "request": request,
                "move": None,
                "error": "Movimiento no encontrado",
            },
            status_code=move_response.status_code,
        )
    move_payload = move_response.json() if move_response.status_code == 200 else None

    form = await request.form()
    item_codes = form.getlist("item_code")
    qtys = form.getlist("qty")
    qty_confirmeds = form.getlist("qty_confirmed")

    lines: list[dict[str, Any]] = []
    for idx, code in enumerate(item_codes):
        code = code.strip()
        if not code:
            continue
        try:
            qty = int(qtys[idx])
            qty_confirmed = int(qty_confirmeds[idx]) if qty_confirmeds[idx] else qty
        except (ValueError, IndexError):
            qty = None  # type: ignore[assignment]
            qty_confirmed = 0
        if qty is None or qty <= 0:
            error_context = {
                "request": request,
                "move": move_payload,
                "error": "Las cantidades deben ser enteros positivos.",
            }
            return templates.TemplateResponse("move_detail.html", error_context, status_code=400)
        line_payload = {
            "item_code": code,
            "qty": qty,
            "qty_confirmed": max(0, min(qty_confirmed, qty)),
            "location_from": form.get("location_from", "MAIN"),
            "location_to": form.get("location_to", "MAIN"),
        }
        lines.append(line_payload)

    if not lines:
        context = {
            "request": request,
            "move": move_payload,
            "error": "Agrega al menos una lí­nea antes de confirmar.",
        }
        return templates.TemplateResponse("move_detail.html", context, status_code=400)

    api_response = await _api_request("POST", f"/moves/{move_id}/confirm", token, json={"lines": lines})
    if api_response.status_code != 200:
        context = {
            "request": request,
            "move": move_payload,
            "error": _safe_detail(api_response, "No se pudo confirmar el movimiento"),
        }
        return templates.TemplateResponse("move_detail.html", context, status_code=api_response.status_code)

    return RedirectResponse(
        url=f"{request.url_for('move_detail', move_id=move_id)}?success=Movimiento%20confirmado",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/print", response_class=HTMLResponse)
async def print_labels(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)

    printer_config = None
    config_error = None
    try:
        response = await _api_request("GET", "/labels/config", token)
    except httpx.RequestError:
        response = None
        config_error = "No se pudo obtener la configuracion de la impresora."
    if response is not None:
        if response.status_code == 200:
            try:
                printer_config = response.json()
            except ValueError:
                config_error = "Respuesta invalida al cargar la configuracion de la impresora."
        else:
            config_error = "Configuracion de impresora no disponible."

    context = {
        "request": request,
        "printer_config": printer_config,
        "config_error": config_error,
    }
    return templates.TemplateResponse("print_labels.html", context)


## Removed duplicate simple receipts UI block.





class LabelPayload(BaseModel):
    item_code: str
    item_name: str
    fecha: str = ""
    copies: int = Field(default=1, ge=1, le=10)


# -------- Labels proxy endpoints (UI -> API) --------
@app.get("/labels/products")
async def ui_labels_products(request: Request, q: str, field: str = "name", limit: int = 10):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    params = {"q": q, "field": field, "limit": str(limit)}
    try:
        resp = await _api_request("GET", "/labels/products", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "Error buscando productos"))
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida desde la API de picking.")


@app.post("/labels/preview")
async def ui_labels_preview(payload: LabelPayload, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        resp = await _api_request("POST", "/labels/preview", token, json=payload.model_dump())
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo generar la previsualización"))
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")


@app.post("/labels/print")
async def ui_labels_print(payload: LabelPayload, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        resp = await _api_request("POST", "/labels/print", token, json=payload.model_dump())
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo imprimir la etiqueta"))
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida desde la API de picking.")


@app.get("/labels/jobs")
async def labels_jobs(request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        response = await _api_request("GET", "/print/jobs", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo obtener la cola de impresión.")
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=_safe_detail(response, "No se pudo obtener la cola de impresión."),
        )
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta inválida al cargar la cola de impresión.")
    return data


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_ops(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    context = {"request": request}
    return templates.TemplateResponse("inventory2.html", context)


# ------- Inventory proxy endpoints (UI -> API) -------
@app.get("/inventory/warehouses")
async def ui_list_warehouses(request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        resp = await _api_request("GET", "/inventory/warehouses", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "Error consultando bodegas"))
    return resp.json()


@app.get("/inventory/balances")
async def ui_balances(request: Request, item_code: str | None = None, warehouse: str | None = None):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    params: dict[str, str] = {}
    if item_code:
        params["item_code"] = item_code
    if warehouse:
        params["warehouse"] = warehouse
    try:
        resp = await _api_request("GET", "/inventory/balances", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "Error consultando saldos"))
    return resp.json()


@app.get("/inventory/movements")
async def ui_movements(request: Request, limit: int = 100):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        resp = await _api_request("GET", "/inventory/movements", token, params={"limit": str(limit)})
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "Error consultando movimientos"))
    return resp.json()


class UIMovementPayload(BaseModel):
    type: str
    item_code: str
    item_name: str
    uom: str = "EA"
    qty: float
    warehouse_from: str | None = None
    warehouse_to: str | None = None
    batch: str | None = None
    serial: str | None = None
    reference: str | None = None
    note: str | None = None


@app.post("/inventory/movements")
async def ui_create_movement(payload: UIMovementPayload, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        resp = await _api_request("POST", "/inventory/movements", token, json=payload.model_dump())
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking")
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo crear el movimiento"))
    try:
        return resp.json()
    except ValueError:
        return {"ok": True}


# ------- Proxy: Count sessions -------
class UICountSessionCreate(BaseModel):
    warehouse_code: str
    note: str | None = None


class UICountScan(BaseModel):
    barcode: str
    qty: float = 1
    batch: str | None = None
    serial: str | None = None


class UICountFinalize(BaseModel):
    adjustments: bool = True


@app.post("/count/sessions")
async def ui_count_create(payload: UICountSessionCreate, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    resp = await _api_request("POST", "/count/sessions", token, json=payload.model_dump())
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo abrir sesión"))
    return resp.json()


@app.post("/count/sessions/{sid}/scan")
async def ui_count_scan(sid: str, payload: UICountScan, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    resp = await _api_request("POST", f"/count/sessions/{sid}/scan", token, json=payload.model_dump())
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo registrar lectura"))
    return resp.json()


@app.post("/count/sessions/{sid}/finalize")
async def ui_count_finalize(sid: str, payload: UICountFinalize, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    resp = await _api_request("POST", f"/count/sessions/{sid}/finalize", token, json=payload.model_dump())
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo cerrar sesión"))
    return resp.json()


# ------- Proxy: Outbound scanning sessions -------
class UIOutboundCreate(BaseModel):
    type: str
    warehouse_from: str
    warehouse_to: str | None = None
    note: str | None = None


class UIOutboundScan(BaseModel):
    barcode: str
    qty: float = 1
    batch: str | None = None
    serial: str | None = None


@app.post("/outbound/sessions")
async def ui_out_create(payload: UIOutboundCreate, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    resp = await _api_request("POST", "/outbound/sessions", token, json=payload.model_dump())
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo abrir sesión"))
    return resp.json()


@app.post("/outbound/sessions/{sid}/scan")
async def ui_out_scan(sid: str, payload: UIOutboundScan, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    resp = await _api_request("POST", f"/outbound/sessions/{sid}/scan", token, json=payload.model_dump())
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo registrar lectura"))
    return resp.json()


@app.post("/outbound/sessions/{sid}/confirm")
async def ui_out_confirm(sid: str, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    resp = await _api_request("POST", f"/outbound/sessions/{sid}/confirm", token)
    if resp.status_code not in {200, 201}:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo confirmar la sesión"))
    return resp.json()


@app.get("/labels/products")
async def labels_products(
    request: Request,
    q: str = Query(..., min_length=1, max_length=64),
    field: str = Query("name"),
    limit: int = Query(10, ge=1, le=50),
):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    params = {"q": q, "field": field, "limit": str(limit)}
    try:
        response = await _api_request("GET", "/labels/products", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudieron obtener sugerencias.")
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=_safe_detail(response, "No se pudieron obtener sugerencias."),
        )
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida al obtener sugerencias.")
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Respuesta de sugerencias invalida.")
    return data


def _label_payload_to_dict(payload: LabelPayload) -> dict[str, Any]:
    data = payload.model_dump()
    item_code = str(data.get("item_code") or "").strip().upper()
    data["item_code"] = item_code
    data["item_name"] = str(data.get("item_name") or "").strip()
    fecha = str(data.get("fecha") or "").strip()
    if not fecha:
        fecha = datetime.now().strftime("%d-%m-%Y")
    data["fecha"] = fecha
    return data


@app.post("/labels/preview")
async def labels_preview(payload: LabelPayload, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    body = _label_payload_to_dict(payload)
    try:
        response = await _api_request("POST", "/labels/preview", token, json=body)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=_safe_detail(response, "No se pudo generar la previsualizacion."),
        )
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")
    return data


@app.post("/labels/print")
async def labels_print(payload: LabelPayload, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    body = _label_payload_to_dict(payload)
    try:
        response = await _api_request("POST", "/labels/print", token, json=body)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code not in {200, 201}:
        raise HTTPException(
            status_code=response.status_code,
            detail=_safe_detail(response, "No se pudo enviar la impresion."),
        )
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")
    return data






# ------------------------------
# Receipts (Goods Receipt) UI
# ------------------------------
@app.get("/receipts/new", response_class=HTMLResponse)
async def receipts_new(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    context = {
        "request": request,
        "username": request.cookies.get("username"),
    }
    return templates.TemplateResponse("receipts_new.html", context)


@app.post("/receipts")
async def receipts_create(request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON invalido")
    try:
        # Post to the simple inventory endpoint to ensure inventory_balance is updated
        response = await _api_request("POST", "/receipts", token, json=payload)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code not in {200, 201}:
        raise HTTPException(status_code=response.status_code, detail=_safe_detail(response, "Error creando entrada"))
    return response.json()


@app.post("/receipts/print/{gr_id}")
async def receipts_print(gr_id: str, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        response = await _api_request("POST", f"/inventory/labels/print/receipt/{gr_id}", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code not in {200, 201}:
        raise HTTPException(status_code=response.status_code, detail=_safe_detail(response, "Error al encolar impresion"))
    return response.json()


# ------------------------------
# Lists: Receipts, Moves, Products
# ------------------------------
@app.get("/receipts", response_class=HTMLResponse, name="receipts_list")
async def receipts_list(request: Request, q: str | None = None, warehouse: str | None = None, date_from: str | None = None, date_to: str | None = None):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    params = {"q": q, "warehouse": warehouse, "date_from": date_from, "date_to": date_to, "limit": "100"}
    try:
        response = await _api_request("GET", "/inventory/receipts", token, params={k: v for k, v in params.items() if v})
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo cargar entradas")
    items = response.json() if response.status_code == 200 else []
    context = {"request": request, "items": items, "q": q, "warehouse": warehouse, "date_from": date_from, "date_to": date_to}
    return templates.TemplateResponse("receipts_list.html", context)


@app.get("/receipts/export", name="receipts_export")
async def receipts_export(request: Request, q: str | None = None, warehouse: str | None = None, date_from: str | None = None, date_to: str | None = None):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    params = {"q": q, "warehouse": warehouse, "date_from": date_from, "date_to": date_to}
    try:
        response = await _api_request("GET", "/inventory/receipts/export", token, params={k: v for k, v in params.items() if v})
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo exportar entradas")
    return HTMLResponse(content=response.content, media_type=response.headers.get("content-type", "text/csv"), headers={"Content-Disposition": response.headers.get("content-disposition", "attachment; filename=receipts.csv")})


@app.get("/moves/list", response_class=HTMLResponse, name="moves_list")
async def moves_list(request: Request, doc_type: str | None = None, status: str | None = None):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    params = {"doc_type": doc_type, "status_q": status, "limit": "100"}
    try:
        response = await _api_request("GET", "/moves/", token, params={k: v for k, v in params.items() if v})
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo cargar movimientos")
    items = response.json() if response.status_code == 200 else []
    context = {"request": request, "items": items, "doc_type": doc_type, "status": status}
    return templates.TemplateResponse("moves_list.html", context)


@app.get("/moves/export", name="moves_export")
async def moves_export(request: Request, doc_type: str | None = None, status: str | None = None):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    params = {"doc_type": doc_type, "status_q": status}
    try:
        response = await _api_request("GET", "/moves/export", token, params={k: v for k, v in params.items() if v})
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo exportar movimientos")
    return HTMLResponse(content=response.content, media_type=response.headers.get("content-type", "text/csv"), headers={"Content-Disposition": response.headers.get("content-disposition", "attachment; filename=moves.csv")})


@app.get("/products", response_class=HTMLResponse, name="products_list")
async def products_list(request: Request, q: str | None = None, active: str | None = None):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    params: dict[str, str] = {"limit": "200"}
    if q:
        params["q"] = q
    if active in {"0", "1"}:
        params["active"] = "true" if active == "1" else "false"
    try:
        response = await _api_request("GET", "/stock/products", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo cargar artículos")
    items = response.json() if response.status_code == 200 else []
    context = {"request": request, "items": items, "q": q, "active": active}
    return templates.TemplateResponse("products_list.html", context)


@app.get("/products/export", name="products_export")
async def products_export(request: Request, q: str | None = None, active: str | None = None):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    params: dict[str, str] = {}
    if q:
        params["q"] = q
    if active in {"0", "1"}:
        params["active"] = "true" if active == "1" else "false"
    try:
        response = await _api_request("GET", "/stock/products/export", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo exportar artículos")
    return HTMLResponse(content=response.content, media_type=response.headers.get("content-type", "text/csv"), headers={"Content-Disposition": response.headers.get("content-disposition", "attachment; filename=products.csv")})


@app.get("/products/new", response_class=HTMLResponse, name="products_new")
async def products_new(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    context = {"request": request, "form": {"uom": "EA"}, "error": None}
    return templates.TemplateResponse("products_new.html", context)


@app.post("/products/new", response_class=HTMLResponse)
async def products_new_submit(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    payload = {
        "item_code": (form.get("item_code") or "").strip().upper(),
        "item_name": (form.get("item_name") or "").strip(),
        "uom": (form.get("uom") or "EA").strip() or "EA",
        "requires_lot": bool(form.get("requires_lot")),
        "requires_serial": bool(form.get("requires_serial")),
        "active": bool(form.get("active", True)),
    }
    if not payload["item_code"] or not payload["item_name"]:
        context = {"request": request, "form": payload, "error": "Completa código y nombre"}
        return templates.TemplateResponse("products_new.html", context, status_code=400)
    try:
        resp = await _api_request("POST", "/stock/products", token, json=payload)
    except httpx.RequestError:
        context = {"request": request, "form": payload, "error": "No se pudo contactar la API"}
        return templates.TemplateResponse("products_new.html", context, status_code=502)
    if resp.status_code not in {200, 201}:
        context = {"request": request, "form": payload, "error": _safe_detail(resp, "No se pudo guardar el artículo")}
        return templates.TemplateResponse("products_new.html", context, status_code=resp.status_code)
    return RedirectResponse(url=request.url_for("products_list"), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/analytics/abcxyz/template", name="analytics_template_products")
async def analytics_template_products(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    try:
        response = await _api_request("GET", "/analytics/abcxyz/template-from-products", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo generar la plantilla")
    return HTMLResponse(content=response.content, media_type=response.headers.get("content-type", "text/csv"), headers={"Content-Disposition": response.headers.get("content-disposition", "attachment; filename=abcxyz_template.csv")})


@app.get("/products/{code}/edit", response_class=HTMLResponse, name="products_edit")
async def products_edit(request: Request, code: str):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    try:
        resp = await _api_request("GET", f"/stock/products/{code}", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo cargar el artículo")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "Artículo no encontrado"))
    form = resp.json() or {}
    context = {"request": request, "form": form, "error": None}
    return templates.TemplateResponse("products_edit.html", context)


@app.post("/products/{code}/edit", response_class=HTMLResponse)
async def products_edit_submit(request: Request, code: str):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    payload = {
        "item_code": code,  # no se usa para actualizar PK
        "item_name": (form.get("item_name") or "").strip(),
        "uom": (form.get("uom") or "EA").strip() or "EA",
        "requires_lot": bool(form.get("requires_lot")),
        "requires_serial": bool(form.get("requires_serial")),
        "active": bool(form.get("active")),
    }
    if not payload["item_name"]:
        context = {"request": request, "form": {**payload, "item_code": code}, "error": "Completa el nombre"}
        return templates.TemplateResponse("products_edit.html", context, status_code=400)
    try:
        resp = await _api_request("PUT", f"/stock/products/{code}", token, json=payload)
    except httpx.RequestError:
        context = {"request": request, "form": {**payload, "item_code": code}, "error": "No se pudo contactar la API"}
        return templates.TemplateResponse("products_edit.html", context, status_code=502)
    if resp.status_code not in {200, 201}:
        context = {"request": request, "form": {**payload, "item_code": code}, "error": _safe_detail(resp, "No se pudo guardar el artículo")}
        return templates.TemplateResponse("products_edit.html", context, status_code=resp.status_code)
    return RedirectResponse(url=request.url_for("products_list"), status_code=status.HTTP_303_SEE_OTHER)


@app.post("/products/{code}/delete", name="products_delete")
async def products_delete(request: Request, code: str):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    try:
        resp = await _api_request("DELETE", f"/stock/products/{code}", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API")
    if resp.status_code not in {200, 204}:
        # bubble error message; redirect back with status would require flash. For now raise.
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "No se pudo eliminar"))
    return RedirectResponse(url=request.url_for("products_list"), status_code=status.HTTP_303_SEE_OTHER)
# ------------------------------
# Analytics ABC–XYZ (UI routes)
# ------------------------------
@app.get("/analytics/abcxyz", response_class=HTMLResponse)
async def analytics_page(request: Request):
    token = _require_token(request)
    if token is None:
        return RedirectResponse(url=request.url_for("login"), status_code=status.HTTP_303_SEE_OTHER)
    context = {
        "request": request,
        "username": request.cookies.get("username"),
    }
    return templates.TemplateResponse("analytics_abcxyz.html", context)


@app.get("/analytics/abcxyz/latest")
async def analytics_latest(request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        response = await _api_request("GET", "/analytics/abcxyz/latest", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=_safe_detail(response, "Error consultando analytics"))
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")


@app.post("/analytics/abcxyz/ingest")
async def analytics_ingest(request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    form = await request.form()
    period = form.get("period")
    upload = form.get("file")
    if not upload:
        raise HTTPException(status_code=400, detail="file requerido")
    # Default period to current YYYY-MM if not provided
    if not period:
        from datetime import datetime
        period = datetime.now().strftime("%d-%m-%Y")
    if not hasattr(upload, "filename"):
        raise HTTPException(status_code=400, detail="archivo invalido")
    # Proxy multipart to API
    headers = {"Authorization": f"Bearer {token}"}
    if API_SERVICE_TOKEN and "X-Service-Token" not in headers:
        headers["X-Service-Token"] = API_SERVICE_TOKEN
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=API_TIMEOUT) as client:
        try:
            files = {"file": (upload.filename, await upload.read(), upload.content_type or "application/octet-stream")}
            data = {"period": str(period)}
            resp = await client.post("/analytics/abcxyz/ingest", headers=headers, files=files, data=data)
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=_safe_detail(resp, "Error en ingest"))
    try:
        return resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")


@app.get("/analytics/abcxyz/item/{code}")
async def analytics_item(code: str, request: Request):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        response = await _api_request("GET", f"/analytics/abcxyz/item/{code}", token)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=_safe_detail(response, "Error consultando SKU"))
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")


@app.get("/analytics/abcxyz/kpi/sale_rate")
async def analytics_kpi_sale_rate(request: Request, period: str | None = None):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        params = {"period": period} if period else None
        response = await _api_request("GET", "/analytics/abcxyz/kpi/sale_rate", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=_safe_detail(response, "Error consultando KPI"))
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")


@app.get("/analytics/abcxyz/kpi/perfect_order")
async def analytics_kpi_pop(request: Request, period: str | None = None):
    token = _require_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Credenciales requeridas.")
    try:
        params = {"period": period} if period else None
        response = await _api_request("GET", "/analytics/abcxyz/kpi/perfect_order", token, params=params)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="No se pudo contactar la API de picking.")
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=_safe_detail(response, "Error consultando KPI POP"))
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Respuesta invalida desde la API de picking.")


# Quiet well-known probe from Chrome DevTools to avoid noisy 404s
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_probe():
    return JSONResponse({"ok": True})
