# MVP Test Plan Dataset Usage

This project uses `data/sample_inputs/labels/` as a practical test dataset scaffold
for manual reviewer testing, smoke checks, and batch demos.

The dataset is intentionally split into three categories:

- `real_reviewed/`: realistic reference labels from reviewed examples.
- `synthetic_variants/`: controlled OCR-stress transforms (blur, rotation, contrast).
- `ai_adversarial/`: intentionally misleading/manipulated labels.

Each case folder should contain:

- `label.*` (image placeholder for now)
- `expected.json` (expected status + field outcomes)
- optional `notes.md`

The canonical sidecar schema is:

- `data/sample_inputs/labels/expected.schema.json`

## How To Use The Dataset

### Manual Single-Label Checks

1. Choose a case folder and upload `label.*` in `/ui`.
2. Use Label-Only or Compare mode based on `expected.json.input_hint.recommended_mode`.
3. Confirm returned status is directionally consistent with `expected_overall_status`.
4. For compare runs, validate field-level outcomes against `expected_field_results`.

Goal: Verify reviewer-facing behavior is conservative (`review` when uncertain)
and compliant with distilled-spirits requirements.

### Smoke Tests

Use these minimum smoke cases:

- Positive control: `real_reviewed/rr_001_accept_clean`
- Warning failure control: `real_reviewed/rr_002_reject_missing_warning`
- OCR stress control: `synthetic_variants/sv_001_blur_low_contrast`

Pass criteria:

- App remains stable (no server crash).
- Results are returned for each input.
- Statuses align with expected direction (`match` vs `mismatch/review`).

### Batch Demo Runs

#### Batch Label-Only Review

- Select cases where `recommended_mode` is `label_only` or `batch_label_only`.
- Build a ZIP containing multiple `label.*` files.
- Run `/ui/batch` in label-only mode.
- Spot check outputs against each case `expected_overall_status`.

#### Batch Compare To Application Data

- Select cases with `recommended_mode` of `compare_application` or `batch_compare_application`.
- Build records CSV/JSON from each case `application_data`.
- Pair records with image ZIP as required by batch compare workflow.
- Validate field-level outputs against `expected_field_results`.

## Authoring New Cases

When adding new examples:

1. Duplicate the nearest existing case folder pattern.
2. Keep case IDs stable and category-prefixed (`rr_`, `sv_`, `adv_`).
3. Set `expected_overall_status` conservatively.
4. If any result is ambiguous, prefer `review` rather than `match`.
5. Record transform/adversarial notes in `input_hint.notes` and optional `notes.md`.

## Notes For This Prototype Stage

- No binary images are committed in this step.
- Placeholder case folders and sidecars are ready for real label assets.
- Dataset supports both reviewer productivity flows:
  - Label-only screening (default)
  - Compare-to-application validation
