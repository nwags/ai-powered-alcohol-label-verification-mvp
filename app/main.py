from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_analyze import router as analyze_router
from app.api.routes_batch import router as batch_router
from app.api.routes_health import router as health_router
from app.api.routes_ui import router as ui_router
from app.config import Settings, get_settings
from app.logging_config import configure_logging


def _ensure_runtime_dirs(settings: Settings) -> None:
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.storage_dir) / "uploads").mkdir(parents=True, exist_ok=True)
    (Path(settings.storage_dir) / "outputs").mkdir(parents=True, exist_ok=True)


settings = get_settings()
_ensure_runtime_dirs(settings)
app = FastAPI(title=settings.app_title)

app.include_router(health_router)
app.include_router(ui_router)
app.include_router(analyze_router)
app.include_router(batch_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/storage", StaticFiles(directory=str(settings.storage_dir)), name="storage")


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    _ensure_runtime_dirs(settings)
    from app.dependencies import get_ocr_service

    get_ocr_service().start_warmup_background()


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "invalid_request", "message": str(exc.detail)}},
    )
