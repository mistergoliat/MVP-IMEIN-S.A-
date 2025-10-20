import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import audit, auth, doc_scan, import_abcxyz, labels, moves, printing, stock
from .routers import analytics
from .routers import inventory_simple
from .routers import labels_simple
from .routers import scanning
from .routers import receipts

app = FastAPI(title="Picking API", version="0.1.0")

# CORS for UI (configurable via API_CORS_ORIGINS)
cors_origins = [
    o.strip()
    for o in os.getenv("API_CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(import_abcxyz.router, prefix="/import/abcxyz", tags=["abcxyz"])
app.include_router(doc_scan.router, prefix="/doc", tags=["doc"])
app.include_router(moves.router, prefix="/moves", tags=["moves"])
app.include_router(printing.router, prefix="/print", tags=["print"])
app.include_router(stock.router, prefix="/stock", tags=["stock"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])
app.include_router(labels.router, tags=["labels"])
app.include_router(analytics.router)
app.include_router(receipts.router)
app.include_router(inventory_simple.router)
app.include_router(labels_simple.router)
app.include_router(scanning.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
