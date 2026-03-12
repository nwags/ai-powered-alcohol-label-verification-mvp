from __future__ import annotations

from app.domain.enums import LabelType, ProductProfile
from app.domain.models import OCRResult, ParsedFields
from app.services.parser_service import normalize_text


def coerce_product_profile(value: str | ProductProfile | None) -> ProductProfile:
    if isinstance(value, ProductProfile):
        return value
    if isinstance(value, str):
        try:
            return ProductProfile(value)
        except ValueError:
            return ProductProfile.UNKNOWN
    return ProductProfile.UNKNOWN


def infer_product_profile(
    *,
    selected_hint: ProductProfile,
    ocr: OCRResult,
    parsed: ParsedFields | None = None,
) -> dict[str, object]:
    text = normalize_text(ocr.full_text or "")

    ds_terms = ("whiskey", "bourbon", "vodka", "gin", "rum", "tequila", "brandy", "proof")
    malt_terms = ("beer", "ale", "lager", "ipa", "stout", "porter", "malt beverage", "pilsner")
    wine_terms = ("wine", "pinot", "cabernet", "chardonnay", "merlot", "riesling", "mead", "cider")

    score_ds, ev_ds = _score_terms(text, ds_terms)
    score_malt, ev_malt = _score_terms(text, malt_terms)
    score_wine, ev_wine = _score_terms(text, wine_terms)

    if "fl oz" in text or "fluid ounce" in text:
        score_malt += 1.0
        ev_malt.append("fl oz")
    if "ml" in text or " l " in f" {text} ":
        score_ds += 0.4
        score_wine += 0.6

    if parsed is not None and parsed.class_type.value:
        normalized_class = normalize_text(parsed.class_type.value)
        if any(token in normalized_class for token in ds_terms):
            score_ds += 1.2
            ev_ds.append(parsed.class_type.value)
        if any(token in normalized_class for token in malt_terms):
            score_malt += 1.2
            ev_malt.append(parsed.class_type.value)
        if any(token in normalized_class for token in wine_terms):
            score_wine += 1.2
            ev_wine.append(parsed.class_type.value)

    ranked = [
        (ProductProfile.DISTILLED_SPIRITS, score_ds, ev_ds, "INF-PROFILE-DS"),
        (ProductProfile.MALT_BEVERAGE, score_malt, ev_malt, "INF-PROFILE-MALT"),
        (ProductProfile.WINE, score_wine, ev_wine, "INF-PROFILE-WINE"),
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)

    detected_profile = ProductProfile.UNKNOWN
    confidence = 0.0
    evidence: list[str] = []
    applied_rule_id = ""
    if ranked[0][1] >= 1.0:
        detected_profile = ranked[0][0]
        confidence = _confidence(ranked[0][1], ranked[1][1])
        evidence = ranked[0][2][:4]
        applied_rule_id = ranked[0][3]

    effective_profile = selected_hint if selected_hint != ProductProfile.UNKNOWN else detected_profile

    return {
        "selected_hint": selected_hint.value,
        "detected_profile": detected_profile.value,
        "effective_profile": effective_profile.value,
        "confidence": round(confidence, 2),
        "evidence": evidence,
        "rule_ids": [rule_id for rule_id in [applied_rule_id] if rule_id],
    }


def infer_label_type(
    *,
    selected_hint: LabelType,
    effective_profile: ProductProfile,
    ocr: OCRResult,
    parsed: ParsedFields,
) -> dict[str, object]:
    text = normalize_text(ocr.full_text or "")

    has_brand = bool(parsed.brand_name.value)
    has_class = bool(parsed.class_type.value)
    has_alcohol = parsed.alcohol_content.abv_percent is not None
    has_other = bool(parsed.government_warning.detected or parsed.net_contents.raw or parsed.bottler_producer.value or parsed.country_of_origin.value)

    brand_score = 0.0
    other_score = 0.0
    evidence: list[str] = []
    rule_ids: list[str] = []

    if effective_profile == ProductProfile.DISTILLED_SPIRITS:
        if has_brand and has_class and has_alcohol:
            brand_score += 2.5
            evidence.append("brand/class/alcohol co-occur")
            rule_ids.append("INF-LABELTYPE-DS-BRAND")
        if parsed.government_warning.detected:
            other_score += 1.0
    elif effective_profile == ProductProfile.WINE:
        if has_brand and has_class:
            brand_score += 1.8
            evidence.append("wine brand+class evidence")
        if "contains sulfites" in text:
            other_score += 0.8
            evidence.append("sulfites statement")
    elif effective_profile == ProductProfile.MALT_BEVERAGE:
        if has_brand and has_class:
            brand_score += 1.2
            evidence.append("malt identity line")
        if "fl oz" in text or "government warning" in text:
            other_score += 1.1
    else:
        if has_brand and has_class:
            brand_score += 1.2
        if has_other:
            other_score += 1.0

    if has_other:
        other_score += 0.6
        rule_ids.append("INF-LABELTYPE-OTHER")

    detected = LabelType.UNKNOWN
    if brand_score >= other_score + 0.8:
        detected = LabelType.BRAND_LABEL
    elif other_score >= brand_score + 0.8:
        detected = LabelType.OTHER_LABEL

    effective = selected_hint if selected_hint != LabelType.UNKNOWN else detected
    confidence = _confidence(max(brand_score, other_score), min(brand_score, other_score))
    if detected == LabelType.UNKNOWN:
        confidence = 0.0

    return {
        "selected_hint": selected_hint.value,
        "detected_label_type": detected.value,
        "effective_label_type": effective.value,
        "confidence": round(confidence, 2),
        "evidence": evidence[:4],
        "rule_ids": sorted(set(rule_ids)),
    }


def _score_terms(text: str, terms: tuple[str, ...]) -> tuple[float, list[str]]:
    evidence: list[str] = []
    score = 0.0
    for term in terms:
        if term in text:
            score += 1.0
            evidence.append(term)
    return score, evidence


def _confidence(top: float, runner_up: float) -> float:
    if top <= 0:
        return 0.0
    gap = max(0.0, top - runner_up)
    capped = min(1.0, (gap / max(1.0, top)) + min(top / 4.0, 0.5))
    return capped
