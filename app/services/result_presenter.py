from __future__ import annotations

from typing import Any

from app.domain.enums import LabelType, OverallStatus, ProductProfile
from app.domain.models import AnalyzeResponse, FieldResult, OCRResult, ParsedFields
from app.services.inference_service import coerce_product_profile
from app.services.matching_service import coerce_label_type
from app.services.result_explanation_service import build_result_explanation, evidence_confidence_for_field
from app.services.rule_registry import short_rule_tags

REVIEW_MODE_LABEL_ONLY = "label_only"
REVIEW_MODE_COMPARE = "compare_application"


def build_result_view_from_analysis(
    *,
    analysis: AnalyzeResponse,
    review_mode: str,
    field_labels: dict[str, str],
    label_type_labels: dict[LabelType, str],
    product_profile_labels: dict[ProductProfile, str],
    label_type_hint: LabelType,
    product_profile_hint: ProductProfile,
    uploaded_filename: str,
    uploaded_image_url: str | None,
    annotated_image_url: str | None,
    page_heading: str,
    nav_label: str,
    nav_url: str,
    page_meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    inference_payload = _extract_inference(analysis)
    effective_label_type = coerce_label_type(inference_payload["label_type"].get("effective_label_type"))
    effective_product_profile = coerce_product_profile(inference_payload["product_profile"].get("effective_profile"))
    detected_label_type = coerce_label_type(inference_payload["label_type"].get("detected_label_type"))
    detected_profile = coerce_product_profile(inference_payload["product_profile"].get("detected_profile"))

    explanation = build_result_explanation(
        analysis=analysis,
        parsed=analysis.parsed,
        review_mode=review_mode,
        effective_label_type=effective_label_type,
        effective_product_profile=effective_product_profile,
        field_labels=field_labels,
    )

    field_rows = build_field_rows(
        analysis=analysis,
        label_type=effective_label_type,
        parsed=analysis.parsed,
        priority_fields=explanation.priority_fields,
        field_labels=field_labels,
    )

    return {
        "page_heading": page_heading,
        "page_meta": page_meta or {},
        "review_mode": review_mode,
        "badge": {
            "class": explanation.ui_overall_badge,
            "label": explanation.ui_overall_label,
        },
        "overall_recommendation": overall_recommendation(analysis.overall_status.value),
        "ui_overall_reason": explanation.ui_overall_reason,
        "overall_evidence_confidence": explanation.overall_evidence_confidence,
        "priority_summary": explanation.priority_summary,
        "non_priority_notice": explanation.non_priority_notice,
        "top_contributing_fields": explanation.top_contributing_fields,
        "top_rules": explanation.top_rules,
        "rule_trace_details": explanation.rule_trace_details,
        "field_rows": field_rows,
        "uploaded_filename": uploaded_filename,
        "uploaded_image_url": uploaded_image_url,
        "annotated_image_url": annotated_image_url,
        "ocr_full_text": analysis.ocr.full_text,
        "ocr_errors": analysis.errors,
        "review_reasons": analysis.review_reasons,
        "annotation_debug": analysis.artifacts.get("annotation_debug"),
        "annotation": analysis.artifacts.get("annotation"),
        "request_id": analysis.request_id,
        "timing_ms": analysis.timing_ms,
        "inference_payload": inference_payload,
        "label_type_display": label_type_labels[effective_label_type],
        "label_type_hint_display": label_type_labels[label_type_hint],
        "detected_label_type_display": label_type_labels[detected_label_type],
        "product_profile_display": product_profile_labels[effective_product_profile],
        "product_profile_hint_display": product_profile_labels[product_profile_hint],
        "detected_product_profile_display": product_profile_labels[detected_profile],
        "navigation": {
            "label": nav_label,
            "url": nav_url,
        },
    }


def build_batch_detail_result_view(
    *,
    batch_id: str,
    record_id: str,
    row: dict[str, Any],
    field_labels: dict[str, str],
    label_type_labels: dict[LabelType, str],
    product_profile_labels: dict[ProductProfile, str],
) -> dict[str, Any]:
    parsed = ParsedFields.model_validate(row.get("parsed", {}))
    field_results = _field_results_from_row(row)
    overall_status = _coerce_overall_status(row.get("overall_status"))
    review_mode = REVIEW_MODE_LABEL_ONLY if str(row.get("evaluation_mode", "label_only")) == "label_only" else REVIEW_MODE_COMPARE

    artifacts = {
        "rule_trace": row.get("rule_trace", {}),
        "annotation": row.get("annotation"),
        "annotation_debug": row.get("annotation_debug"),
        "inference": row.get("inference", {}),
    }

    analysis = AnalyzeResponse(
        request_id=str(row.get("request_id") or f"batch-{batch_id}-{record_id}"),
        overall_status=overall_status,
        timing_ms=int(row.get("timing_ms") or 0),
        ocr=OCRResult(full_text=str(row.get("ocr_full_text") or ""), lines=[]),
        parsed=parsed,
        field_results=field_results,
        review_reasons=[str(item) for item in row.get("review_reasons", []) if isinstance(item, str)],
        artifacts=artifacts,
        errors=[str(item) for item in row.get("ocr_errors", []) if isinstance(item, str)],
    )

    label_type_hint = coerce_label_type(_deep_get(artifacts, ["inference", "label_type", "selected_hint"]))
    product_profile_hint = coerce_product_profile(_deep_get(artifacts, ["inference", "product_profile", "selected_hint"]))

    return build_result_view_from_analysis(
        analysis=analysis,
        review_mode=review_mode,
        field_labels=field_labels,
        label_type_labels=label_type_labels,
        product_profile_labels=product_profile_labels,
        label_type_hint=label_type_hint,
        product_profile_hint=product_profile_hint,
        uploaded_filename=str(row.get("image_filename") or record_id),
        uploaded_image_url=str(row.get("image_url")) if row.get("image_url") else None,
        annotated_image_url=str(row.get("annotated_image_url")) if row.get("annotated_image_url") else None,
        page_heading="Batch Record Detail",
        nav_label="Back to Batch Report",
        nav_url=f"/ui/batch/{batch_id}",
        page_meta={"batch_id": batch_id, "record_id": record_id},
    )


def build_batch_report_rows(results: list[Any], batch_mode: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in results:
        internal_status = row.overall_status.value
        display_status = _display_status(internal_status=internal_status, batch_mode=batch_mode)
        output.append(
            {
                "record_id": row.record_id,
                "request_id": row.request_id,
                "image_filename": row.image_filename,
                "image_url": row.image_url,
                "main_reason": row.main_reason,
                "timing_ms": row.timing_ms,
                "internal_status": internal_status,
                "display_status": display_status,
            }
        )
    return output


def build_field_rows(
    *,
    analysis: AnalyzeResponse,
    label_type: LabelType,
    parsed: ParsedFields,
    priority_fields: list[str],
    field_labels: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    confidence_bands = {"high", "medium", "low", "unknown"}
    priority_field_set = set(priority_fields)
    is_hint_mode = label_type != LabelType.UNKNOWN
    for field_name, label in field_labels.items():
        result = analysis.field_results.get(field_name)
        if result is None:
            continue
        notes = result.notes
        rule_ids = _rule_ids_for_field(analysis, field_name)
        if rule_ids:
            notes = f"{notes or ''}{short_rule_tags(rule_ids)}".strip()
        if is_hint_mode and field_name not in priority_field_set:
            info_note = "Informational for selected label type."
            notes = f"{notes} {info_note}".strip() if notes else info_note
        confidence = evidence_confidence_for_field(
            field_name=field_name,
            status=result.status,
            parsed=parsed,
        )
        normalized_confidence = confidence.lower().strip() if isinstance(confidence, str) else "unknown"
        if normalized_confidence not in confidence_bands:
            normalized_confidence = "unknown"
        rows.append(
            {
                "field_name": field_name,
                "label": label,
                "submitted_value": result.submitted_value,
                "detected_value": result.detected_value,
                "status": result.status.value,
                "is_priority": field_name in priority_field_set,
                "evidence_confidence": normalized_confidence,
                "notes": notes,
            }
        )
    return rows


def overall_recommendation(overall_status: str) -> str:
    if overall_status == "match":
        return "Looks consistent. Reviewer can do a quick confirmation."
    if overall_status == "normalized_match":
        return "Mostly consistent after normalization. Reviewer should spot-check."
    if overall_status == "mismatch":
        return "Potential mismatch found. Reviewer should inspect differences carefully."
    return "Manual review required due to uncertainty or missing evidence."


def _extract_inference(analysis: AnalyzeResponse) -> dict[str, dict[str, object]]:
    payload = analysis.artifacts.get("inference", {})
    if isinstance(payload, dict):
        product_profile = payload.get("product_profile", {})
        label_type = payload.get("label_type", {})
        if isinstance(product_profile, dict) and isinstance(label_type, dict):
            return {"product_profile": product_profile, "label_type": label_type}
    return {"product_profile": {}, "label_type": {}}


def _rule_ids_for_field(analysis: AnalyzeResponse, field_name: str) -> list[str]:
    payload = analysis.artifacts.get("rule_trace", {})
    if not isinstance(payload, dict):
        return []
    entries = payload.get(field_name)
    if not isinstance(entries, list):
        return []
    rule_ids: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            rule_id = entry.get("rule_id")
            if isinstance(rule_id, str):
                rule_ids.append(rule_id)
    return rule_ids


def _field_results_from_row(row: dict[str, Any]) -> dict[str, FieldResult]:
    raw = row.get("field_results")
    if isinstance(raw, dict):
        output: dict[str, FieldResult] = {}
        for field_name, value in raw.items():
            if isinstance(value, dict):
                try:
                    output[str(field_name)] = FieldResult.model_validate(value)
                except Exception:
                    continue
        if output:
            return output

    output: dict[str, FieldResult] = {}
    for item in row.get("field_rows", []):
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field_name") or "")
        if not field_name:
            continue
        try:
            output[field_name] = FieldResult.model_validate(
                {
                    "status": item.get("status", "review"),
                    "submitted_value": item.get("submitted_value"),
                    "detected_value": item.get("detected_value"),
                    "notes": item.get("notes"),
                }
            )
        except Exception:
            continue
    return output


def _coerce_overall_status(value: object) -> OverallStatus:
    text = str(value or "review").strip().lower()
    try:
        return OverallStatus(text)
    except ValueError:
        return OverallStatus.REVIEW


def _display_status(*, internal_status: str, batch_mode: str) -> str:
    if batch_mode == "batch_label_only":
        if internal_status in {"match", "normalized_match"}:
            return "pass"
        if internal_status == "mismatch":
            return "fail"
        return "review"
    return internal_status


def _deep_get(payload: dict[str, Any], keys: list[str]) -> object:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
