from app.domain.enums import LabelType, ProductProfile
from app.domain.models import OCRLine, OCRResult, ParsedAlcoholContent, ParsedFields, ParsedNetContents, ParsedTextValue, ParsedWarning
from app.services.inference_service import infer_label_type, infer_product_profile


def _ocr(text: str) -> OCRResult:
    return OCRResult(
        full_text=text,
        lines=[OCRLine(text=text, confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]])],
    )


def test_infer_product_profile_detects_distilled_spirits_when_hint_unknown():
    parsed = ParsedFields(class_type=ParsedTextValue(value="Straight Bourbon Whiskey"))
    result = infer_product_profile(
        selected_hint=ProductProfile.UNKNOWN,
        ocr=_ocr("STONE'S THROW STRAIGHT BOURBON WHISKEY 45% ALC./VOL. 750 ML"),
        parsed=parsed,
    )

    assert result["detected_profile"] == ProductProfile.DISTILLED_SPIRITS.value
    assert result["effective_profile"] == ProductProfile.DISTILLED_SPIRITS.value
    assert result["confidence"] > 0


def test_infer_product_profile_respects_non_unknown_hint():
    result = infer_product_profile(
        selected_hint=ProductProfile.WINE,
        ocr=_ocr("STONE RIDGE CABERNET WINE 12% ALC BY VOL 750 ML"),
        parsed=ParsedFields(),
    )

    assert result["selected_hint"] == ProductProfile.WINE.value
    assert result["effective_profile"] == ProductProfile.WINE.value


def test_infer_label_type_profile_aware_brand_detection_for_distilled_spirits():
    parsed = ParsedFields(
        brand_name=ParsedTextValue(value="Stone's Throw"),
        class_type=ParsedTextValue(value="Whiskey"),
        alcohol_content=ParsedAlcoholContent(raw="45% Alc./Vol.", abv_percent=45.0, proof=90.0),
        net_contents=ParsedNetContents(raw="750 mL", milliliters=750),
        government_warning=ParsedWarning(value=None, detected=False, has_uppercase_prefix=False, confidence=None),
    )
    result = infer_label_type(
        selected_hint=LabelType.UNKNOWN,
        effective_profile=ProductProfile.DISTILLED_SPIRITS,
        ocr=_ocr("STONE'S THROW WHISKEY 45% ALC./VOL. 750 ML"),
        parsed=parsed,
    )

    assert result["detected_label_type"] == LabelType.BRAND_LABEL.value
    assert result["effective_label_type"] == LabelType.BRAND_LABEL.value
