from app.domain.enums import FieldStatus
from app.services.warning_service import CANONICAL_WARNING_TEXT, compare_warning_statement


def test_warning_statement_exact_match():
    result, reasons = compare_warning_statement(
        submitted_value=CANONICAL_WARNING_TEXT,
        detected_value=CANONICAL_WARNING_TEXT,
        detected=True,
        has_uppercase_prefix=True,
        detection_confidence=0.95,
    )
    assert result.status == FieldStatus.MATCH
    assert reasons == []


def test_warning_statement_prefers_review_when_prefix_uncertain():
    result, reasons = compare_warning_statement(
        submitted_value=CANONICAL_WARNING_TEXT,
        detected_value="Government warning: partial text",
        detected=True,
        has_uppercase_prefix=False,
        detection_confidence=0.9,
    )
    assert result.status == FieldStatus.REVIEW
    assert reasons


def test_warning_statement_label_only_prefers_review_for_partial_text():
    result, reasons = compare_warning_statement(
        submitted_value=None,
        detected_value="GOVERNMENT WARNING: pregnant women should not drink",
        detected=True,
        has_uppercase_prefix=True,
        detection_confidence=0.72,
        evaluation_mode="label_only",
    )
    assert result.status == FieldStatus.REVIEW
    assert reasons


def test_warning_statement_label_only_can_return_non_review_when_strong():
    result, reasons = compare_warning_statement(
        submitted_value=None,
        detected_value=CANONICAL_WARNING_TEXT,
        detected=True,
        has_uppercase_prefix=True,
        detection_confidence=0.95,
        evaluation_mode="label_only",
    )
    assert result.status in {FieldStatus.MATCH, FieldStatus.NORMALIZED_MATCH}
    assert reasons == []
