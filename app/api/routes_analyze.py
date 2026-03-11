import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import get_settings
from app.dependencies import get_ocr_service
from app.domain.enums import FieldStatus, LabelType, OverallStatus
from app.domain.models import (
    AnalyzeResponse,
    ApplicationData,
    FieldResult,
    OCRSmokeResponse,
    ParsedFields,
)
from app.services.matching_service import build_field_results, coerce_label_type
from app.services.parser_service import parse_ocr_text

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

router = APIRouter(prefix="/api/v1", tags=["analyze"])

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    image: UploadFile = File(...),
    application_json: str = Form(...),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
    ocr_service: "OCRService" = Depends(get_ocr_service),
) -> AnalyzeResponse:
    started = time.perf_counter()

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"error": {"code": "invalid_image", "message": "Uploaded file is not a supported image format."}},
        )

    try:
        app_payload = json.loads(application_json)
        application = ApplicationData.model_validate(app_payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "invalid_request", "message": f"Invalid application_json payload: {exc}"}},
        ) from exc

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "invalid_image", "message": "Image file is empty."}},
        )
    settings = get_settings()
    if len(image_bytes) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "image_too_large",
                    "message": f"Image exceeds upload size limit of {settings.max_upload_bytes} bytes.",
                }
            },
        )

    resolved_label_type = coerce_label_type(label_type)
    ocr, ocr_errors = ocr_service.run_ocr_bytes(image_bytes, source_label=image.filename or "upload")
    try:
        parsed = parse_ocr_text(ocr)
        field_results, overall_status, review_reasons = build_field_results(
            application,
            parsed,
            label_type=resolved_label_type,
            evaluation_mode="compare",
        )
    except Exception as exc:  # pragma: no cover - defensive path
        ocr_errors.append(f"analysis_failed: {exc.__class__.__name__}")
        parsed = ParsedFields()
        field_results = _review_field_results(application)
        overall_status = OverallStatus.REVIEW
        review_reasons = ["Analysis pipeline failed safely; manual review required."]
    timing_ms = int((time.perf_counter() - started) * 1000)

    return AnalyzeResponse(
        request_id=str(uuid.uuid4()),
        overall_status=overall_status,
        timing_ms=timing_ms,
        ocr=ocr,
        parsed=parsed,
        field_results=field_results,
        review_reasons=review_reasons,
        artifacts={},
        errors=ocr_errors,
    )


def _review_field_results(application: ApplicationData) -> dict[str, FieldResult]:
    fields = {
        "brand_name": application.brand_name,
        "class_type": application.class_type,
        "alcohol_content": application.alcohol_content,
        "net_contents": application.net_contents,
        "bottler_producer": application.bottler_producer,
        "country_of_origin": application.country_of_origin,
        "government_warning": application.government_warning,
    }
    return {
        name: FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted,
            detected_value=None,
            notes="Analysis failed; reviewer should verify manually.",
        )
        for name, submitted in fields.items()
    }


@router.get("/demo/sample/{name}", response_model=OCRSmokeResponse)
def demo_sample_ocr(name: str, ocr_service: "OCRService" = Depends(get_ocr_service)) -> OCRSmokeResponse:
    settings = get_settings()
    sample_path = Path(settings.sample_data_dir) / "fixtures" / f"{name}.jpg"
    if not sample_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "invalid_request", "message": f"Unknown sample: {name}"}},
        )

    started = time.perf_counter()
    errors: list[str] = []
    try:
        ocr_result = ocr_service.run_ocr(str(sample_path))
    except Exception as exc:
        ocr_result, fallback_errors = ocr_service.run_ocr_bytes(sample_path.read_bytes(), source_label=sample_path.name)
        errors.append(f"ocr_failed: {exc}")
        errors.extend(fallback_errors)

    return OCRSmokeResponse(
        sample_name=name,
        image_path=str(sample_path),
        timing_ms=int((time.perf_counter() - started) * 1000),
        ocr=ocr_result,
        errors=errors,
    )
