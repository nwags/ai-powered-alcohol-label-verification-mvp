import json
from pathlib import Path
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import get_batch_service, get_ocr_service
from app.domain.enums import LabelType, ProductProfile
from app.domain.models import BatchResponse
from app.services.batch_service import BatchService
from app.services.inference_service import coerce_product_profile
from app.services.matching_service import coerce_label_type

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

router = APIRouter(tags=["batch"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

BATCH_MODE_LABEL_ONLY = "batch_label_only"
BATCH_MODE_COMPARE = "batch_compare_application"
SUPPORTED_BATCH_MODES = {BATCH_MODE_LABEL_ONLY, BATCH_MODE_COMPARE}
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
LABEL_ONLY_UI_STATUS_MAP = {
    "match": "pass",
    "normalized_match": "pass",
    "review": "review",
    "mismatch": "fail",
}


@router.get("/ui/batch")
def batch_page(request: Request):
    settings = get_settings()
    if not settings.enable_batch_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    batch_mode = _default_batch_mode(settings)
    label_type = _default_label_type(settings)
    product_profile = _default_product_profile(settings)
    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={
            "title": "Batch Analysis",
            "batch_response": None,
            "error_message": None,
            "batch_review_mode": batch_mode,
            "label_type": label_type.value,
            "product_profile": product_profile.value,
            "batch_review_mode_options": _batch_review_mode_options(settings),
            "label_type_options": _label_type_options(settings),
            "product_profile_options": _product_profile_options(settings),
            "batch_elapsed_ms": None,
            "batch_mode_used": None,
            "processed_count": None,
            "batch_display_rows": [],
            "batch_display_summary": None,
        },
    )


@router.post("/ui/batch")
async def batch_page_submit(
    request: Request,
    batch_review_mode: str = Form(default=BATCH_MODE_LABEL_ONLY),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
    product_profile: str = Form(default=ProductProfile.UNKNOWN.value),
    batch_file: UploadFile | None = File(default=None),
    images_archive: UploadFile | None = File(default=None),
    ocr_service: "OCRService" = Depends(get_ocr_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    settings = get_settings()
    if not settings.enable_batch_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    batch_review_mode = _coerce_batch_mode(batch_review_mode, settings)
    resolved_label_type = _coerce_label_type_allowed(label_type, settings)
    resolved_product_profile = _coerce_product_profile_allowed(product_profile, settings)
    started = time.perf_counter()
    try:
        response = await _run_batch_ui(
            batch_review_mode,
            batch_file,
            images_archive,
            ocr_service,
            batch_service,
            resolved_label_type,
            resolved_product_profile,
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
                "product_profile": resolved_product_profile.value,
                "batch_review_mode_options": _batch_review_mode_options(settings),
                "label_type_options": _label_type_options(settings),
                "product_profile_options": _product_profile_options(settings),
                "batch_elapsed_ms": None,
                "batch_mode_used": batch_review_mode,
                "processed_count": None,
                "batch_display_rows": [],
                "batch_display_summary": None,
            },
            status_code=422,
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    display_rows = _build_display_rows(response, batch_review_mode)
    display_summary = _build_display_summary(response, batch_review_mode, display_rows)

    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={
            "title": "Batch Analysis",
            "batch_response": response,
            "error_message": None,
            "batch_review_mode": batch_review_mode,
            "label_type": resolved_label_type.value,
            "product_profile": resolved_product_profile.value,
            "batch_review_mode_options": _batch_review_mode_options(settings),
            "label_type_options": _label_type_options(settings),
            "product_profile_options": _product_profile_options(settings),
            "batch_elapsed_ms": elapsed_ms,
            "batch_mode_used": batch_review_mode,
            "processed_count": len(response.results),
            "batch_display_rows": display_rows,
            "batch_display_summary": display_summary,
        },
    )


@router.get("/ui/batch/{batch_id}/record/{record_id}")
def batch_record_detail(request: Request, batch_id: str, record_id: str):
    settings = get_settings()
    if not settings.enable_batch_ui:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    summary_path = Path(settings.storage_dir) / "outputs" / "batch" / batch_id / "summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch record not found")
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch record not found")
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch record not found")
    row = next((item for item in results if isinstance(item, dict) and str(item.get("record_id")) == record_id), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch record not found")
    return templates.TemplateResponse(
        request=request,
        name="batch_record_detail.html",
        context={
            "title": f"Batch Record {record_id}",
            "batch_id": batch_id,
            "record_id": record_id,
            "row": row,
            "overall_status_display": _label_only_ui_status(str(row.get("overall_status", "review"))),
        },
    )


@router.post("/api/v1/batch/analyze", response_model=BatchResponse)
async def analyze_batch_api(
    batch_file: UploadFile = File(...),
    images_archive: UploadFile | None = File(default=None),
    label_type: str = Form(default=LabelType.UNKNOWN.value),
    product_profile: str = Form(default=ProductProfile.UNKNOWN.value),
    ocr_service: "OCRService" = Depends(get_ocr_service),
    batch_service: BatchService = Depends(get_batch_service),
) -> BatchResponse:
    settings = get_settings()
    try:
        return await _run_batch(
            batch_file,
            images_archive,
            ocr_service,
            batch_service,
            _coerce_label_type_allowed(label_type, settings),
            _coerce_product_profile_allowed(product_profile, settings),
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
    product_profile: ProductProfile,
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
        product_profile=product_profile,
    )


async def _run_batch_ui(
    batch_review_mode: str,
    batch_file: UploadFile | None,
    images_archive: UploadFile | None,
    ocr_service: "OCRService",
    batch_service: BatchService,
    label_type: LabelType,
    product_profile: ProductProfile,
) -> BatchResponse:
    if batch_review_mode == BATCH_MODE_COMPARE:
        if batch_file is None:
            raise ValueError("Batch file is required in Compare to Application Data mode.")
        return await _run_batch(batch_file, images_archive, ocr_service, batch_service, label_type, product_profile)

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
        product_profile=product_profile,
    )


def _batch_review_mode_options(settings: object) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for mode in _allowed_batch_modes(settings):
        if mode == BATCH_MODE_LABEL_ONLY:
            options.append((mode, "Batch Label-Only Review"))
        elif mode == BATCH_MODE_COMPARE:
            options.append((mode, "Batch Compare to Application Data"))
    return options


def _label_type_options(settings: object) -> list[tuple[str, str]]:
    values = _allowed_label_types(settings)
    return [(value.value, LABEL_TYPE_LABELS[value]) for value in values]


def _product_profile_options(settings: object) -> list[tuple[str, str]]:
    values = _allowed_product_profiles(settings)
    return [(value.value, PRODUCT_PROFILE_LABELS[value]) for value in values]


def _default_batch_mode(settings: object) -> str:
    allowed = _allowed_batch_modes(settings)
    if BATCH_MODE_LABEL_ONLY in allowed:
        return BATCH_MODE_LABEL_ONLY
    return allowed[0]


def _default_label_type(settings: object) -> LabelType:
    allowed = _allowed_label_types(settings)
    if LabelType.UNKNOWN in allowed:
        return LabelType.UNKNOWN
    return allowed[0]


def _default_product_profile(settings: object) -> ProductProfile:
    allowed = _allowed_product_profiles(settings)
    if ProductProfile.UNKNOWN in allowed:
        return ProductProfile.UNKNOWN
    return allowed[0]


def _coerce_batch_mode(value: str, settings: object) -> str:
    allowed = _allowed_batch_modes(settings)
    if value in allowed:
        return value
    return _default_batch_mode(settings)


def _coerce_label_type_allowed(value: str, settings: object) -> LabelType:
    candidate = coerce_label_type(value)
    allowed = _allowed_label_types(settings)
    if candidate in allowed:
        return candidate
    return _default_label_type(settings)


def _coerce_product_profile_allowed(value: str, settings: object) -> ProductProfile:
    candidate = coerce_product_profile(value)
    allowed = _allowed_product_profiles(settings)
    if candidate in allowed:
        return candidate
    return _default_product_profile(settings)


def _allowed_batch_modes(settings: object) -> list[str]:
    allowed_review_modes = _parse_allowed_csv(
        getattr(settings, "allowed_review_modes", None),
        valid_order=["label_only", "compare_application"],
    )
    output: list[str] = []
    if "label_only" in allowed_review_modes:
        output.append(BATCH_MODE_LABEL_ONLY)
    if "compare_application" in allowed_review_modes:
        output.append(BATCH_MODE_COMPARE)
    return output or [BATCH_MODE_LABEL_ONLY]


def _allowed_label_types(settings: object) -> list[LabelType]:
    raw_values = _parse_allowed_csv(
        getattr(settings, "allowed_label_types", None),
        valid_order=[value.value for value in LABEL_TYPE_LABELS.keys()],
    )
    values = [coerce_label_type(raw) for raw in raw_values]
    return values or [LabelType.UNKNOWN, LabelType.BRAND_LABEL, LabelType.OTHER_LABEL]


def _allowed_product_profiles(settings: object) -> list[ProductProfile]:
    raw_values = _parse_allowed_csv(
        getattr(settings, "allowed_product_profiles", None),
        valid_order=[value.value for value in PRODUCT_PROFILE_LABELS.keys()],
    )
    values = [coerce_product_profile(raw) for raw in raw_values]
    return values or [ProductProfile.UNKNOWN, ProductProfile.DISTILLED_SPIRITS, ProductProfile.MALT_BEVERAGE, ProductProfile.WINE]


def _parse_allowed_csv(raw_value: object, valid_order: list[str]) -> list[str]:
    if not isinstance(raw_value, str):
        return valid_order
    seen: set[str] = set()
    output: list[str] = []
    for part in raw_value.split(","):
        normalized = part.strip().lower()
        if normalized in valid_order and normalized not in seen:
            output.append(normalized)
            seen.add(normalized)
    return output or valid_order


def _build_display_rows(response: BatchResponse, batch_mode: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in response.results:
        internal_status = row.overall_status.value
        if batch_mode == BATCH_MODE_LABEL_ONLY:
            display_status = _label_only_ui_status(internal_status)
        else:
            display_status = internal_status
        output.append(
            {
                "record_id": row.record_id,
                "request_id": row.request_id,
                "image_filename": row.image_filename,
                "main_reason": row.main_reason,
                "timing_ms": row.timing_ms,
                "internal_status": internal_status,
                "display_status": display_status,
                "detail_url": f"/ui/batch/{response.batch_id}/record/{row.record_id}",
            }
        )
    return output


def _build_display_summary(
    response: BatchResponse,
    batch_mode: str,
    display_rows: list[dict[str, object]],
) -> dict[str, int]:
    if batch_mode != BATCH_MODE_LABEL_ONLY:
        return {
            "match": response.summary.match,
            "normalized_match": response.summary.normalized_match,
            "review": response.summary.review,
            "mismatch": response.summary.mismatch,
        }
    counts = {"pass": 0, "review": 0, "fail": 0}
    for row in display_rows:
        status = str(row.get("display_status", "review"))
        if status in counts:
            counts[status] += 1
    return counts


def _label_only_ui_status(internal_status: str) -> str:
    return LABEL_ONLY_UI_STATUS_MAP.get(internal_status, "review")
