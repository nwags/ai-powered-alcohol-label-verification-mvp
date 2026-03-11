from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import get_batch_service, get_ocr_service
from app.domain.enums import LabelType
from app.domain.models import BatchResponse
from app.services.batch_service import BatchService
from app.services.matching_service import coerce_label_type

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

router = APIRouter(tags=["batch"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

BATCH_MODE_LABEL_ONLY = "batch_label_only"
BATCH_MODE_COMPARE = "batch_compare_application"
SUPPORTED_BATCH_MODES = {BATCH_MODE_LABEL_ONLY, BATCH_MODE_COMPARE}


@router.get("/ui/batch")
def batch_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={
            "title": "Batch Analysis",
            "batch_response": None,
            "error_message": None,
            "batch_review_mode": BATCH_MODE_LABEL_ONLY,
            "label_type": LabelType.UNKNOWN.value,
        },
    )


@router.post("/ui/batch")
async def batch_page_submit(
    request: Request,
    batch_review_mode: str = Form(default=BATCH_MODE_LABEL_ONLY),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
    batch_file: UploadFile | None = File(default=None),
    images_archive: UploadFile | None = File(default=None),
    ocr_service: "OCRService" = Depends(get_ocr_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    if batch_review_mode not in SUPPORTED_BATCH_MODES:
        batch_review_mode = BATCH_MODE_LABEL_ONLY
    resolved_label_type = coerce_label_type(label_type)
    try:
        response = await _run_batch_ui(
            batch_review_mode,
            batch_file,
            images_archive,
            ocr_service,
            batch_service,
            resolved_label_type,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="batch.html",
            context={
                "title": "Batch Analysis",
                "batch_response": None,
                "error_message": str(exc),
                "batch_review_mode": batch_review_mode,
                "label_type": resolved_label_type.value,
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
            "batch_review_mode": batch_review_mode,
            "label_type": resolved_label_type.value,
        },
    )


@router.post("/api/v1/batch/analyze", response_model=BatchResponse)
async def analyze_batch_api(
    batch_file: UploadFile = File(...),
    images_archive: UploadFile | None = File(default=None),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
    ocr_service: "OCRService" = Depends(get_ocr_service),
    batch_service: BatchService = Depends(get_batch_service),
) -> BatchResponse:
    try:
        return await _run_batch(
            batch_file,
            images_archive,
            ocr_service,
            batch_service,
            coerce_label_type(label_type),
        )
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
    label_type: LabelType,
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
        label_type=label_type,
    )


async def _run_batch_ui(
    batch_review_mode: str,
    batch_file: UploadFile | None,
    images_archive: UploadFile | None,
    ocr_service: "OCRService",
    batch_service: BatchService,
    label_type: LabelType,
) -> BatchResponse:
    if batch_review_mode == BATCH_MODE_COMPARE:
        if batch_file is None:
            raise ValueError("Batch file is required in Compare to Application Data mode.")
        return await _run_batch(batch_file, images_archive, ocr_service, batch_service, label_type)

    if images_archive is None:
        raise ValueError("Image ZIP archive is required in Label-Only Review mode.")

    archive_name = images_archive.filename or ""
    if archive_name and Path(archive_name).suffix.lower() != ".zip":
        raise ValueError("images_archive must be a .zip file.")

    archive_bytes = await images_archive.read()
    if not archive_bytes:
        raise ValueError("Image ZIP archive was provided but empty.")

    settings = get_settings()
    if len(archive_bytes) > settings.max_upload_bytes:
        raise ValueError(f"Image ZIP exceeds upload size limit of {settings.max_upload_bytes} bytes.")

    return batch_service.analyze_label_only(
        images_archive_bytes=archive_bytes,
        ocr_service=ocr_service,
        label_type=label_type,
    )
