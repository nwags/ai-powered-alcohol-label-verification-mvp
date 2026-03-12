from __future__ import annotations

from typing import Any

from app.domain.enums import ProductProfile

RuleEntry = dict[str, str]


_RULES: dict[str, RuleEntry] = {
    "INF-PROFILE-DS": {
        "rule_id": "INF-PROFILE-DS",
        "product_profile": ProductProfile.DISTILLED_SPIRITS.value,
        "label_type_scope": "all",
        "field": "profile_inference",
        "source_type": "internal_doc",
        "source_citation": "docs/ttb_rules_distilled_spirits.md",
        "source_title": "TTB Distilled Spirits Rules",
        "source_ref": "docs/ttb_rules_distilled_spirits.md",
        "rationale": "Spirits lexicon and alc/vol patterns indicate distilled spirits profile.",
    },
    "INF-PROFILE-MALT": {
        "rule_id": "INF-PROFILE-MALT",
        "product_profile": ProductProfile.MALT_BEVERAGE.value,
        "label_type_scope": "all",
        "field": "profile_inference",
        "source_type": "project_scope",
        "source_citation": "malt beverage profile split",
        "source_title": "Project Scope Beverage Profiles",
        "source_ref": "docs/project_scope.md",
        "rationale": "Beer/malt lexicon and U.S. customary patterns indicate malt beverage profile.",
    },
    "INF-PROFILE-WINE": {
        "rule_id": "INF-PROFILE-WINE",
        "product_profile": ProductProfile.WINE.value,
        "label_type_scope": "all",
        "field": "profile_inference",
        "source_type": "project_scope",
        "source_citation": "wine profile split",
        "source_title": "Project Scope Beverage Profiles",
        "source_ref": "docs/project_scope.md",
        "rationale": "Wine/varietal/appellation cues indicate wine profile.",
    },
    "INF-LABELTYPE-DS-BRAND": {
        "rule_id": "INF-LABELTYPE-DS-BRAND",
        "product_profile": ProductProfile.DISTILLED_SPIRITS.value,
        "label_type_scope": "brand_label",
        "field": "label_type_inference",
        "source_type": "internal_doc",
        "source_citation": "same-field-of-vision",
        "source_title": "TTB Distilled Spirits Rules",
        "source_ref": "docs/ttb_rules_distilled_spirits.md",
        "rationale": "Brand/class/alcohol co-occurrence suggests distilled spirits brand label.",
    },
    "INF-LABELTYPE-OTHER": {
        "rule_id": "INF-LABELTYPE-OTHER",
        "product_profile": "unknown",
        "label_type_scope": "other_label",
        "field": "label_type_inference",
        "source_type": "api_contract",
        "source_citation": "other-label emphasis",
        "source_title": "API Contract Label Type Hint",
        "source_ref": "docs/api_contract.md",
        "rationale": "Warning/net/bottler/country evidence suggests other-label content.",
    },
    "PARSE-BRAND-BASE": {
        "rule_id": "PARSE-BRAND-BASE",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "brand_name",
        "source_type": "project_scope",
        "source_citation": "required field",
        "source_title": "Project Scope Required Fields",
        "source_ref": "docs/project_scope.md",
        "rationale": "Brand candidate excludes warning, net, alcohol, and class-only lines.",
    },
    "PARSE-CLASS-PROFILE": {
        "rule_id": "PARSE-CLASS-PROFILE",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "class_type",
        "source_type": "project_scope",
        "source_citation": "required field",
        "source_title": "Project Scope Required Fields",
        "source_ref": "docs/project_scope.md",
        "rationale": "Class/type extraction uses profile-specific lexicons.",
    },
    "PARSE-ALCOHOL-NORMALIZE": {
        "rule_id": "PARSE-ALCOHOL-NORMALIZE",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "alcohol_content",
        "source_type": "acceptance_criteria",
        "source_citation": "parse alcohol content and proof",
        "source_title": "Acceptance Criteria Parsing",
        "source_ref": "docs/acceptance_criteria.md",
        "rationale": "Normalize OCR alcohol expressions and proof evidence conservatively.",
    },
    "PARSE-NET-PROFILE": {
        "rule_id": "PARSE-NET-PROFILE",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "net_contents",
        "source_type": "project_scope",
        "source_citation": "required field",
        "source_title": "Project Scope Required Fields",
        "source_ref": "docs/project_scope.md",
        "rationale": "Net contents parsing supports metric and customary units by profile.",
    },
    "PARSE-BOTTLER-ROLE": {
        "rule_id": "PARSE-BOTTLER-ROLE",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "bottler_producer",
        "source_type": "project_scope",
        "source_citation": "required field",
        "source_title": "Project Scope Required Fields",
        "source_ref": "docs/project_scope.md",
        "rationale": "Role markers and continuation stitching identify bottler/producer data.",
    },
    "PARSE-COUNTRY-IMPORT": {
        "rule_id": "PARSE-COUNTRY-IMPORT",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "country_of_origin",
        "source_type": "internal_doc",
        "source_citation": "imports concept",
        "source_title": "TTB Distilled Spirits Rules",
        "source_ref": "docs/ttb_rules_distilled_spirits.md",
        "rationale": "Country extraction emphasizes product-of/import-context evidence.",
    },
    "WARN-SHARED": {
        "rule_id": "WARN-SHARED",
        "product_profile": "unknown",
        "label_type_scope": "all",
        "field": "government_warning",
        "source_type": "acceptance_criteria",
        "source_citation": "warning detection",
        "source_title": "Acceptance Criteria Warning Detection",
        "source_ref": "docs/acceptance_criteria.md",
        "rationale": "Government warning evaluation is shared across profiles and conservative.",
    },
}


def get_rule(rule_id: str) -> RuleEntry | None:
    return _RULES.get(rule_id)


def registry_snapshot() -> dict[str, RuleEntry]:
    return dict(_RULES)


def build_rule_trace(rule_ids_by_field: dict[str, list[str]]) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    for field_name, rule_ids in rule_ids_by_field.items():
        entries: list[dict[str, str]] = []
        for rule_id in rule_ids:
            entry = get_rule(rule_id)
            if entry:
                entries.append(entry)
        if entries:
            trace[field_name] = entries
    return trace


def short_rule_tags(rule_ids: list[str]) -> str:
    if not rule_ids:
        return ""
    return " [rules: " + ", ".join(rule_ids) + "]"


def summarize_rule(rule_id: str) -> dict[str, str] | None:
    entry = get_rule(rule_id)
    if not entry:
        return None
    return {
        "rule_id": rule_id,
        "title": entry.get("source_title", "Rule"),
        "summary": entry.get("rationale", "Rule applied."),
    }
