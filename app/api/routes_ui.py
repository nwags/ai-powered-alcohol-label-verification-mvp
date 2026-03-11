import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import get_ocr_service
from app.domain.enums import FieldStatus, OverallStatus
from app.domain.models import AnalyzeResponse, ApplicationData, FieldResult, ParsedFields
from app.services.matching_service import build_field_results
from app.services.parser_service import parse_ocr_text

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

FIELD_LABELS = {
    "brand_name": "Brand Name",
    "class_type": "Class / Type",
    "alcohol_content": "Alcohol Content",
    "net_contents": "Net Contents",
    "bottler_producer": "Bottler / Producer",
    "country_of_origin": "Country of Origin",
    "government_warning": "Government Warning",
}

REVIEW_MODE_LABEL_ONLY = "label_only"
REVIEW_MODE_COMPARE = "compare_application"
SUPPORTED_REVIEW_MODES = {REVIEW_MODE_LABEL_ONLY, REVIEW_MODE_COMPARE}


@router.get("/")
def index(request: Request, ocr_service: "OCRService" = Depends(get_ocr_service)):
    ocr_status = _format_ocr_status(ocr_service.get_status())
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "AI-Powered Alcohol Label Verification",
            "field_labels": FIELD_LABELS,
            "form_values": _empty_form_values(),
            "error_message": None,
            "ocr_status": ocr_status,
            "enable_diagnostics_ui": settings.enable_diagnostics_ui,
        },
    )


@router.post("/ui/analyze")
async def analyze_ui(
    request: Request,
    image: UploadFile = File(...),
    review_mode: str = Form(default=REVIEW_MODE_LABEL_ONLY),
    application_json: str = Form(default=""),
    brand_name: str = Form(default=""),
    class_type: str = Form(default=""),
    alcohol_content: str = Form(default=""),
    net_contents: str = Form(default=""),
    bottler_producer: str = Form(default=""),
    country_of_origin: str = Form(default=""),
    government_warning: str = Form(default=""),
    ocr_service: "OCRService" = Depends(get_ocr_service),
):
    if review_mode not in SUPPORTED_REVIEW_MODES:
        review_mode = REVIEW_MODE_LABEL_ONLY

    settings = get_settings()
    form_values = {
        "review_mode": review_mode,
        "brand_name": brand_name,
        "class_type": class_type,
        "alcohol_content": alcohol_content,
        "net_contents": net_contents,
        "bottler_producer": bottler_producer,
        "country_of_origin": country_of_origin,
        "government_warning": government_warning,
        "application_json": application_json,
    }
    ocr_status = _format_ocr_status(ocr_service.get_status())
    if not ocr_status["ready"]:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": "AI-Powered Alcohol Label Verification",
                "field_labels": FIELD_LABELS,
                "form_values": form_values,
                "error_message": "OCR is not ready yet. Please wait for warmup to complete.",
                "ocr_status": ocr_status,
                "enable_diagnostics_ui": settings.enable_diagnostics_ui,
            },
            status_code=503,
        )

    try:
        application_data = _build_application_data(application_json, form_values, review_mode=review_mode)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": "AI-Powered Alcohol Label Verification",
                "field_labels": FIELD_LABELS,
                "form_values": form_values,
                "error_message": str(exc),
                "ocr_status": ocr_status,
                "enable_diagnostics_ui": settings.enable_diagnostics_ui,
            },
            status_code=422,
        )

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": "AI-Powered Alcohol Label Verification",
                "field_labels": FIELD_LABELS,
                "form_values": form_values,
                "error_message": "Please upload a PNG, JPG, JPEG, or WEBP image.",
                "ocr_status": ocr_status,
                "enable_diagnostics_ui": settings.enable_diagnostics_ui,
            },
            status_code=415,
        )

    image_bytes = await image.read()
    if not image_bytes:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": "AI-Powered Alcohol Label Verification",
                "field_labels": FIELD_LABELS,
                "form_values": form_values,
                "error_message": "The uploaded image was empty.",
                "ocr_status": ocr_status,
                "enable_diagnostics_ui": settings.enable_diagnostics_ui,
            },
            status_code=400,
        )
    if len(image_bytes) > settings.max_upload_bytes:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": "AI-Powered Alcohol Label Verification",
                "field_labels": FIELD_LABELS,
                "form_values": form_values,
                "error_message": f"Image exceeds upload size limit of {settings.max_upload_bytes} bytes.",
                "ocr_status": ocr_status,
                "enable_diagnostics_ui": settings.enable_diagnostics_ui,
            },
            status_code=400,
        )

    analysis = _run_analysis(image_bytes=image_bytes, filename=image.filename or "upload", application=application_data, ocr_service=ocr_service)
    uploaded_path = _persist_upload(image_bytes=image_bytes, original_name=image.filename or "upload")
    field_rows = _build_field_rows(analysis)

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context={
            "title": "Analysis Result",
            "analysis": analysis,
            "field_rows": field_rows,
            "uploaded_image_url": f"/storage/{uploaded_path}",
            "annotated_image_url": analysis.artifacts.get("annotated_image_path"),
            "overall_recommendation": _overall_recommendation(analysis.overall_status.value),
            "ocr_errors": analysis.errors,
            "review_reasons": analysis.review_reasons,
        },
    )


@router.get("/ui/diagnostics")
def diagnostics_page(request: Request, ocr_service: "OCRService" = Depends(get_ocr_service)):
    settings = get_settings()
    if not settings.enable_diagnostics_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    ocr_status = _format_ocr_status(ocr_service.get_status())
    storage_exists = Path(settings.storage_dir).exists()
    storage_writable = _is_storage_writable(settings.storage_dir)
    db_ok = True
    is_ready = storage_exists and db_ok and bool(ocr_status["ready"])

    readiness = {
        "status": "ready" if is_ready else "not_ready",
        "ocr_loaded": bool(ocr_status["ready"]),
        "ocr_state": ocr_status["state"],
        "storage_ok": storage_exists,
        "storage_writable": storage_writable,
        "db_ok": db_ok,
    }

    config_summary = {
        "app_env": settings.app_env,
        "log_level": settings.log_level,
        "enable_diagnostics_ui": settings.enable_diagnostics_ui,
        "enable_ocr": settings.enable_ocr,
        "ocr_use_gpu": settings.ocr_use_gpu,
        "ocr_max_dimension": settings.ocr_max_dimension,
        "ocr_max_variants": settings.ocr_max_variants,
        "ocr_enable_deskew": settings.ocr_enable_deskew,
        "enable_preprocessing": settings.enable_preprocessing,
        "enable_visualization": settings.enable_visualization,
        "storage_dir": str(settings.storage_dir),
        "sample_data_dir": str(settings.sample_data_dir),
        "max_upload_bytes": settings.max_upload_bytes,
    }

    return templates.TemplateResponse(
        request=request,
        name="diagnostics.html",
        context={
            "title": "Developer Diagnostics",
            "ocr_status": ocr_status,
            "readiness": readiness,
            "config_summary": config_summary,
            "paths": {
                "runtime_storage": str(settings.storage_dir),
                "sample_data": str(settings.sample_data_dir),
            },
        },
    )


def _run_analysis(image_bytes: bytes, filename: str, application: ApplicationData, ocr_service: "OCRService") -> AnalyzeResponse:
    started = time.perf_counter()
    ocr, ocr_errors = ocr_service.run_ocr_bytes(image_bytes, source_label=filename)
    try:
        parsed = parse_ocr_text(ocr)
        field_results, overall_status, review_reasons = build_field_results(application, parsed)
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


def _build_application_data(application_json: str, form_values: dict[str, str], review_mode: str) -> ApplicationData:
    if review_mode == REVIEW_MODE_LABEL_ONLY:
        return ApplicationData()

    if application_json and application_json.strip():
        try:
            payload = json.loads(application_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse Application JSON: {exc}") from exc
        return ApplicationData.model_validate(payload)

    payload = {
        "brand_name": form_values.get("brand_name") or None,
        "class_type": form_values.get("class_type") or None,
        "alcohol_content": form_values.get("alcohol_content") or None,
        "net_contents": form_values.get("net_contents") or None,
        "bottler_producer": form_values.get("bottler_producer") or None,
        "country_of_origin": form_values.get("country_of_origin") or None,
        "government_warning": form_values.get("government_warning") or None,
    }
    return ApplicationData.model_validate(payload)


def _persist_upload(image_bytes: bytes, original_name: str) -> str:
    settings = get_settings()
    upload_dir = Path(settings.storage_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix if Path(original_name).suffix else ".jpg"
    target_name = f"{uuid.uuid4().hex}{suffix}"
    target_path = upload_dir / target_name
    target_path.write_bytes(image_bytes)
    return f"uploads/{target_name}"


def _build_field_rows(analysis: AnalyzeResponse) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for field_name, label in FIELD_LABELS.items():
        result = analysis.field_results.get(field_name)
        if result is None:
            continue
        rows.append(
            {
                "field_name": field_name,
                "label": label,
                "submitted_value": result.submitted_value,
                "detected_value": result.detected_value,
                "status": result.status.value,
                "notes": result.notes,
            }
        )
    return rows


def _overall_recommendation(overall_status: str) -> str:
    if overall_status == "match":
        return "Looks consistent. Reviewer can do a quick confirmation."
    if overall_status == "normalized_match":
        return "Mostly consistent after normalization. Reviewer should spot-check."
    if overall_status == "mismatch":
        return "Potential mismatch found. Reviewer should inspect differences carefully."
    return "Manual review required due to uncertainty or missing evidence."


def _empty_form_values() -> dict[str, str]:
    return {
        "review_mode": REVIEW_MODE_LABEL_ONLY,
        "brand_name": "",
        "class_type": "",
        "alcohol_content": "",
        "net_contents": "",
        "bottler_producer": "",
        "country_of_origin": "",
        "government_warning": "",
        "application_json": "",
    }


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


def _format_ocr_status(status_payload: dict[str, object]) -> dict[str, object]:
    state = str(status_payload.get("state", "cold"))
    message_by_state = {
        "cold": "OCR is cold and waiting to warm up.",
        "warming": "OCR warmup is in progress.",
        "ready": "OCR is ready.",
        "failed": "OCR warmup failed. Manual review only until OCR recovers.",
    }
    return {
        "state": state,
        "ready": bool(status_payload.get("ready", False)),
        "message": message_by_state.get(state, "OCR status unavailable."),
        "error": status_payload.get("error"),
    }


def _is_storage_writable(storage_dir: Path) -> bool:
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=storage_dir, prefix="diag-", suffix=".tmp", delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
        return True
    except Exception:
        return False
