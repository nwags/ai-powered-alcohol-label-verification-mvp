from app.domain.enums import FieldStatus, OverallStatus
from app.domain.models import ApplicationData, FieldResult, ParsedFields
from app.services.parser_service import normalize_text, parse_alcohol_content, parse_net_contents
from app.services.warning_service import compare_warning_statement


def build_field_results(
    application: ApplicationData, parsed: ParsedFields
) -> tuple[dict[str, FieldResult], OverallStatus, list[str]]:
    """Compare submitted application fields vs parsed OCR fields.

    Returns field-level statuses, aggregate status, and reviewer-facing reasons.
    """
    review_reasons: list[str] = []
    results: dict[str, FieldResult] = {}

    results["brand_name"] = _compare_text_field(
        application.brand_name,
        parsed.brand_name.value,
        field_label="brand_name",
        allow_partial_review=True,
    )
    if results["brand_name"].status == FieldStatus.REVIEW:
        review_reasons.append("Brand name could not be confidently matched from OCR text.")

    results["class_type"] = _compare_text_field(
        application.class_type,
        parsed.class_type.value,
        field_label="class_type",
        allow_partial_review=False,
    )
    if results["class_type"].status == FieldStatus.REVIEW:
        review_reasons.append("Class/type is missing or uncertain in OCR result.")

    results["alcohol_content"] = _compare_alcohol_content(application.alcohol_content, parsed.alcohol_content.abv_percent)
    if results["alcohol_content"].status == FieldStatus.REVIEW:
        review_reasons.append("Alcohol content could not be confidently parsed.")

    results["net_contents"] = _compare_net_contents(application.net_contents, parsed.net_contents.milliliters, parsed.net_contents.raw)
    if results["net_contents"].status == FieldStatus.REVIEW:
        review_reasons.append("Net contents could not be confidently parsed.")

    results["bottler_producer"] = _compare_text_field(
        application.bottler_producer,
        parsed.bottler_producer.value,
        field_label="bottler_producer",
        allow_partial_review=True,
    )
    if results["bottler_producer"].status == FieldStatus.REVIEW:
        review_reasons.append("Bottler/producer text is incomplete or only partially matched.")

    results["country_of_origin"] = _compare_text_field(
        application.country_of_origin,
        parsed.country_of_origin.value,
        field_label="country_of_origin",
        allow_partial_review=True,
    )
    if results["country_of_origin"].status == FieldStatus.REVIEW:
        review_reasons.append("Country of origin was not confidently identified.")

    warning_result, warning_reasons = compare_warning_statement(
        submitted_value=application.government_warning,
        detected_value=parsed.government_warning.value,
        detected=parsed.government_warning.detected,
        has_uppercase_prefix=parsed.government_warning.has_uppercase_prefix,
        detection_confidence=parsed.government_warning.confidence,
    )
    results["government_warning"] = warning_result
    review_reasons.extend(warning_reasons)

    overall = _compute_overall_status(results)
    return results, overall, _dedupe(review_reasons)


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


def _compare_alcohol_content(submitted_value: str | None, detected_abv_percent: float | None) -> FieldResult:
    if not submitted_value or detected_abv_percent is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=None if detected_abv_percent is None else f"{detected_abv_percent:.2f}% ABV",
            notes="alcohol_content: missing parsed ABV from submitted or OCR data.",
        )

    submitted = parse_alcohol_content(submitted_value)
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


def _compare_net_contents(submitted_value: str | None, detected_ml: int | None, detected_raw: str | None) -> FieldResult:
    if not submitted_value or detected_ml is None:
        return FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=submitted_value,
            detected_value=detected_raw,
            notes="net_contents: missing parsed milliliters from submitted or OCR data.",
        )

    submitted = parse_net_contents(submitted_value)
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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
