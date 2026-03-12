from app.domain.enums import ProductProfile
from app.domain.models import OCRLine, OCRResult
from app.services.parser_service import normalize_text, parse_alcohol_content, parse_net_contents, parse_ocr_text


def test_normalize_text_handles_quotes_punctuation_and_whitespace():
    raw = "  Stone’s   Throw  --  WHISKEY  "
    assert normalize_text(raw) == "stone's throw whiskey"


def test_parse_alcohol_content_supports_proof_conversion():
    parsed = parse_alcohol_content("90 Proof")
    assert parsed.proof == 90.0
    assert parsed.abv_percent == 45.0


def test_parse_net_contents_supports_liter_conversion():
    parsed = parse_net_contents("1.75 L")
    assert parsed.milliliters == 1750


def test_parse_net_contents_normalizes_common_ocr_ml_confusion():
    parsed = parse_net_contents("Net cont. 750 mi")
    assert parsed.milliliters == 750


def test_parse_net_contents_supports_fl_oz_for_malt_profile():
    parsed = parse_net_contents("12 FL OZ", product_profile=ProductProfile.MALT_BEVERAGE)
    assert parsed.milliliters == 355


def test_parse_alcohol_content_converts_proof_to_abv_for_all_profiles():
    parsed = parse_alcohol_content("90 Proof", product_profile=ProductProfile.WINE)
    assert parsed.proof == 90.0
    assert parsed.abv_percent == 45.0


def test_parse_ocr_text_extracts_class_phrase_with_modifiers():
    ocr = OCRResult(
        full_text="SUMMIT CREEK\nSTRAIGHT BOURBON WHISKEY\n45% Alc./Vol.",
        lines=[
            OCRLine(text="SUMMIT CREEK", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="STRAIGHT BOURBON WHISKEY", confidence=0.91, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="45% Alc./Vol.", confidence=0.95, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )
    parsed = parse_ocr_text(ocr)
    assert parsed.class_type.value == "Straight Bourbon Whiskey"


def test_parse_ocr_text_uses_profile_aware_class_vocab_for_wine():
    ocr = OCRResult(
        full_text="STONE RIDGE\nPINOT NOIR WINE\n12% ALC. BY VOL.",
        lines=[
            OCRLine(text="STONE RIDGE", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="PINOT NOIR WINE", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="12% ALC. BY VOL.", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )
    parsed = parse_ocr_text(ocr, product_profile=ProductProfile.WINE)
    assert parsed.class_type.value == "Wine"


def test_parse_ocr_text_stitches_bottler_continuation_line():
    ocr = OCRResult(
        full_text="Bottled by\nSummit Creek Distilling Co., Louisville, KY",
        lines=[
            OCRLine(text="Bottled by", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(
                text="Summit Creek Distilling Co., Louisville, KY",
                confidence=0.9,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
        ],
    )
    parsed = parse_ocr_text(ocr)
    assert parsed.bottler_producer.value == "Bottled by Summit Creek Distilling Co., Louisville, KY"


def test_parse_ocr_text_prefers_phrase_level_country_over_noisy_token():
    ocr = OCRResult(
        full_text="Imported by Valley Wine Co.\nProduct of Italy\ntaly - L. 04/17",
        lines=[
            OCRLine(text="Imported by Valley Wine Co.", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="Product of Italy", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="taly - L. 04/17", confidence=0.7, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )
    parsed = parse_ocr_text(ocr, product_profile=ProductProfile.WINE)
    assert parsed.country_of_origin.value == "Italy"


def test_parse_ocr_text_prefers_brand_title_over_paragraph_copy():
    ocr = OCRResult(
        full_text=(
            "Blue Ridge Estate Vineyard & Winery\n"
            "operated by husband and wife, Randy and Tiffany\n"
            "Product of Italy"
        ),
        lines=[
            OCRLine(text="Blue Ridge Estate Vineyard & Winery", confidence=0.96, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(
                text="operated by husband and wife, Randy and Tiffany",
                confidence=0.94,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
            OCRLine(text="Product of Italy", confidence=0.88, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )
    parsed = parse_ocr_text(ocr, product_profile=ProductProfile.WINE)
    assert parsed.brand_name.value == "Blue Ridge Estate Vineyard & Winery"


def test_parse_ocr_text_does_not_stitch_non_bottler_line():
    ocr = OCRResult(
        full_text="Bottled by\nHandcrafted for bourbon lovers",
        lines=[
            OCRLine(text="Bottled by", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="Handcrafted for bourbon lovers", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )
    parsed = parse_ocr_text(ocr)
    assert parsed.bottler_producer.value == "Bottled by"


def test_parse_ocr_text_expands_warning_across_multiple_lines():
    ocr = OCRResult(
        full_text=(
            "GOVERNMENT WARNING: (1) According to the Surgeon General,\n"
            "women should not drink alcoholic beverages during pregnancy\n"
            "because of the risk of birth defects.\n"
            "(2) Consumption of alcoholic beverages impairs your ability to drive\n"
            "a car or operate machinery, and may cause health problems."
        ),
        lines=[
            OCRLine(
                text="GOVERNMENT WARNING: (1) According to the Surgeon General,",
                confidence=0.85,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
            OCRLine(
                text="women should not drink alcoholic beverages during pregnancy",
                confidence=0.85,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
            OCRLine(
                text="because of the risk of birth defects.",
                confidence=0.85,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
            OCRLine(
                text="(2) Consumption of alcoholic beverages impairs your ability to drive",
                confidence=0.85,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
            OCRLine(
                text="a car or operate machinery, and may cause health problems.",
                confidence=0.85,
                bbox=[[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
        ],
    )
    parsed = parse_ocr_text(ocr)
    assert parsed.government_warning.detected is True
    assert "health problems" in (parsed.government_warning.value or "").lower()
