from __future__ import annotations

from app.domain.enums import FieldStatus, LabelType, OverallStatus, ProductProfile
from app.domain.models import ApplicationData, FieldResult, ParsedFields
from app.services.parser_service import normalize_text, parse_alcohol_content, parse_net_contents
from app.services.warning_service import compare_warning_statement

EVAL_MODE_COMPARE = "compare"
EVAL_MODE_LABEL_ONLY = "label_only"


def build_field_results(
    application: ApplicationData,
    parsed: ParsedFields,
    label_type: LabelType = LabelType.UNKNOWN,
    evaluation_mode: str = EVAL_MODE_COMPARE,
    product_profile: ProductProfile = ProductProfile.UNKNOWN,
    rule_ids_by_field: dict[str, list[str]] | None = None,
) -> tuple[dict[str, FieldResult], OverallStatus, list[str]]:
    """Build field-level outcomes in compare or label-only evaluation mode."""
    resolved_mode = _coerce_evaluation_mode(evaluation_mode)
    review_reasons: list[str] = []
    results: dict[str, FieldResult] = {}

    if resolved_mode == EVAL_MODE_LABEL_ONLY:
        results["brand_name"] = _evaluate_text_field_label_only(parsed.brand_name.value, "brand_name")
        _add_rule(rule_ids_by_field, "brand_name", "PARSE-BRAND-BASE")
        results["class_type"] = _evaluate_text_field_label_only(parsed.class_type.value, "class_type")
        _add_rule(rule_ids_by_field, "class_type", "PARSE-CLASS-PROFILE")
        results["alcohol_content"] = _evaluate_alcohol_content_label_only(
            parsed.alcohol_content.abv_percent,
            parsed.alcohol_content.raw,
            product_profile=product_profile,
        )
        _add_rule(rule_ids_by_field, "alcohol_content", "PARSE-ALCOHOL-NORMALIZE")
        results["net_contents"] = _evaluate_net_contents_label_only(
            parsed.net_contents.milliliters,
            parsed.net_contents.raw,
            product_profile=product_profile,
        )
        _add_rule(rule_ids_by_field, "net_contents", "PARSE-NET-PROFILE")
        results["bottler_producer"] = _evaluate_text_field_label_only(parsed.bottler_producer.value, "bottler_producer")
        _add_rule(rule_ids_by_field, "bottler_producer", "PARSE-BOTTLER-ROLE")
        results["country_of_origin"] = _evaluate_text_field_label_only(parsed.country_of_origin.value, "country_of_origin")
        _add_rule(rule_ids_by_field, "country_of_origin", "PARSE-COUNTRY-IMPORT")
    else:
        results["brand_name"] = _compare_text_field(
            application.brand_name,
            parsed.brand_name.value,
            field_label="brand_name",
            allow_partial_review=True,
        )
        _add_rule(rule_ids_by_field, "brand_name", "PARSE-BRAND-BASE")
        results["class_type"] = _compare_text_field(
            application.class_type,
            parsed.class_type.value,
            field_label="class_type",
            allow_partial_review=False,
        )
        _add_rule(rule_ids_by_field, "class_type", "PARSE-CLASS-PROFILE")
        results["alcohol_content"] = _compare_alcohol_content(
            application.alcohol_content,
            parsed.alcohol_content.abv_percent,
            product_profile=product_profile,
        )
        _add_rule(rule_ids_by_field, "alcohol_content", "PARSE-ALCOHOL-NORMALIZE")
        results["net_contents"] = _compare_net_contents(
            application.net_contents,
            parsed.net_contents.milliliters,
            parsed.net_contents.raw,
            product_profile=product_profile,
        )
        _add_rule(rule_ids_by_field, "net_contents", "PARSE-NET-PROFILE")
        results["bottler_producer"] = _compare_text_field(
            application.bottler_producer,
            parsed.bottler_producer.value,
            field_label="bottler_producer",
            allow_partial_review=True,
        )
        _add_rule(rule_ids_by_field, "bottler_producer", "PARSE-BOTTLER-ROLE")
        results["country_of_origin"] = _compare_text_field(
            application.country_of_origin,
            parsed.country_of_origin.value,
            field_label="country_of_origin",
            allow_partial_review=True,
        )
        _add_rule(rule_ids_by_field, "country_of_origin", "PARSE-COUNTRY-IMPORT")

    warning_result, warning_reasons = compare_warning_statement(
        submitted_value=application.government_warning,
        detected_value=parsed.government_warning.value,
        detected=parsed.government_warning.detected,
        has_uppercase_prefix=parsed.government_warning.has_uppercase_prefix,
        detection_confidence=parsed.government_warning.confidence,
        evaluation_mode=resolved_mode,
    )
    results["government_warning"] = warning_result
    _add_rule(rule_ids_by_field, "government_warning", "WARN-SHARED")
    review_reasons.extend(warning_reasons)

    review_reasons.extend(_review_reasons_for_results(results, resolved_mode))
    priority_fields = priority_fields_for_label_type(label_type)
    prioritized_results = {field: results[field] for field in priority_fields}
    prioritized_review_reasons = _filter_review_reasons(review_reasons, priority_fields)
    overall = _compute_overall_status(prioritized_results)
    return results, overall, _dedupe(prioritized_review_reasons)


def priority_fields_for_label_type(label_type: LabelType) -> tuple[str, ...]:
    if label_type == LabelType.BRAND_LABEL:
        return ("brand_name", "class_type", "alcohol_content")
    if label_type == LabelType.OTHER_LABEL:
        return ("government_warning", "bottler_producer", "net_contents", "country_of_origin")
    return (
        "brand_name",
        "class_type",
        "alcohol_content",
        "net_contents",
        "bottler_producer",
        "country_of_origin",
        "government_warning",
    )


def coerce_label_type(label_type: str | LabelType | None) -> LabelType:
    if isinstance(label_type, LabelType):
        return label_type
    if isinstance(label_type, str):
        try:
            return LabelType(label_type)
        except ValueError:
            return LabelType.UNKNOWN
    return LabelType.UNKNOWN


def _coerce_evaluation_mode(evaluation_mode: str | None) -> str:
    if evaluation_mode == EVAL_MODE_LABEL_ONLY:
        return EVAL_MODE_LABEL_ONLY
    return EVAL_MODE_COMPARE


def _compute_overall_status(field_results: dict[str, FieldResult]) -> OverallStatus:
    statuses = [result.status for result in field_results.values()]
    if FieldStatus.REVIEW in statuses:
        return OverallStatus.REVIEW
    if FieldStatus.MISMATCH in statuses:
        return OverallStatus.MISMATCH
    if FieldStatus.NORMALIZED_MATCH in statuses:
        return OverallStatus.NORMALIZED_MATCH
    return OverallStatus.MATCH


def _compare_text_field(
    submitted_value: str | None,
    detected_value: str | None,
    field_label: str,
    allow_partial_review: bool,
) -> FieldResult:
    if not submitted_value and not detected_value:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=detected_value,
            notes=f"{field_label}: both submitted and detected values are missing.",
        )
    if not submitted_value or not detected_value:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=detected_value,
            notes=f"{field_label}: missing submitted or OCR value.",
        )

    if submitted_value == detected_value:
        return FieldResult(
            status=FieldStatus.MATCH,
            submitted_value=submitted_value,
            detected_value=detected_value,
            notes=f"{field_label}: exact text match.",
        )

    normalized_submitted = normalize_text(submitted_value)
    normalized_detected = normalize_text(detected_value)
    if normalized_submitted == normalized_detected:
        return FieldResult(
            status=FieldStatus.NORMALIZED_MATCH,
            submitted_value=submitted_value,
            detected_value=detected_value,
            notes=f"{field_label}: matched after normalization (case/punctuation/whitespace).",
        )

    if allow_partial_review and (
        normalized_submitted in normalized_detected or normalized_detected in normalized_submitted
    ):
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=detected_value,
            notes=f"{field_label}: partial textual overlap, manual review required.",
        )

    return FieldResult(
        status=FieldStatus.MISMATCH,
        submitted_value=submitted_value,
        detected_value=detected_value,
        notes=f"{field_label}: submitted and detected text differ.",
    )


def _compare_alcohol_content(
    submitted_value: str | None,
    detected_abv_percent: float | None,
    product_profile: ProductProfile,
) -> FieldResult:
    if not submitted_value or detected_abv_percent is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=None if detected_abv_percent is None else f"{detected_abv_percent:.2f}% ABV",
            notes="alcohol_content: missing parsed ABV from submitted or OCR data.",
        )

    submitted = parse_alcohol_content(submitted_value, product_profile=product_profile)
    submitted_abv = submitted.abv_percent
    if submitted_abv is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=f"{detected_abv_percent:.2f}% ABV",
            notes="alcohol_content: submitted value could not be parsed to ABV.",
        )

    if abs(submitted_abv - detected_abv_percent) <= 0.1:
        exact = submitted.raw and submitted.raw.strip().casefold() == f"{detected_abv_percent:g}% abv"
        return FieldResult(
            status=FieldStatus.MATCH if exact else FieldStatus.NORMALIZED_MATCH,
            submitted_value=submitted_value,
            detected_value=f"{detected_abv_percent:.2f}% ABV",
            notes="alcohol_content: numeric ABV values are equivalent.",
        )

    return FieldResult(
        status=FieldStatus.MISMATCH,
        submitted_value=submitted_value,
        detected_value=f"{detected_abv_percent:.2f}% ABV",
        notes="alcohol_content: numeric ABV values differ.",
    )


def _compare_net_contents(
    submitted_value: str | None,
    detected_ml: int | None,
    detected_raw: str | None,
    product_profile: ProductProfile,
) -> FieldResult:
    if not submitted_value or detected_ml is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=detected_raw,
            notes="net_contents: missing parsed milliliters from submitted or OCR data.",
        )

    submitted = parse_net_contents(submitted_value, product_profile=product_profile)
    if submitted.milliliters is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=detected_raw,
            notes="net_contents: submitted value could not be parsed.",
        )

    if submitted.milliliters == detected_ml:
        exact = submitted.raw and detected_raw and submitted.raw.strip().casefold() == detected_raw.strip().casefold()
        return FieldResult(
            status=FieldStatus.MATCH if exact else FieldStatus.NORMALIZED_MATCH,
            submitted_value=submitted_value,
            detected_value=detected_raw,
            notes="net_contents: normalized volume values are equivalent.",
        )

    return FieldResult(
        status=FieldStatus.MISMATCH,
        submitted_value=submitted_value,
        detected_value=detected_raw,
        notes="net_contents: parsed volume values differ.",
    )


def _evaluate_text_field_label_only(detected_value: str | None, field_label: str) -> FieldResult:
    field_phrase = field_label.replace("_", " ")
    if not detected_value:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=None,
            detected_value=None,
            notes=f"{field_phrase}: OCR evidence not confidently detected.",
        )

    normalized = normalize_text(detected_value)
    if not normalized or len(normalized) < 3:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=None,
            detected_value=detected_value,
            notes=f"{field_phrase}: detected text is too weak for confidence.",
        )

    if normalized in {"na", "n a", "none", "unknown"}:
        return FieldResult(
            status=FieldStatus.MISMATCH,
            submitted_value=None,
            detected_value=detected_value,
            notes=f"{field_phrase}: detected content appears invalid.",
        )

    normalized_display = " ".join(detected_value.split())
    normalized_needed = normalized_display != detected_value or normalize_text(normalized_display) != normalize_text(detected_value)
    return FieldResult(
        status=FieldStatus.NORMALIZED_MATCH if normalized_needed else FieldStatus.MATCH,
        submitted_value=None,
        detected_value=detected_value,
        notes=(
            f"{field_phrase}: strong OCR evidence detected after normalization."
            if normalized_needed
            else f"{field_phrase}: strong OCR evidence detected."
        ),
    )


def _evaluate_alcohol_content_label_only(
    detected_abv_percent: float | None,
    detected_raw: str | None,
    product_profile: ProductProfile,
) -> FieldResult:
    if detected_abv_percent is None:
        if product_profile in {ProductProfile.MALT_BEVERAGE, ProductProfile.WINE}:
            return FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=None,
                detected_value=detected_raw,
                notes="alcohol content: not confidently parsed (allowed to be conditional for this profile).",
            )
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=None,
            detected_value=detected_raw,
            notes="alcohol_content: OCR did not provide a confident ABV/proof parse.",
        )
    if detected_abv_percent <= 0 or detected_abv_percent > 100:
        return FieldResult(
            status=FieldStatus.MISMATCH,
            submitted_value=None,
            detected_value=f"{detected_abv_percent:.2f}% ABV",
            notes="alcohol_content: parsed ABV is out of valid range.",
        )
    normalized_needed = bool(detected_raw and "proof" in normalize_text(detected_raw))
    return FieldResult(
        status=FieldStatus.NORMALIZED_MATCH if normalized_needed else FieldStatus.MATCH,
        submitted_value=None,
        detected_value=f"{detected_abv_percent:.2f}% ABV",
        notes=(
            "alcohol_content: parseable alcohol statement detected after proof-to-ABV normalization."
            if normalized_needed
            else "alcohol_content: parseable ABV detected."
        ),
    )


def _evaluate_net_contents_label_only(
    detected_ml: int | None,
    detected_raw: str | None,
    product_profile: ProductProfile,
) -> FieldResult:
    if detected_ml is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=None,
            detected_value=detected_raw,
            notes="net_contents: OCR did not provide a confident volume parse.",
        )
    if detected_ml <= 0 or detected_ml > 10000:
        return FieldResult(
            status=FieldStatus.MISMATCH,
            submitted_value=None,
            detected_value=detected_raw,
            notes="net_contents: parsed volume appears invalid.",
        )
    expected_canonical = f"{detected_ml} ml"
    normalized_needed = not detected_raw or normalize_text(detected_raw) != expected_canonical
    if product_profile == ProductProfile.MALT_BEVERAGE and detected_raw and "oz" in normalize_text(detected_raw):
        normalized_needed = True
    return FieldResult(
        status=FieldStatus.NORMALIZED_MATCH if normalized_needed else FieldStatus.MATCH,
        submitted_value=None,
        detected_value=detected_raw or expected_canonical,
        notes=(
            "net_contents: parseable volume detected after normalization."
            if normalized_needed
            else "net_contents: parseable volume detected."
        ),
    )


COMPARE_FIELD_REASON_MAP = {
    "brand_name": "Brand name could not be confidently matched from OCR text.",
    "class_type": "Class/type is missing or uncertain in OCR result.",
    "alcohol_content": "Alcohol content could not be confidently parsed.",
    "net_contents": "Net contents could not be confidently parsed.",
    "bottler_producer": "Bottler/producer text is incomplete or only partially matched.",
    "country_of_origin": "Country of origin was not confidently identified.",
}

LABEL_ONLY_FIELD_REASON_MAP = {
    "brand_name": "Brand name evidence is incomplete or uncertain in OCR output.",
    "class_type": "Class/type evidence is incomplete or uncertain in OCR output.",
    "alcohol_content": "Alcohol content evidence is incomplete or uncertain in OCR output.",
    "net_contents": "Net contents evidence is incomplete or uncertain in OCR output.",
    "bottler_producer": "Bottler/producer evidence is incomplete or uncertain in OCR output.",
    "country_of_origin": "Country of origin evidence is incomplete or uncertain in OCR output.",
}


def _review_reasons_for_results(field_results: dict[str, FieldResult], evaluation_mode: str) -> list[str]:
    mapping = LABEL_ONLY_FIELD_REASON_MAP if evaluation_mode == EVAL_MODE_LABEL_ONLY else COMPARE_FIELD_REASON_MAP
    reasons: list[str] = []
    for field_name, reason in mapping.items():
        result = field_results.get(field_name)
        if result is not None and result.status == FieldStatus.REVIEW:
            reasons.append(reason)
    return reasons


def _filter_review_reasons(review_reasons: list[str], priority_fields: tuple[str, ...]) -> list[str]:
    allowed = {
        reason
        for field_name, reason in {**COMPARE_FIELD_REASON_MAP, **LABEL_ONLY_FIELD_REASON_MAP}.items()
        if field_name in priority_fields
    }
    include_warning_reasons = "government_warning" in priority_fields
    warning_prefixes = ("Government warning", "Warning detected", "Warning detection", "Warning text")
    filtered: list[str] = []
    for reason in review_reasons:
        if reason in allowed:
            filtered.append(reason)
            continue
        if include_warning_reasons and reason.startswith(warning_prefixes):
            filtered.append(reason)
    return filtered


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _add_rule(rule_ids_by_field: dict[str, list[str]] | None, field_name: str, rule_id: str) -> None:
    if rule_ids_by_field is None:
        return
    rule_ids_by_field.setdefault(field_name, [])
    if rule_id not in rule_ids_by_field[field_name]:
        rule_ids_by_field[field_name].append(rule_id)
