from app.domain.enums import LabelType, OverallStatus
from app.domain.models import ApplicationData, ParsedAlcoholContent, ParsedFields, ParsedNetContents, ParsedTextValue, ParsedWarning
from app.services.matching_service import build_field_results


def _base_application() -> ApplicationData:
    return ApplicationData(
        brand_name="Summit Creek",
        class_type="Whiskey",
        alcohol_content="45% Alc./Vol.",
        net_contents="750 mL",
        bottler_producer="Summit Creek Distilling Co.",
        country_of_origin="United States",
        government_warning="GOVERNMENT WARNING: sample",
    )


def _parsed_with_brand_focus() -> ParsedFields:
    return ParsedFields(
        brand_name=ParsedTextValue(value="Summit Creek"),
        class_type=ParsedTextValue(value="Whiskey"),
        alcohol_content=ParsedAlcoholContent(raw="45% Alc./Vol.", abv_percent=45.0, proof=90.0),
        net_contents=ParsedNetContents(raw=None, milliliters=None),
        bottler_producer=ParsedTextValue(value=None),
        country_of_origin=ParsedTextValue(value=None),
        government_warning=ParsedWarning(value=None, detected=False, has_uppercase_prefix=False, confidence=None),
    )


def test_unknown_label_type_keeps_full_scan_overall_review():
    field_results, overall_status, review_reasons = build_field_results(
        _base_application(),
        _parsed_with_brand_focus(),
        label_type=LabelType.UNKNOWN,
    )

    assert overall_status == OverallStatus.REVIEW
    assert field_results["government_warning"].status.value == "review"
    assert any("Government warning" in reason for reason in review_reasons)


def test_brand_label_ignores_non_priority_missing_fields_for_overall():
    _, overall_status, review_reasons = build_field_results(
        _base_application(),
        _parsed_with_brand_focus(),
        label_type=LabelType.BRAND_LABEL,
    )

    assert overall_status in {OverallStatus.MATCH, OverallStatus.NORMALIZED_MATCH}
    assert review_reasons == []


def test_other_label_ignores_brand_missing_when_other_fields_match():
    parsed = ParsedFields(
        brand_name=ParsedTextValue(value=None),
        class_type=ParsedTextValue(value=None),
        alcohol_content=ParsedAlcoholContent(raw=None, abv_percent=None, proof=None),
        net_contents=ParsedNetContents(raw="750ML", milliliters=750),
        bottler_producer=ParsedTextValue(value="Summit Creek Distilling Co."),
        country_of_origin=ParsedTextValue(value="United States"),
        government_warning=ParsedWarning(
            value="GOVERNMENT WARNING: sample",
            detected=True,
            has_uppercase_prefix=True,
            confidence=0.99,
        ),
    )
    _, overall_status, review_reasons = build_field_results(
        _base_application(),
        parsed,
        label_type=LabelType.OTHER_LABEL,
    )

    assert overall_status in {OverallStatus.MATCH, OverallStatus.NORMALIZED_MATCH}
    assert review_reasons == []


def test_other_label_priority_field_mismatch_drives_overall_mismatch():
    parsed = ParsedFields(
        brand_name=ParsedTextValue(value="Different Name"),
        class_type=ParsedTextValue(value="Vodka"),
        alcohol_content=ParsedAlcoholContent(raw="45% Alc./Vol.", abv_percent=45.0, proof=90.0),
        net_contents=ParsedNetContents(raw="375 mL", milliliters=375),
        bottler_producer=ParsedTextValue(value="Summit Creek Distilling Co."),
        country_of_origin=ParsedTextValue(value="United States"),
        government_warning=ParsedWarning(
            value="GOVERNMENT WARNING: sample",
            detected=True,
            has_uppercase_prefix=True,
            confidence=0.99,
        ),
    )
    _, overall_status, _ = build_field_results(
        _base_application(),
        parsed,
        label_type=LabelType.OTHER_LABEL,
    )

    assert overall_status == OverallStatus.MISMATCH
