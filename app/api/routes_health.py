from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.dependencies import get_ocr_service

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(ocr_service: "OCRService" = Depends(get_ocr_service)) -> JSONResponse:
    settings = get_settings()
    storage_ok = Path(settings.storage_dir).exists()
    db_ok = True
    ocr_status = ocr_service.get_status()
    ocr_loaded = bool(ocr_status["ready"])
    is_ready = storage_ok and db_ok and ocr_loaded

    payload = {
        "status": "ready" if is_ready else "not_ready",
        "ocr_loaded": ocr_loaded,
        "ocr_state": ocr_status["state"],
        "storage_ok": storage_ok,
        "db_ok": db_ok,
    }

    return JSONResponse(
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


@router.get("/api/v1/ocr/status")
def ocr_status(ocr_service: "OCRService" = Depends(get_ocr_service)) -> dict[str, str | bool | None]:
    status_payload = ocr_service.get_status()
    state = str(status_payload["state"])
    error = status_payload.get("error")

    message_by_state = {
        "cold": "OCR is cold and waiting to warm up.",
        "warming": "OCR warmup is in progress.",
        "ready": "OCR is ready.",
        "failed": "OCR warmup failed. Manual review only until OCR recovers.",
    }
    return {
        "state": state,
        "ready": bool(status_payload["ready"]),
        "message": message_by_state.get(state, "OCR status unavailable."),
        "error": str(error) if error else None,
    }
