from app.domain.enums import FieldStatus, LabelType, OverallStatus, ProductProfile
from app.domain.models import AnalyzeResponse, FieldResult, OCRResult, ParsedFields
from app.services.result_explanation_service import build_result_explanation


def _analysis(overall: OverallStatus, statuses: dict[str, FieldStatus]) -> AnalyzeResponse:
    field_results = {
        name: FieldResult(status=status, submitted_value=None, detected_value="x", notes=f"{name} note")
        for name, status in statuses.items()
    }
    return AnalyzeResponse(
        request_id="r1",
        overall_status=overall,
        timing_ms=100,
        ocr=OCRResult(full_text="sample", lines=[]),
        parsed=ParsedFields(),
        field_results=field_results,
        review_reasons=[],
        artifacts={
            "rule_trace": {
                "profile_inference": [
                    {
                        "rule_id": "INF-PROFILE-DS",
                        "source_title": "TTB Distilled Spirits Rules",
                        "source_type": "internal_doc",
                        "rationale": "profile rationale",
                        "source_ref": "docs/ttb_rules_distilled_spirits.md",
                    }
                ]
            }
        },
        errors=[],
    )


def test_label_only_mapping_normalized_match_to_pass():
    analysis = _analysis(
        OverallStatus.NORMALIZED_MATCH,
        {
            "brand_name": FieldStatus.NORMALIZED_MATCH,
            "class_type": FieldStatus.MATCH,
            "alcohol_content": FieldStatus.MATCH,
            "net_contents": FieldStatus.REVIEW,
            "bottler_producer": FieldStatus.REVIEW,
            "country_of_origin": FieldStatus.REVIEW,
            "government_warning": FieldStatus.REVIEW,
        },
    )

    explanation = build_result_explanation(
        analysis=analysis,
        parsed=analysis.parsed,
        review_mode="label_only",
        effective_label_type=LabelType.BRAND_LABEL,
        effective_product_profile=ProductProfile.DISTILLED_SPIRITS,
        field_labels={
            "brand_name": "Brand Name",
            "class_type": "Class / Type",
            "alcohol_content": "Alcohol Content",
            "net_contents": "Net Contents",
            "bottler_producer": "Bottler / Producer",
            "country_of_origin": "Country of Origin",
            "government_warning": "Government Warning",
        },
    )

    assert explanation.ui_overall_badge == "pass"
    assert explanation.ui_overall_label == "pass"


def test_label_only_mapping_mismatch_to_fail():
    analysis = _analysis(
        OverallStatus.MISMATCH,
        {
            "brand_name": FieldStatus.MISMATCH,
            "class_type": FieldStatus.MATCH,
            "alcohol_content": FieldStatus.MATCH,
            "net_contents": FieldStatus.REVIEW,
            "bottler_producer": FieldStatus.REVIEW,
            "country_of_origin": FieldStatus.REVIEW,
            "government_warning": FieldStatus.REVIEW,
        },
    )
    explanation = build_result_explanation(
        analysis=analysis,
        parsed=analysis.parsed,
        review_mode="label_only",
        effective_label_type=LabelType.BRAND_LABEL,
        effective_product_profile=ProductProfile.DISTILLED_SPIRITS,
        field_labels={"brand_name": "Brand Name", "class_type": "Class / Type", "alcohol_content": "Alcohol Content"},
    )

    assert explanation.ui_overall_badge == "fail"
    assert explanation.top_rules
