import re

from app.domain.models import (
    OCRResult,
    ParsedAlcoholContent,
    ParsedFields,
    ParsedNetContents,
    ParsedTextValue,
    ParsedWarning,
)

ALCOHOL_PERCENT_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:alc\.?\s*/?\s*vol\.?|alcohol by volume)?", re.IGNORECASE)
PROOF_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*proof", re.IGNORECASE)
ML_RE = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*(ml|mL|ML|l|L)\b")
COUNTRY_RE = re.compile(r"(?:product of|made in|produced in)\s+(.+)", re.IGNORECASE)
WARNING_PREFIX_RE = re.compile(r"\bgovernment\s+warning\s*:", re.IGNORECASE)

KNOWN_CLASSES = ("whiskey", "vodka", "rum", "gin", "tequila", "brandy")
BOTTLER_MARKERS = ("bottled by", "produced by", "distilled by", "imported by")


def parse_ocr_text(ocr: OCRResult) -> ParsedFields:
    """Parse best-effort structured fields from OCR text lines.

    The parser is intentionally heuristic-based and conservative for MVP:
    when a field cannot be confidently extracted, it returns `None`.
    """
    lines = [line.text.strip() for line in ocr.lines if line.text and line.text.strip()]
    confidence_by_line = {line.text.strip(): line.confidence for line in ocr.lines if line.text and line.text.strip()}
    full_text = "\n".join(lines) if lines else ocr.full_text or ""

    alcohol = parse_alcohol_content(full_text)
    net = parse_net_contents(full_text)
    class_type = _detect_class_type(lines, full_text)
    bottler = _detect_bottler(lines)
    country = _detect_country(lines)
    warning = _detect_warning(lines, confidence_by_line)
    brand = _detect_brand(lines)

    return ParsedFields(
        brand_name=ParsedTextValue(value=brand),
        class_type=ParsedTextValue(value=class_type),
        alcohol_content=alcohol,
        net_contents=net,
        bottler_producer=ParsedTextValue(value=bottler),
        country_of_origin=ParsedTextValue(value=country),
        government_warning=warning,
    )


def normalize_text(value: str) -> str:
    """Normalize text for comparison (case, quotes, punctuation, whitespace)."""
    normalized = value.casefold()
    normalized = normalized.replace("’", "'").replace("‘", "'").replace("`", "'")
    normalized = normalized.replace("“", '"').replace("”", '"')
    normalized = re.sub(r"[^\w\s%./:']", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def parse_alcohol_content(text: str) -> ParsedAlcoholContent:
    """Parse ABV/proof values and normalize proof<->ABV equivalence."""
    abv_match = ALCOHOL_PERCENT_RE.search(text)
    proof_match = PROOF_RE.search(text)

    abv_percent = float(abv_match.group(1)) if abv_match else None
    proof = float(proof_match.group(1)) if proof_match else None
    raw = abv_match.group(0) if abv_match else (proof_match.group(0) if proof_match else None)

    if abv_percent is None and proof is not None:
        abv_percent = round(proof / 2.0, 2)
    if proof is None and abv_percent is not None:
        proof = round(abv_percent * 2.0, 2)

    return ParsedAlcoholContent(raw=raw, abv_percent=abv_percent, proof=proof)


def parse_net_contents(text: str) -> ParsedNetContents:
    """Parse net contents and normalize to milliliters when possible."""
    match = ML_RE.search(text)
    if not match:
        return ParsedNetContents(raw=None, milliliters=None)

    amount = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "l":
        milliliters = int(round(amount * 1000))
    else:
        milliliters = int(round(amount))
    return ParsedNetContents(raw=match.group(0), milliliters=milliliters)


def _detect_class_type(lines: list[str], full_text: str) -> str | None:
    text = normalize_text(full_text)
    for class_name in KNOWN_CLASSES:
        if class_name in text:
            return class_name.capitalize()
    for line in lines:
        normalized = normalize_text(line)
        for class_name in KNOWN_CLASSES:
            if class_name in normalized:
                return class_name.capitalize()
    return None


def _detect_bottler(lines: list[str]) -> str | None:
    for line in lines:
        normalized = normalize_text(line)
        if any(marker in normalized for marker in BOTTLER_MARKERS):
            return line
    return None


def _detect_country(lines: list[str]) -> str | None:
    for line in lines:
        match = COUNTRY_RE.search(line)
        if match:
            return match.group(1).strip(" .")
    return None


def _detect_warning(lines: list[str], confidence_by_line: dict[str, float]) -> ParsedWarning:
    for index, line in enumerate(lines):
        if not WARNING_PREFIX_RE.search(line):
            continue

        warning_lines = [line]
        if index + 1 < len(lines):
            warning_lines.append(lines[index + 1])
        if index + 2 < len(lines):
            warning_lines.append(lines[index + 2])
        joined = " ".join(warning_lines).strip()

        has_uppercase_prefix = "GOVERNMENT WARNING:" in line
        confidences = [confidence_by_line.get(item, 0.0) for item in warning_lines]
        avg_confidence = sum(confidences) / len(confidences) if confidences else None
        return ParsedWarning(
            value=joined,
            detected=True,
            has_uppercase_prefix=has_uppercase_prefix,
            confidence=avg_confidence,
        )
    return ParsedWarning(value=None, detected=False, has_uppercase_prefix=False, confidence=None)


def _detect_brand(lines: list[str]) -> str | None:
    if not lines:
        return None

    for line in lines:
        normalized = normalize_text(line)
        if not normalized:
            continue
        if WARNING_PREFIX_RE.search(line):
            continue
        if any(marker in normalized for marker in BOTTLER_MARKERS):
            continue
        if COUNTRY_RE.search(line):
            continue
        if ALCOHOL_PERCENT_RE.search(line) or PROOF_RE.search(line) or ML_RE.search(line):
            continue
        return line
    return lines[0]
