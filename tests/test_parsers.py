from app.services.parser_service import normalize_text, parse_alcohol_content, parse_net_contents


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
