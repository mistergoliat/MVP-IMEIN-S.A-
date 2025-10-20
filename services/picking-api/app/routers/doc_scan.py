from fastapi import APIRouter, HTTPException

from .. import schemas
from ..barcodes import BarcodeError, parse_hid_scan

router = APIRouter()


@router.post("/scan", response_model=schemas.DocScanResponse)
async def scan_document(payload: schemas.DocScanRequest) -> schemas.DocScanResponse:
    try:
        data = parse_hid_scan(payload.scan)
    except BarcodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return schemas.DocScanResponse(**data)
