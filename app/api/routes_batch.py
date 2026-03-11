from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import get_batch_service, get_ocr_service
from app.domain.models import BatchResponse
from app.services.batch_service import BatchService

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

router = APIRouter(tags=["batch"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/ui/batch")
def batch_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={
            "title": "Batch Analysis",
            "batch_response": None,
            "error_message": None,
        },
    )


@router.post("/ui/batch")
async def batch_page_submit(
    request: Request,
    batch_file: UploadFile = File(...),
    images_archive: UploadFile | None = File(default=None),
    ocr_service: "OCRService" = Depends(get_ocr_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    try:
        response = await _run_batch(batch_file, images_archive, ocr_service, batch_service)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="batch.html",
            context={
                "title": "Batch Analysis",
                "batch_response": None,
                "error_message": str(exc),
            },
            status_code=422,
        )

    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={
            "title": "Batch Analysis",
            "batch_response": response,
            "error_message": None,
        },
    )


@router.post("/api/v1/batch/analyze", response_model=BatchResponse)
async def analyze_batch_api(
    batch_file: UploadFile = File(...),
    images_archive: UploadFile | None = File(default=None),
    ocr_service: "OCRService" = Depends(get_ocr_service),
    batch_service: BatchService = Depends(get_batch_service),
) -> BatchResponse:
    try:
        return await _run_batch(batch_file, images_archive, ocr_service, batch_service)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "invalid_request", "message": str(exc)}},
        ) from exc


async def _run_batch(
    batch_file: UploadFile,
    images_archive: UploadFile | None,
    ocr_service: "OCRService",
    batch_service: BatchService,
) -> BatchResponse:
    batch_filename = batch_file.filename or ""
    if not batch_filename:
        raise ValueError("Batch file is required.")
    if Path(batch_filename).suffix.lower() not in {".csv", ".json"}:
        raise ValueError("Batch file must be .csv or .json.")

    batch_bytes = await batch_file.read()
    if not batch_bytes:
        raise ValueError("Batch file is empty.")
    settings = get_settings()
    if len(batch_bytes) > settings.max_upload_bytes:
        raise ValueError(f"Batch file exceeds upload size limit of {settings.max_upload_bytes} bytes.")

    archive_bytes: bytes | None = None
    if images_archive is not None:
        archive_name = images_archive.filename or ""
        if archive_name and Path(archive_name).suffix.lower() != ".zip":
            raise ValueError("images_archive must be a .zip file.")
        archive_bytes = await images_archive.read()
        if not archive_bytes:
            raise ValueError("Image ZIP archive was provided but empty.")
        if len(archive_bytes) > settings.max_upload_bytes:
            raise ValueError(f"Image ZIP exceeds upload size limit of {settings.max_upload_bytes} bytes.")

    return batch_service.analyze(
        batch_file_bytes=batch_bytes,
        batch_filename=batch_filename,
        images_archive_bytes=archive_bytes,
        ocr_service=ocr_service,
    )
