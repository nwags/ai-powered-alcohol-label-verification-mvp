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
from app.domain.enums import FieldStatus, LabelType, OverallStatus, ProductProfile
from app.domain.models import AnalyzeResponse, ApplicationData, FieldResult, OCREvidenceLine, ParsedFields
from app.services.inference_service import coerce_product_profile, infer_label_type, infer_product_profile
from app.services.matching_service import build_field_results, coerce_label_type
from app.services.parser_service import parse_ocr_text
from app.services.rule_registry import build_rule_trace
from app.services.result_presenter import build_result_view_from_analysis
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
REVIEW_MODE_LABELS = {
    REVIEW_MODE_LABEL_ONLY: "Label-Only Review",
    REVIEW_MODE_COMPARE: "Compare to Application Data",
}
LABEL_TYPE_LABELS = {
    LabelType.UNKNOWN: "Unknown",
    LabelType.BRAND_LABEL: "Brand Label",
    LabelType.OTHER_LABEL: "Other Label",
}
PRODUCT_PROFILE_LABELS = {
    ProductProfile.UNKNOWN: "Unknown / Auto",
    ProductProfile.DISTILLED_SPIRITS: "Distilled Spirits",
    ProductProfile.MALT_BEVERAGE: "Malt Beverage",
    ProductProfile.WINE: "Wine",
}


@router.get("/")
def index(request: Request, ocr_service: "OCRService" = Depends(get_ocr_service)):
    ocr_status = _format_ocr_status(ocr_service.get_status())
    settings = get_settings()
    form_values = _empty_form_values()
    form_values["review_mode"] = _coerce_review_mode(form_values["review_mode"], settings)
    form_values["label_type"] = _coerce_label_type_allowed(form_values["label_type"], settings).value
    form_values["product_profile"] = _coerce_product_profile_allowed(form_values["product_profile"], settings).value
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "AI-Powered Alcohol Label Verification",
            "field_labels": FIELD_LABELS,
            "form_values": form_values,
            "error_message": None,
            "ocr_status": ocr_status,
            "enable_diagnostics_ui": settings.enable_diagnostics_ui,
            "enable_batch_ui": settings.enable_batch_ui,
            "review_mode_options": _review_mode_options(settings),
            "label_type_options": _label_type_options(settings),
            "product_profile_options": _product_profile_options(settings),
        },
    )


@router.post("/ui/analyze")
async def analyze_ui(
    request: Request,
    image: UploadFile = File(...),
    review_mode: str = Form(default=REVIEW_MODE_LABEL_ONLY),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
    product_profile: str = Form(default=ProductProfile.UNKNOWN.value),
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
    settings = get_settings()
    review_mode = _coerce_review_mode(review_mode, settings)
    resolved_label_type = _coerce_label_type_allowed(label_type, settings)
    resolved_product_profile = _coerce_product_profile_allowed(product_profile, settings)
    form_values = {
        "review_mode": review_mode,
        "label_type": resolved_label_type.value,
        "product_profile": resolved_product_profile.value,
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
                "enable_batch_ui": settings.enable_batch_ui,
                "review_mode_options": _review_mode_options(settings),
                "label_type_options": _label_type_options(settings),
                "product_profile_options": _product_profile_options(settings),
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
                "enable_batch_ui": settings.enable_batch_ui,
                "review_mode_options": _review_mode_options(settings),
                "label_type_options": _label_type_options(settings),
                "product_profile_options": _product_profile_options(settings),
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
                "enable_batch_ui": settings.enable_batch_ui,
                "review_mode_options": _review_mode_options(settings),
                "label_type_options": _label_type_options(settings),
                "product_profile_options": _product_profile_options(settings),
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
                "enable_batch_ui": settings.enable_batch_ui,
                "review_mode_options": _review_mode_options(settings),
                "label_type_options": _label_type_options(settings),
                "product_profile_options": _product_profile_options(settings),
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
                "enable_batch_ui": settings.enable_batch_ui,
                "review_mode_options": _review_mode_options(settings),
                "label_type_options": _label_type_options(settings),
                "product_profile_options": _product_profile_options(settings),
            },
            status_code=400,
        )

    uploaded_path = _persist_upload(image_bytes=image_bytes, original_name=image.filename or "upload")
    uploaded_image_url = f"/storage/{uploaded_path}"
    analysis = _run_analysis(
        image_bytes=image_bytes,
        filename=image.filename or "upload",
        application=application_data,
        label_type=resolved_label_type,
        product_profile=resolved_product_profile,
        review_mode=review_mode,
        enable_visualization=settings.enable_visualization,
        storage_dir=Path(settings.storage_dir),
        ocr_service=ocr_service,
    )
    result_view = build_result_view_from_analysis(
        analysis=analysis,
        review_mode=review_mode,
        field_labels=FIELD_LABELS,
        label_type_labels=LABEL_TYPE_LABELS,
        product_profile_labels=PRODUCT_PROFILE_LABELS,
        label_type_hint=resolved_label_type,
        product_profile_hint=resolved_product_profile,
        uploaded_filename=image.filename or "upload",
        uploaded_image_url=uploaded_image_url,
        annotated_image_url=analysis.artifacts.get("annotated_image_path"),
        page_heading="Analysis Result",
        nav_label="Analyze Another Label",
        nav_url="/",
    )
    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context={
            "title": "Analysis Result",
            "result_view": result_view,
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
    if (
        isinstance(coverage_run, dict)
        and coverage_run.get("state") == "failure"
        and bool(coverage.get("available"))
        and isinstance(coverage_run.get("message"), str)
    ):
        coverage_run["message"] = (
            f"{coverage_run['message']} Last successful coverage summary artifacts are still available below."
        )
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
    product_profile: ProductProfile,
    review_mode: str,
    enable_visualization: bool,
    storage_dir: Path,
    ocr_service: "OCRService",
) -> AnalyzeResponse:
    started = time.perf_counter()
    variant_image = None
    variant_metadata: dict[str, object] = {}
    try:
        ocr_run = ocr_service.run_ocr_bytes(
            image_bytes,
            source_label=filename,
            return_variant_image=True,
            return_variant_metadata=True,
        )
    except TypeError:
        ocr_run = ocr_service.run_ocr_bytes(image_bytes, source_label=filename)

    if isinstance(ocr_run, tuple) and len(ocr_run) == 4:
        ocr, ocr_errors, variant_image, variant_metadata = ocr_run
    elif isinstance(ocr_run, tuple) and len(ocr_run) == 3:
        ocr, ocr_errors, variant_image = ocr_run
    else:
        ocr, ocr_errors = ocr_run
    artifacts: dict[str, object] = {}
    evidence_lines: list[OCREvidenceLine] = []
    if isinstance(variant_metadata.get("evidence_lines"), list):
        for raw in variant_metadata["evidence_lines"]:
            if isinstance(raw, dict):
                try:
                    evidence_lines.append(OCREvidenceLine.model_validate(raw))
                except Exception:
                    continue

    try:
        pre_parsed = parse_ocr_text(ocr, product_profile=ProductProfile.UNKNOWN)
        profile_inference = infer_product_profile(selected_hint=product_profile, ocr=ocr, parsed=pre_parsed)
        effective_profile = coerce_product_profile(profile_inference.get("effective_profile"))
        parsed = parse_ocr_text(ocr, product_profile=effective_profile)
        label_inference = infer_label_type(
            selected_hint=label_type,
            effective_profile=effective_profile,
            ocr=ocr,
            parsed=parsed,
        )
        effective_label_type = coerce_label_type(label_inference.get("effective_label_type"))
        rule_ids_by_field: dict[str, list[str]] = {}
        if isinstance(profile_inference.get("rule_ids"), list):
            rule_ids_by_field["profile_inference"] = [str(value) for value in profile_inference["rule_ids"]]
        if isinstance(label_inference.get("rule_ids"), list):
            rule_ids_by_field["label_type_inference"] = [str(value) for value in label_inference["rule_ids"]]
        field_results, overall_status, review_reasons = build_field_results(
            application,
            parsed,
            label_type=effective_label_type,
            evaluation_mode="label_only" if review_mode == REVIEW_MODE_LABEL_ONLY else "compare",
            product_profile=effective_profile,
            rule_ids_by_field=rule_ids_by_field,
        )
        artifacts["inference"] = {"product_profile": profile_inference, "label_type": label_inference}
        artifacts["rule_trace"] = build_rule_trace(rule_ids_by_field)
        if evidence_lines:
            artifacts["ocr_evidence"] = [line.model_dump() for line in evidence_lines]
            artifacts["parsed_field_evidence"] = _build_parsed_field_evidence_links(parsed=parsed, evidence_lines=evidence_lines)
        if enable_visualization:
            source_variant_id = variant_metadata.get("source_variant_id")
            bbox_space_hint = variant_metadata.get("bbox_space")
            annotation_result = create_annotated_ocr_artifact(
                image_bytes=image_bytes,
                ocr=ocr,
                storage_dir=storage_dir,
                parsed=parsed,
                base_image=variant_image,
                evidence_lines=evidence_lines,
                source_variant_id=str(source_variant_id) if isinstance(source_variant_id, str) and source_variant_id else None,
                bbox_space_hint=str(bbox_space_hint) if isinstance(bbox_space_hint, str) and bbox_space_hint else "unknown",
                allow_legacy_fallback=False,
                return_metadata=True,
            )
            annotated_path, annotation_payload, annotation_debug = annotation_result
            artifacts["annotation"] = annotation_payload
            artifacts["annotation_debug"] = annotation_debug
            if annotated_path:
                artifacts["annotated_image_path"] = f"/storage/{annotated_path}"
            elif ocr.lines:
                ocr_errors.append("annotation_unavailable: no drawable OCR bounding boxes were available")
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


def _empty_form_values() -> dict[str, str]:
    return {
        "review_mode": REVIEW_MODE_LABEL_ONLY,
        "label_type": LabelType.UNKNOWN.value,
        "product_profile": ProductProfile.UNKNOWN.value,
        "brand_name": "",
        "class_type": "",
        "alcohol_content": "",
        "net_contents": "",
        "bottler_producer": "",
        "country_of_origin": "",
        "government_warning": "",
        "application_json": "",
    }


def _review_mode_options(settings: object) -> list[tuple[str, str]]:
    values = _allowed_review_modes(settings)
    return [(value, REVIEW_MODE_LABELS[value]) for value in values]


def _label_type_options(settings: object) -> list[tuple[str, str]]:
    values = _allowed_label_types(settings)
    return [(value.value, LABEL_TYPE_LABELS[value]) for value in values]


def _product_profile_options(settings: object) -> list[tuple[str, str]]:
    values = _allowed_product_profiles(settings)
    return [(value.value, PRODUCT_PROFILE_LABELS[value]) for value in values]


def _coerce_review_mode(value: str, settings: object) -> str:
    allowed = _allowed_review_modes(settings)
    if value in allowed:
        return value
    return REVIEW_MODE_LABEL_ONLY if REVIEW_MODE_LABEL_ONLY in allowed else allowed[0]


def _coerce_label_type_allowed(value: str, settings: object) -> LabelType:
    candidate = coerce_label_type(value)
    allowed = _allowed_label_types(settings)
    if candidate in allowed:
        return candidate
    return LabelType.UNKNOWN if LabelType.UNKNOWN in allowed else allowed[0]


def _coerce_product_profile_allowed(value: str, settings: object) -> ProductProfile:
    candidate = coerce_product_profile(value)
    allowed = _allowed_product_profiles(settings)
    if candidate in allowed:
        return candidate
    return ProductProfile.UNKNOWN if ProductProfile.UNKNOWN in allowed else allowed[0]


def _allowed_review_modes(settings: object) -> list[str]:
    allowed = _parse_allowed_csv(getattr(settings, "allowed_review_modes", None), valid_order=list(REVIEW_MODE_LABELS.keys()))
    return allowed or [REVIEW_MODE_LABEL_ONLY, REVIEW_MODE_COMPARE]


def _allowed_label_types(settings: object) -> list[LabelType]:
    raw_values = _parse_allowed_csv(
        getattr(settings, "allowed_label_types", None),
        valid_order=[value.value for value in LABEL_TYPE_LABELS.keys()],
    )
    values = [coerce_label_type(raw) for raw in raw_values]
    if values:
        return values
    return [LabelType.UNKNOWN, LabelType.BRAND_LABEL, LabelType.OTHER_LABEL]


def _allowed_product_profiles(settings: object) -> list[ProductProfile]:
    raw_values = _parse_allowed_csv(
        getattr(settings, "allowed_product_profiles", None),
        valid_order=[value.value for value in PRODUCT_PROFILE_LABELS.keys()],
    )
    values = [coerce_product_profile(raw) for raw in raw_values]
    if values:
        return values
    return [ProductProfile.UNKNOWN, ProductProfile.DISTILLED_SPIRITS, ProductProfile.MALT_BEVERAGE, ProductProfile.WINE]


def _parse_allowed_csv(raw_value: object, valid_order: list[str]) -> list[str]:
    if not isinstance(raw_value, str):
        return valid_order
    seen: set[str] = set()
    output: list[str] = []
    for part in raw_value.split(","):
        normalized = part.strip().lower()
        if normalized in valid_order and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output or valid_order


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


def _build_parsed_field_evidence_links(parsed: ParsedFields, evidence_lines: list[OCREvidenceLine]) -> dict[str, dict[str, object]]:
    field_values = {
        "brand_name": parsed.brand_name.value,
        "class_type": parsed.class_type.value,
        "alcohol_content": parsed.alcohol_content.raw,
        "net_contents": parsed.net_contents.raw,
        "bottler_producer": parsed.bottler_producer.value,
        "country_of_origin": parsed.country_of_origin.value,
        "government_warning": parsed.government_warning.value,
    }
    output: dict[str, dict[str, object]] = {}
    for field_name, value in field_values.items():
        if not value:
            continue
        tokens = [token for token in " ".join(value.lower().split()).split(" ") if len(token) >= 5]
        if not tokens:
            continue
        matched_ids: list[str] = []
        confidences: list[float] = []
        for line in evidence_lines:
            lowered = line.text.lower()
            if any(token in lowered for token in tokens):
                matched_ids.append(line.id)
                confidences.append(line.confidence)
        if matched_ids:
            avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
            output[field_name] = {
                "supporting_evidence_ids": matched_ids,
                "confidence_source": "ocr_evidence_average",
                "confidence_value": avg_confidence,
            }
    return output


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
