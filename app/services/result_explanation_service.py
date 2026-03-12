from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.enums import FieldStatus, LabelType, OverallStatus, ProductProfile
from app.domain.models import AnalyzeResponse, ParsedFields
from app.services.matching_service import priority_fields_for_label_type
from app.services.rule_registry import summarize_rule


@dataclass(frozen=True)
class ResultExplanation:
    ui_overall_badge: str
    ui_overall_label: str
    ui_overall_reason: str
    overall_evidence_confidence: str
    priority_fields: list[str]
    priority_summary: str
    non_priority_notice: str | None
    top_contributing_fields: list[dict[str, str]]
    top_rules: list[dict[str, str]]
    rule_trace_details: list[dict[str, Any]]


def build_result_explanation(
    *,
    analysis: AnalyzeResponse,
    parsed: ParsedFields,
    review_mode: str,
    effective_label_type: LabelType,
    effective_product_profile: ProductProfile,
    field_labels: dict[str, str],
) -> ResultExplanation:
    priority_fields = list(priority_fields_for_label_type(effective_label_type))
    ui_badge, ui_label = _ui_overall_badge(review_mode=review_mode, overall_status=analysis.overall_status)

    mode_label = "Label-Only Review" if review_mode == "label_only" else "Compare to Application"
    profile_label = effective_product_profile.value.replace("_", " ")
    label_type_label = effective_label_type.value.replace("_", " ")

    top_contributors = _top_contributing_fields(analysis, priority_fields, field_labels)
    top_rules = _top_rule_summaries(analysis, priority_fields)

    if top_contributors:
        contributor_phrase = ", ".join(item["label"] for item in top_contributors[:2])
        reason = f"{mode_label}: overall {ui_label} driven by priority evidence in {contributor_phrase}."
    else:
        reason = f"{mode_label}: overall {ui_label} from available priority-field evidence."

    priority_summary = (
        f"Overall status is prioritized using {label_type_label} fields for the {profile_label} product profile."
    )

    non_priority_notice = None
    if effective_label_type != LabelType.UNKNOWN:
        non_priority_notice = (
            "Some displayed fields are secondary for this label type and may be informational even when overall is positive."
        )

    rule_trace_details = _rule_trace_details(analysis)
    overall_confidence = _overall_evidence_confidence(analysis, parsed, priority_fields)

    return ResultExplanation(
        ui_overall_badge=ui_badge,
        ui_overall_label=ui_label,
        ui_overall_reason=reason,
        overall_evidence_confidence=overall_confidence,
        priority_fields=priority_fields,
        priority_summary=priority_summary,
        non_priority_notice=non_priority_notice,
        top_contributing_fields=top_contributors,
        top_rules=top_rules,
        rule_trace_details=rule_trace_details,
    )


def evidence_confidence_for_field(
    *,
    field_name: str,
    status: FieldStatus,
    parsed: ParsedFields,
) -> str:
    if field_name == "government_warning":
        confidence = parsed.government_warning.confidence
        if confidence is None:
            return _status_band(status)
        if confidence >= 0.85:
            return "high"
        if confidence >= 0.6:
            return "medium"
        return "low"
    return _status_band(status)


def _status_band(status: FieldStatus) -> str:
    if status in {FieldStatus.MATCH, FieldStatus.NORMALIZED_MATCH}:
        return "high"
    if status == FieldStatus.MISMATCH:
        return "low"
    if status == FieldStatus.REVIEW:
        return "unknown"
    return "unknown"


def _ui_overall_badge(*, review_mode: str, overall_status: OverallStatus) -> tuple[str, str]:
    if review_mode == "label_only":
        if overall_status in {OverallStatus.MATCH, OverallStatus.NORMALIZED_MATCH}:
            return "pass", "pass"
        if overall_status == OverallStatus.MISMATCH:
            return "fail", "fail"
        return "review", "review"
    return overall_status.value, overall_status.value


def _top_contributing_fields(
    analysis: AnalyzeResponse,
    priority_fields: list[str],
    field_labels: dict[str, str],
) -> list[dict[str, str]]:
    ranked: list[tuple[int, str, str]] = []
    for field_name in priority_fields:
        result = analysis.field_results.get(field_name)
        if not result:
            continue
        impact = _status_impact(result.status)
        note = (result.notes or "").strip()
        if impact > 0:
            ranked.append((impact, field_name, note))

    ranked.sort(reverse=True)
    output: list[dict[str, str]] = []
    for _, field_name, note in ranked[:4]:
        output.append(
            {
                "field_name": field_name,
                "label": field_labels.get(field_name, field_name),
                "status": analysis.field_results[field_name].status.value,
                "reason": note or "Contributed to overall outcome.",
            }
        )
    return output


def _status_impact(status: FieldStatus) -> int:
    if status == FieldStatus.MISMATCH:
        return 4
    if status == FieldStatus.REVIEW:
        return 3
    if status == FieldStatus.NORMALIZED_MATCH:
        return 2
    if status == FieldStatus.MATCH:
        return 1
    return 0


def _top_rule_summaries(analysis: AnalyzeResponse, priority_fields: list[str]) -> list[dict[str, str]]:
    rule_trace = analysis.artifacts.get("rule_trace", {})
    if not isinstance(rule_trace, dict):
        return []

    ordered_fields = ["profile_inference", "label_type_inference", *priority_fields]
    seen: set[str] = set()
    summaries: list[dict[str, str]] = []

    for field_name in ordered_fields:
        entries = rule_trace.get(field_name)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rule_id = entry.get("rule_id")
            if not isinstance(rule_id, str) or rule_id in seen:
                continue
            summary = summarize_rule(rule_id)
            if summary is None:
                continue
            summaries.append(summary)
            seen.add(rule_id)
            if len(summaries) >= 4:
                return summaries
    return summaries


def _rule_trace_details(analysis: AnalyzeResponse) -> list[dict[str, Any]]:
    rule_trace = analysis.artifacts.get("rule_trace", {})
    if not isinstance(rule_trace, dict):
        return []
    details: list[dict[str, Any]] = []
    for field_name, entries in rule_trace.items():
        if not isinstance(entries, list):
            continue
        details.append({"field_name": field_name, "entries": entries})
    return details


def _overall_evidence_confidence(analysis: AnalyzeResponse, parsed: ParsedFields, priority_fields: list[str]) -> str:
    score_map = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    scores: list[int] = []
    for field_name in priority_fields:
        result = analysis.field_results.get(field_name)
        if not result:
            continue
        band = evidence_confidence_for_field(field_name=field_name, status=result.status, parsed=parsed)
        scores.append(score_map.get(band, 0))
    if not scores:
        return "unknown"
    avg = sum(scores) / len(scores)
    if avg >= 2.4:
        return "high"
    if avg >= 1.4:
        return "medium"
    if avg > 0.0:
        return "low"
    return "unknown"
