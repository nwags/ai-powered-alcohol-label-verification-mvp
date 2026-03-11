from app.domain.enums import LabelType
from app.domain.models import ApplicationData, ParsedAlcoholContent, ParsedFields, ParsedNetContents, ParsedTextValue, ParsedWarning
from app.services.matching_service import build_field_results


def test_label_only_mode_uses_ocr_evidence_without_missing_submitted_penalty():
    application = ApplicationData()
    parsed = ParsedFields(
        brand_name=ParsedTextValue(value="STONE'S THROW"),
        class_type=ParsedTextValue(value="Whiskey"),
        alcohol_content=ParsedAlcoholContent(raw="90 Proof", abv_percent=45.0, proof=90.0),
        net_contents=ParsedNetContents(raw="750ML", milliliters=750),
        bottler_producer=ParsedTextValue(value="Bottled by Example Spirits Co."),
        country_of_origin=ParsedTextValue(value="United States"),
        government_warning=ParsedWarning(
            value="GOVERNMENT WARNING: according to the surgeon general ...",
            detected=True,
            has_uppercase_prefix=True,
            confidence=0.78,
        ),
    )

    field_results, overall_status, review_reasons = build_field_results(
        application,
        parsed,
        label_type=LabelType.UNKNOWN,
        evaluation_mode="label_only",
    )

    assert field_results["brand_name"].status.value in {"match", "normalized_match"}
    assert "missing submitted" not in (field_results["brand_name"].notes or "").lower()
    assert field_results["alcohol_content"].status.value in {"match", "normalized_match"}
    assert overall_status.value in {"match", "normalized_match", "review"}
    assert all("missing submitted" not in reason.lower() for reason in review_reasons)


def test_label_only_mode_prefers_review_for_missing_or_weak_evidence():
    application = ApplicationData()
    parsed = ParsedFields(
        brand_name=ParsedTextValue(value=None),
        class_type=ParsedTextValue(value=None),
        alcohol_content=ParsedAlcoholContent(raw=None, abv_percent=None, proof=None),
        net_contents=ParsedNetContents(raw=None, milliliters=None),
        bottler_producer=ParsedTextValue(value=None),
        country_of_origin=ParsedTextValue(value=None),
        government_warning=ParsedWarning(value="government warning: text", detected=True, has_uppercase_prefix=False, confidence=0.5),
    )

    field_results, overall_status, _ = build_field_results(
        application,
        parsed,
        label_type=LabelType.UNKNOWN,
        evaluation_mode="label_only",
    )

    assert field_results["brand_name"].status.value == "review"
    assert field_results["government_warning"].status.value == "review"
    assert overall_status.value == "review"
