from app.domain.enums import FieldStatus, LabelType, OverallStatus, ProductProfile
from app.domain.models import AnalyzeResponse, FieldResult, OCRResult, ParsedFields
from app.services.result_presenter import build_batch_detail_result_view, build_result_view_from_analysis


FIELD_LABELS = {
    "brand_name": "Brand Name",
    "class_type": "Class / Type",
    "alcohol_content": "Alcohol Content",
    "net_contents": "Net Contents",
    "bottler_producer": "Bottler / Producer",
    "country_of_origin": "Country of Origin",
    "government_warning": "Government Warning",
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


def test_build_result_view_from_analysis_has_expected_shared_sections():
    analysis = AnalyzeResponse(
        request_id="req-1",
        overall_status=OverallStatus.REVIEW,
        timing_ms=120,
        ocr=OCRResult(full_text="STONE'S THROW", lines=[]),
        parsed=ParsedFields(),
        field_results={
            "brand_name": FieldResult(
                status=FieldStatus.REVIEW,
                submitted_value="Stone's Throw",
                detected_value="STONE'S THROW",
                notes="Needs review",
            )
        },
        review_reasons=["Needs reviewer attention."],
        artifacts={"inference": {"product_profile": {}, "label_type": {}}, "rule_trace": {}},
        errors=[],
    )

    view = build_result_view_from_analysis(
        analysis=analysis,
        review_mode="compare_application",
        field_labels=FIELD_LABELS,
        label_type_labels=LABEL_TYPE_LABELS,
        product_profile_labels=PRODUCT_PROFILE_LABELS,
        label_type_hint=LabelType.UNKNOWN,
        product_profile_hint=ProductProfile.UNKNOWN,
        uploaded_filename="label.jpg",
        uploaded_image_url="/storage/uploads/label.jpg",
        annotated_image_url=None,
        page_heading="Analysis Result",
        nav_label="Analyze Another Label",
        nav_url="/",
    )

    assert view["page_heading"] == "Analysis Result"
    assert view["navigation"]["label"] == "Analyze Another Label"
    assert isinstance(view["field_rows"], list)
    assert view["field_rows"][0]["label"] == "Brand Name"


def test_build_batch_detail_result_view_uses_shared_shape_and_batch_nav():
    row = {
        "record_id": "img-001",
        "request_id": "req-2",
        "overall_status": "review",
        "image_filename": "label1.jpg",
        "image_url": "/storage/outputs/batch/batch-1/images/label1.jpg",
        "annotated_image_url": "/storage/outputs/annotated/example.jpg",
        "timing_ms": 88,
        "evaluation_mode": "label_only",
        "ocr_full_text": "TEXT",
        "field_results": {
            "brand_name": {
                "status": "review",
                "submitted_value": None,
                "detected_value": "STONE'S THROW",
                "notes": "Needs review",
            }
        },
        "parsed": {},
        "review_reasons": ["Needs reviewer attention."],
        "ocr_errors": [],
        "inference": {"product_profile": {}, "label_type": {}},
        "rule_trace": {
            "brand_name": [
                {
                    "rule_id": "RULE-BRAND-001",
                    "source_title": "Synthetic Test Rule",
                    "rationale": "Test rationale",
                }
            ]
        },
    }

    view = build_batch_detail_result_view(
        batch_id="batch-1",
        record_id="img-001",
        row=row,
        field_labels=FIELD_LABELS,
        label_type_labels=LABEL_TYPE_LABELS,
        product_profile_labels=PRODUCT_PROFILE_LABELS,
    )

    assert view["page_heading"] == "Batch Record Detail"
    assert view["navigation"]["label"] == "Back to Batch Report"
    assert view["navigation"]["url"] == "/ui/batch/batch-1"
    assert view["page_meta"]["batch_id"] == "batch-1"
    assert view["annotated_image_url"] == "/storage/outputs/annotated/example.jpg"
    assert view["field_rows"][0]["evidence_confidence"] in {"high", "medium", "low", "unknown"}
    assert "[RULE-BRAND-001]" in (view["field_rows"][0]["notes"] or "")
