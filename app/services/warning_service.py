from __future__ import annotations

from app.domain.enums import FieldStatus
from app.domain.models import FieldResult
from app.services.parser_service import normalize_text

CANONICAL_WARNING_TEXT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages "
    "during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs "
    "your ability to drive a car or operate machinery, and may cause health problems."
)

EVAL_MODE_COMPARE = "compare"
EVAL_MODE_LABEL_ONLY = "label_only"


def compare_warning_statement(
    submitted_value: str | None,
    detected_value: str | None,
    detected: bool,
    has_uppercase_prefix: bool,
    detection_confidence: float | None,
    evaluation_mode: str = EVAL_MODE_COMPARE,
) -> tuple[FieldResult, list[str]]:
    if evaluation_mode == EVAL_MODE_LABEL_ONLY:
        return _evaluate_warning_label_only(
            detected_value=detected_value,
            detected=detected,
            has_uppercase_prefix=has_uppercase_prefix,
            detection_confidence=detection_confidence,
        )
    return _evaluate_warning_compare_mode(
        submitted_value=submitted_value,
        detected_value=detected_value,
        detected=detected,
        has_uppercase_prefix=has_uppercase_prefix,
        detection_confidence=detection_confidence,
    )


def _evaluate_warning_compare_mode(
    submitted_value: str | None,
    detected_value: str | None,
    detected: bool,
    has_uppercase_prefix: bool,
    detection_confidence: float | None,
) -> tuple[FieldResult, list[str]]:
    review_reasons: list[str] = []

    if not detected or not detected_value:
        review_reasons.append("Government warning statement not detected in OCR output.")
        return (
            FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=submitted_value,
                detected_value=detected_value,
                notes="Warning statement not confidently detected.",
            ),
            review_reasons,
        )

    if not has_uppercase_prefix:
        review_reasons.append("Warning detected without exact uppercase prefix 'GOVERNMENT WARNING:'.")
        return (
            FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=submitted_value,
                detected_value=detected_value,
                notes="Warning-like text found but required uppercase prefix is uncertain.",
            ),
            review_reasons,
        )

    if detection_confidence is not None and detection_confidence < 0.70:
        review_reasons.append("Warning detection confidence is below review threshold.")
        return (
            FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=submitted_value,
                detected_value=detected_value,
                notes="Warning text confidence is low; manual review required.",
            ),
            review_reasons,
        )

    expected_source = submitted_value or CANONICAL_WARNING_TEXT
    normalized_detected = normalize_text(detected_value)
    normalized_expected = normalize_text(expected_source)

    if normalized_detected == normalized_expected:
        return (
            FieldResult(
                status=FieldStatus.MATCH,
                submitted_value=submitted_value,
                detected_value=detected_value,
                notes="Warning statement matches expected text.",
            ),
            review_reasons,
        )

    overlap = _token_overlap(normalized_expected, normalized_detected)
    if overlap >= 0.85:
        return (
            FieldResult(
                status=FieldStatus.NORMALIZED_MATCH,
                submitted_value=submitted_value,
                detected_value=detected_value,
                notes="Warning statement matches after normalization with minor OCR differences.",
            ),
            review_reasons,
        )

    if overlap >= 0.55:
        review_reasons.append("Warning text is partially matched but not reliable enough.")
        return (
            FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=submitted_value,
                detected_value=detected_value,
                notes="Warning statement partially matched; manual review recommended.",
            ),
            review_reasons,
        )

    return (
        FieldResult(
            status=FieldStatus.MISMATCH,
            submitted_value=submitted_value,
            detected_value=detected_value,
            notes="Warning statement content does not match expected text.",
        ),
        review_reasons,
    )


def _evaluate_warning_label_only(
    detected_value: str | None,
    detected: bool,
    has_uppercase_prefix: bool,
    detection_confidence: float | None,
) -> tuple[FieldResult, list[str]]:
    review_reasons: list[str] = []

    if not detected or not detected_value:
        review_reasons.append("Government warning statement not detected in OCR output.")
        return (
            FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=None,
                detected_value=detected_value,
                notes="Warning statement evidence not confidently detected.",
            ),
            review_reasons,
        )

    normalized_detected = normalize_text(detected_value)
    normalized_expected = normalize_text(CANONICAL_WARNING_TEXT)
    overlap = _token_overlap(normalized_expected, normalized_detected)
    confidence = detection_confidence if detection_confidence is not None else 0.0

    if confidence < 0.55:
        review_reasons.append("Warning detection confidence is below review threshold.")
        return (
            FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value=None,
                detected_value=detected_value,
                notes="Warning text confidence is low; manual review required.",
            ),
            review_reasons,
        )

    if has_uppercase_prefix and overlap >= 0.9 and confidence >= 0.80:
        return (
            FieldResult(
                status=FieldStatus.MATCH,
                submitted_value=None,
                detected_value=detected_value,
                notes="Warning statement strongly detected in OCR output.",
            ),
            review_reasons,
        )

    if overlap >= 0.65 and confidence >= 0.65:
        return (
            FieldResult(
                status=FieldStatus.NORMALIZED_MATCH,
                submitted_value=None,
                detected_value=detected_value,
                notes="Warning statement detected with normalization-friendly OCR differences.",
            ),
            review_reasons,
        )

    if has_uppercase_prefix and overlap < 0.12 and confidence >= 0.90:
        return (
            FieldResult(
                status=FieldStatus.MISMATCH,
                submitted_value=None,
                detected_value=detected_value,
                notes="Warning-like text appears contradictory to the required statement.",
            ),
            review_reasons,
        )

    review_reasons.append("Warning text is partial or noisy; manual review required.")
    return (
        FieldResult(
            status=FieldStatus.REVIEW,
            submitted_value=None,
            detected_value=detected_value,
            notes="Warning statement partially detected; manual review recommended.",
        ),
        review_reasons,
    )


def _token_overlap(expected: str, detected: str) -> float:
    expected_tokens = [token for token in expected.split(" ") if token]
    detected_tokens = [token for token in detected.split(" ") if token]
    if not expected_tokens or not detected_tokens:
        return 0.0
    expected_set = set(expected_tokens)
    detected_set = set(detected_tokens)
    return len(expected_set.intersection(detected_set)) / float(len(expected_set))
