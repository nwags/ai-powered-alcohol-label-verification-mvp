import re
from difflib import SequenceMatcher

from app.domain.enums import ProductProfile
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
US_CUSTOMARY_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:fl\.?\s*oz\.?|fluid ounces?|oz\.?)\b", re.IGNORECASE)
COUNTRY_RE = re.compile(r"(?:product of|made in|produced in|imported from)\s+([A-Za-z][A-Za-z .,'-]{1,60})", re.IGNORECASE)
WARNING_PREFIX_RE = re.compile(r"\bgovernment\s+warning\s*:", re.IGNORECASE)
CLASS_PHRASE_RE = re.compile(
    r"\b((?:(?:straight|blended|single|small|batch|kentucky|tennessee|bourbon|rye|malt|grain|aged|anejo|reposado)\s+){0,4}"
    r"(whiskey|vodka|rum|gin|tequila|brandy))\b",
    re.IGNORECASE,
)

KNOWN_CLASSES = ("whiskey", "vodka", "rum", "gin", "tequila", "brandy")
DISTILLED_CLASS_TERMS = ("whiskey", "vodka", "rum", "gin", "tequila", "brandy", "bourbon", "rye")
MALT_CLASS_TERMS = ("beer", "ale", "lager", "ipa", "stout", "porter", "malt beverage", "pilsner")
WINE_CLASS_TERMS = ("wine", "cabernet", "pinot", "merlot", "chardonnay", "riesling", "mead", "cider")
BOTTLER_MARKERS = ("bottled by", "produced by", "distilled by", "imported by", "bottled for", "distributed by")
WARNING_CONTINUATION_TOKENS = (
    "surgeon",
    "general",
    "pregnancy",
    "birth",
    "defects",
    "consumption",
    "impairs",
    "machinery",
    "health",
    "problems",
    "(1)",
    "(2)",
)
COUNTRY_CANONICAL = {
    "united states": "United States",
    "u.s.a": "United States",
    "usa": "United States",
    "mexico": "Mexico",
    "canada": "Canada",
    "scotland": "Scotland",
    "ireland": "Ireland",
    "japan": "Japan",
    "france": "France",
    "italy": "Italy",
    "spain": "Spain",
}
NET_CONTEXT_RE = re.compile(r"\bnet\s*(?:contents?|cont\.?)\b", re.IGNORECASE)
NET_METRIC_NOISY_RE = re.compile(
    r"(?P<amount>\d{1,4}(?:\.\d+)?)\s*(?P<unit>m\s*[\.\-_/\\]?\s*[l1i]|l|lt|liter|litre)\b",
    re.IGNORECASE,
)
COUNTRY_TRAILING_NOISE_RE = re.compile(r"(?:\s*[-;,].*|\s+l\.?\s*\d{1,2}.*)$", re.IGNORECASE)
BRAND_PROSE_RE = re.compile(
    r"\b(?:operated|founded|husband|wife|family|crafted|fermented|aged|cellared|estate grown|story|history)\b",
    re.IGNORECASE,
)


def parse_ocr_text(ocr: OCRResult, product_profile: ProductProfile = ProductProfile.UNKNOWN) -> ParsedFields:
    """Parse best-effort structured fields from OCR text lines.

    The parser is intentionally heuristic-based and conservative for MVP:
    when a field cannot be confidently extracted, it returns `None`.
    """
    lines = [line.text.strip() for line in ocr.lines if line.text and line.text.strip()]
    confidence_by_line = {line.text.strip(): line.confidence for line in ocr.lines if line.text and line.text.strip()}
    full_text = "\n".join(lines) if lines else ocr.full_text or ""

    alcohol = parse_alcohol_content(full_text, product_profile=product_profile)
    net = parse_net_contents(full_text, product_profile=product_profile)
    class_type = _detect_class_type(lines, full_text, product_profile=product_profile)
    bottler = _detect_bottler(lines)
    country = _detect_country(lines)
    warning = _detect_warning(lines, confidence_by_line)
    brand = _detect_brand(lines, product_profile=product_profile)

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


def parse_alcohol_content(text: str, product_profile: ProductProfile = ProductProfile.UNKNOWN) -> ParsedAlcoholContent:
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


def parse_net_contents(text: str, product_profile: ProductProfile = ProductProfile.UNKNOWN) -> ParsedNetContents:
    """Parse net contents and normalize to milliliters when possible."""
    noisy_metric_match = NET_METRIC_NOISY_RE.search(text)
    if noisy_metric_match:
        unit_token = _normalize_metric_unit(noisy_metric_match.group("unit"))
        has_net_context = bool(NET_CONTEXT_RE.search(text))
        if unit_token == "ml" and (has_net_context or "ml" in noisy_metric_match.group("unit").lower() or "m" in noisy_metric_match.group("unit").lower()):
            amount = float(noisy_metric_match.group("amount"))
            return ParsedNetContents(raw=noisy_metric_match.group(0), milliliters=int(round(amount)))
        if unit_token == "l":
            amount = float(noisy_metric_match.group("amount"))
            return ParsedNetContents(raw=noisy_metric_match.group(0), milliliters=int(round(amount * 1000)))

    match = ML_RE.search(text)
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        if unit == "l":
            milliliters = int(round(amount * 1000))
        else:
            milliliters = int(round(amount))
        return ParsedNetContents(raw=match.group(0), milliliters=milliliters)

    custom_match = US_CUSTOMARY_RE.search(text)
    if custom_match:
        ounces = float(custom_match.group(1))
        milliliters = int(round(ounces * 29.5735))
        raw = custom_match.group(0)
        if product_profile == ProductProfile.MALT_BEVERAGE:
            return ParsedNetContents(raw=raw, milliliters=milliliters)
        return ParsedNetContents(raw=raw, milliliters=milliliters)

    return ParsedNetContents(raw=None, milliliters=None)


def _detect_class_type(lines: list[str], full_text: str, product_profile: ProductProfile) -> str | None:
    phrase = _find_class_phrase(full_text, product_profile=product_profile)
    if phrase:
        return phrase
    for line in lines:
        phrase = _find_class_phrase(line, product_profile=product_profile)
        if phrase:
            return phrase
    return None


def _detect_bottler(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        marker = next((value for value in BOTTLER_MARKERS if value in normalized), None)
        if not marker:
            continue

        candidate = line
        has_location_hint = "," in line or re.search(r"\b[A-Z]{2}\b", line) is not None
        if not has_location_hint and index + 1 < len(lines):
            next_line = lines[index + 1]
            normalized_next = normalize_text(next_line)
            if _looks_like_bottler_continuation(normalized_next):
                candidate = f"{line} {next_line}".strip()
        return candidate
    return None


def _detect_country(lines: list[str]) -> str | None:
    # Prefer phrase-level evidence ("Product of X", "Produced in X", etc.).
    for line in lines:
        match = COUNTRY_RE.search(line)
        if match:
            candidate = COUNTRY_TRAILING_NOISE_RE.sub("", match.group(1)).strip(" .")
            canonical = _canonicalize_country(candidate)
            if canonical:
                return canonical
            cleaned = re.sub(r"\s+", " ", candidate).strip()
            if cleaned and len(cleaned.split()) <= 3:
                return cleaned.title()

    for line in lines:
        normalized_line = normalize_text(line)
        if normalized_line.startswith("imported from "):
            candidate = normalized_line.replace("imported from ", "").strip(" .")
            canonical = _canonicalize_country(candidate)
            if canonical:
                return canonical
        if normalized_line in COUNTRY_CANONICAL:
            return COUNTRY_CANONICAL[normalized_line]
    return None


def _detect_warning(lines: list[str], confidence_by_line: dict[str, float]) -> ParsedWarning:
    for index, line in enumerate(lines):
        if not WARNING_PREFIX_RE.search(line):
            continue

        warning_lines = [line]
        next_index = index + 1
        while next_index < len(lines) and len(warning_lines) < 6:
            candidate = lines[next_index]
            if not _looks_like_warning_continuation(normalize_text(candidate)):
                break
            warning_lines.append(candidate)
            if "health problems" in normalize_text(candidate):
                break
            next_index += 1
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


def _detect_brand(lines: list[str], product_profile: ProductProfile) -> str | None:
    if not lines:
        return None

    candidates: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
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
        if US_CUSTOMARY_RE.search(line):
            continue
        if _looks_like_class_only_line(normalized):
            continue
        if _looks_like_profile_designation_line(normalized, product_profile):
            continue
        score = _brand_line_score(index, line, normalized)
        candidates.append((score, line))
    if not candidates:
        return lines[0]
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _find_class_phrase(text: str, product_profile: ProductProfile) -> str | None:
    normalized = normalize_text(text)
    if product_profile in {ProductProfile.UNKNOWN, ProductProfile.DISTILLED_SPIRITS}:
        match = CLASS_PHRASE_RE.search(normalized)
        if match:
            phrase = match.group(1).strip()
            return " ".join(token.capitalize() for token in phrase.split())
        for term in DISTILLED_CLASS_TERMS:
            if _contains_term(normalized, term):
                return " ".join(token.capitalize() for token in term.split())
    if product_profile in {ProductProfile.UNKNOWN, ProductProfile.MALT_BEVERAGE}:
        for term in MALT_CLASS_TERMS:
            if _contains_term(normalized, term):
                return " ".join(token.capitalize() for token in term.split())
    if product_profile in {ProductProfile.UNKNOWN, ProductProfile.WINE}:
        for term in WINE_CLASS_TERMS:
            if _contains_term(normalized, term):
                return " ".join(token.capitalize() for token in term.split())
    return None


def _looks_like_bottler_continuation(normalized_line: str) -> bool:
    if not normalized_line:
        return False
    if any(marker in normalized_line for marker in BOTTLER_MARKERS):
        return False
    if WARNING_PREFIX_RE.search(normalized_line):
        return False
    if ALCOHOL_PERCENT_RE.search(normalized_line) or PROOF_RE.search(normalized_line) or ML_RE.search(normalized_line):
        return False
    has_company_term = any(token in normalized_line for token in ("co", "company", "distilling", "spirits", "llc", "inc"))
    # Use punctuation as a lightweight location hint and avoid generic two-letter matches.
    has_location = "," in normalized_line
    return has_company_term or has_location


def _looks_like_warning_continuation(normalized_line: str) -> bool:
    if not normalized_line:
        return False
    if ALCOHOL_PERCENT_RE.search(normalized_line) or PROOF_RE.search(normalized_line) or ML_RE.search(normalized_line):
        return False
    return any(token in normalized_line for token in WARNING_CONTINUATION_TOKENS)


def _looks_like_class_only_line(normalized_line: str) -> bool:
    if not normalized_line:
        return False
    tokens = normalized_line.split()
    if len(tokens) > 5:
        return False
    return any(_contains_term(normalized_line, class_name) for class_name in KNOWN_CLASSES + MALT_CLASS_TERMS + WINE_CLASS_TERMS)


def _looks_like_profile_designation_line(normalized_line: str, product_profile: ProductProfile) -> bool:
    profile_tokens: tuple[str, ...]
    if product_profile == ProductProfile.DISTILLED_SPIRITS:
        profile_tokens = DISTILLED_CLASS_TERMS
    elif product_profile == ProductProfile.MALT_BEVERAGE:
        profile_tokens = MALT_CLASS_TERMS
    elif product_profile == ProductProfile.WINE:
        profile_tokens = WINE_CLASS_TERMS
    else:
        profile_tokens = ()
    if not profile_tokens:
        return False
    return any(_contains_term(normalized_line, token) for token in profile_tokens)


def _contains_term(normalized_line: str, term: str) -> bool:
    escaped = re.escape(term)
    pattern = rf"\b{escaped}\b"
    return re.search(pattern, normalized_line) is not None


def _normalize_metric_unit(unit: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", unit.lower())
    if normalized in {"l", "lt", "liter", "litre"}:
        return "l"
    if normalized.startswith("m"):
        return "ml"
    return normalized


def _canonicalize_country(candidate: str) -> str | None:
    normalized = normalize_text(candidate)
    if not normalized:
        return None
    for key, canonical in COUNTRY_CANONICAL.items():
        if key in normalized or normalized in key:
            return canonical
    tokens = [token for token in normalized.split() if token]
    for token in tokens:
        for key, canonical in COUNTRY_CANONICAL.items():
            ratio = SequenceMatcher(None, token, key).ratio()
            if ratio >= 0.84:
                return canonical
    return None


def _brand_line_score(index: int, raw_line: str, normalized_line: str) -> int:
    words = [token for token in normalized_line.split() if token]
    word_count = len(words)
    score = 0

    if index <= 2:
        score += 3
    elif index <= 5:
        score += 1

    if 2 <= word_count <= 7:
        score += 2
    if word_count >= 10:
        score -= 4

    uppercase_letters = sum(1 for char in raw_line if char.isalpha() and char.isupper())
    letters = sum(1 for char in raw_line if char.isalpha())
    if letters > 0 and (uppercase_letters / letters) >= 0.55:
        score += 2

    if "&" in raw_line:
        score += 1
    if "," in raw_line:
        score -= 2
    if BRAND_PROSE_RE.search(raw_line):
        score -= 5
    if re.search(r"[.!?]\s*$", raw_line):
        score -= 2
    if re.search(r"\b(?:and|with|by)\b", normalized_line) and word_count >= 8:
        score -= 2
    return score
