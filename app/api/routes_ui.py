import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import get_dev_diagnostics_service, get_ocr_service
from app.domain.enums import FieldStatus, LabelType, OverallStatus
from app.domain.models import AnalyzeResponse, ApplicationData, FieldResult, ParsedFields
from app.services.matching_service import build_field_results, coerce_label_type, priority_fields_for_label_type
from app.services.parser_service import parse_ocr_text
from app.services.visualization_service import create_annotated_ocr_artifact

if TYPE_CHECKING:
    from app.services.dev_diagnostics_service import DevDiagnosticsService
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
LABEL_TYPE_LABELS = {
    LabelType.UNKNOWN: "Unknown",
    LabelType.BRAND_LABEL: "Brand Label",
    LabelType.OTHER_LABEL: "Other Label",
}


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
            "label_type_options": _label_type_options(),
        },
    )


@router.post("/ui/analyze")
async def analyze_ui(
    request: Request,
    image: UploadFile = File(...),
    review_mode: str = Form(default=REVIEW_MODE_LABEL_ONLY),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
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
    resolved_label_type = coerce_label_type(label_type)

    settings = get_settings()
    form_values = {
        "review_mode": review_mode,
        "label_type": resolved_label_type.value,
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
                "label_type_options": _label_type_options(),
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
                "label_type_options": _label_type_options(),
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
                "label_type_options": _label_type_options(),
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
                "label_type_options": _label_type_options(),
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
                "label_type_options": _label_type_options(),
            },
            status_code=400,
        )

    analysis = _run_analysis(
        image_bytes=image_bytes,
        filename=image.filename or "upload",
        application=application_data,
        label_type=resolved_label_type,
        review_mode=review_mode,
        enable_visualization=settings.enable_visualization,
        storage_dir=Path(settings.storage_dir),
        ocr_service=ocr_service,
    )
    uploaded_path = _persist_upload(image_bytes=image_bytes, original_name=image.filename or "upload")
    field_rows = _build_field_rows(analysis, resolved_label_type)

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
            "label_type_display": LABEL_TYPE_LABELS[resolved_label_type],
        },
    )


@router.get("/ui/diagnostics")
def diagnostics_page(
    request: Request,
    ocr_service: "OCRService" = Depends(get_ocr_service),
    diagnostics_service: "DevDiagnosticsService" = Depends(get_dev_diagnostics_service),
):
    settings = get_settings()
    if not settings.enable_diagnostics_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    context = _build_diagnostics_context(ocr_service=ocr_service, diagnostics_service=diagnostics_service)
    return templates.TemplateResponse(
        request=request,
        name="diagnostics.html",
        context={
            "title": "Developer Diagnostics",
            **context,
        },
    )


@router.get("/ui/diagnostics/coverage/status")
def diagnostics_coverage_status(
    ocr_service: "OCRService" = Depends(get_ocr_service),
    diagnostics_service: "DevDiagnosticsService" = Depends(get_dev_diagnostics_service),
) -> JSONResponse:
    settings = get_settings()
    if not settings.enable_diagnostics_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    context = _build_diagnostics_context(ocr_service=ocr_service, diagnostics_service=diagnostics_service)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "coverage_run": context["coverage_run"],
            "coverage": context["coverage"],
        },
    )


def _build_diagnostics_context(
    ocr_service: "OCRService",
    diagnostics_service: "DevDiagnosticsService",
) -> dict[str, object]:
    settings = get_settings()
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
        "ocr_require_local_models": settings.ocr_require_local_models,
        "ocr_model_source": settings.ocr_model_source,
        "ocr_model_root": str(settings.ocr_model_root),
        "ocr_det_model_dir": str(settings.ocr_det_model_dir) if settings.ocr_det_model_dir else None,
        "ocr_rec_model_dir": str(settings.ocr_rec_model_dir) if settings.ocr_rec_model_dir else None,
        "ocr_cls_model_dir": str(settings.ocr_cls_model_dir) if settings.ocr_cls_model_dir else None,
        "ocr_max_dimension": settings.ocr_max_dimension,
        "ocr_max_variants": settings.ocr_max_variants,
        "ocr_enable_deskew": settings.ocr_enable_deskew,
        "enable_preprocessing": settings.enable_preprocessing,
        "enable_visualization": settings.enable_visualization,
        "storage_dir": str(settings.storage_dir),
        "sample_data_dir": str(settings.sample_data_dir),
        "coverage_dir": str(settings.coverage_dir),
        "max_upload_bytes": settings.max_upload_bytes,
    }
    coverage = _load_coverage_summary(settings.coverage_dir)
    coverage_run = diagnostics_service.coverage_status()
    recent_logs = diagnostics_service.recent_logs(limit=150)

    return {
        "ocr_status": ocr_status,
        "readiness": readiness,
        "config_summary": config_summary,
        "paths": {
            "runtime_storage": str(settings.storage_dir),
            "sample_data": str(settings.sample_data_dir),
        },
        "coverage": coverage,
        "coverage_run": coverage_run,
        "recent_logs": recent_logs,
    }


@router.post("/ui/diagnostics/coverage")
def trigger_diagnostics_coverage(
    diagnostics_service: "DevDiagnosticsService" = Depends(get_dev_diagnostics_service),
):
    settings = get_settings()
    if not settings.enable_diagnostics_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    diagnostics_service.trigger_coverage()
    return RedirectResponse(url="/ui/diagnostics", status_code=status.HTTP_303_SEE_OTHER)


def _run_analysis(
    image_bytes: bytes,
    filename: str,
    application: ApplicationData,
    label_type: LabelType,
    review_mode: str,
    enable_visualization: bool,
    storage_dir: Path,
    ocr_service: "OCRService",
) -> AnalyzeResponse:
    started = time.perf_counter()
    ocr, ocr_errors = ocr_service.run_ocr_bytes(image_bytes, source_label=filename)
    artifacts: dict[str, str] = {}
    if enable_visualization:
        annotated_path = create_annotated_ocr_artifact(image_bytes=image_bytes, ocr=ocr, storage_dir=storage_dir)
        if annotated_path:
            artifacts["annotated_image_path"] = f"/storage/{annotated_path}"
    try:
        parsed = parse_ocr_text(ocr)
        field_results, overall_status, review_reasons = build_field_results(
            application,
            parsed,
            label_type=label_type,
            evaluation_mode="label_only" if review_mode == REVIEW_MODE_LABEL_ONLY else "compare",
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
        artifacts=artifacts,
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


def _build_field_rows(analysis: AnalyzeResponse, label_type: LabelType) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    priority_fields = set(priority_fields_for_label_type(label_type))
    is_hint_mode = label_type != LabelType.UNKNOWN
    for field_name, label in FIELD_LABELS.items():
        result = analysis.field_results.get(field_name)
        if result is None:
            continue
        notes = result.notes
        if is_hint_mode and field_name not in priority_fields:
            info_note = "Informational for selected label type."
            notes = f"{notes} {info_note}".strip() if notes else info_note
        rows.append(
            {
                "field_name": field_name,
                "label": label,
                "submitted_value": result.submitted_value,
                "detected_value": result.detected_value,
                "status": result.status.value,
                "notes": notes,
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
        "label_type": LabelType.UNKNOWN.value,
        "brand_name": "",
        "class_type": "",
        "alcohol_content": "",
        "net_contents": "",
        "bottler_producer": "",
        "country_of_origin": "",
        "government_warning": "",
        "application_json": "",
    }


def _label_type_options() -> list[tuple[str, str]]:
    return [(value.value, label) for value, label in LABEL_TYPE_LABELS.items()]


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
    raw_missing_assets = status_payload.get("model_assets_missing", [])
    if isinstance(raw_missing_assets, list):
        missing_assets = [str(item) for item in raw_missing_assets]
    else:
        missing_assets = []

    return {
        "state": state,
        "ready": bool(status_payload.get("ready", False)),
        "message": message_by_state.get(state, "OCR status unavailable."),
        "error": status_payload.get("error"),
        "model_source": status_payload.get("model_source"),
        "require_local_models": bool(status_payload.get("require_local_models", False)),
        "model_assets_ready": bool(status_payload.get("model_assets_ready", False)),
        "model_assets_missing": missing_assets,
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


def _load_coverage_summary(coverage_dir: Path) -> dict[str, object]:
    summary_path = coverage_dir / "coverage.json"
    html_index_path = coverage_dir / "html" / "index.html"
    payload: dict[str, object] = {
        "available": False,
        "summary_path": str(summary_path),
        "html_url": f"/storage/coverage/html/index.html" if html_index_path.exists() else None,
        "total_percent": None,
        "covered_lines": None,
        "num_statements": None,
    }

    if not summary_path.exists():
        return payload

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return payload

    totals = summary.get("totals", {})
    if not isinstance(totals, dict):
        return payload

    payload["available"] = True
    payload["total_percent"] = totals.get("percent_covered_display")
    payload["covered_lines"] = totals.get("covered_lines")
    payload["num_statements"] = totals.get("num_statements")
    return payload
