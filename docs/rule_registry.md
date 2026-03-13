# Rule Registry and Traceability (MVP)

The MVP includes an internal rule registry that maps evaluator logic to trace metadata.

## Registry Entry Shape

Each rule entry includes:

- `rule_id`
- `product_profile`
- `label_type_scope`
- `field`
- `source_type`
- `source_citation`
- `source_title`
- `source_ref`
- `rationale`

## Runtime Usage

- Evaluators collect applied `rule_id` values per field.
- Analysis artifacts expose machine-readable `rule_trace` per field.
- Parsed-field evidence links may reference canonical OCR evidence line IDs
  (from normalized OCR evidence) so field extraction and rule traces can be
  tied back to explicit OCR geometry provenance.
- UI can append compact rule IDs in rationale text for reviewer transparency.
- Result explanation uses `rule_trace` as canonical input and derives compact,
  reviewer-facing summaries from the same metadata.

## Notes

- `artifacts.rule_trace` is canonical for machines.
- Field-note tags and “Why this result” summaries are UI-layer explanations
  and a bridge toward fuller rule-engine behavior.
