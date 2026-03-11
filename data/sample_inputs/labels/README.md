# Label Test Dataset (MVP Scaffold)

This directory defines a practical MVP dataset layout for manual reviewer testing,
smoke tests, and batch demos.

No binary images are committed in this scaffold step.
Add real or synthetic images later using the naming rules below.

## Directory Categories

- `real_reviewed/`
  - Labels captured from real reviewed examples (accepted and rejected).
  - Best source for realistic OCR + compliance behavior.

- `synthetic_variants/`
  - Image-quality variants derived from known labels.
  - Used to test OCR robustness (blur, rotation, lighting, low contrast, compression).

- `ai_adversarial/`
  - Intentionally problematic or misleading labels (text spoofing, conflicting fields).
  - Used to verify conservative `review` behavior and reduce false certainty.

## Record Folder Convention

Each label case should be a folder:

- `real_reviewed/rr_###_<short_name>/`
- `synthetic_variants/sv_###_<short_name>/`
- `ai_adversarial/adv_###_<short_name>/`

Recommended files inside each case folder:

- `label.*`
  - Main image file, for example `label.jpg`.
- `expected.json`
  - Sidecar with expected behavior for this case.
- `notes.md` (optional)
  - Reviewer notes, source details, or preprocessing notes.

## Expected Sidecar Format

See `expected.schema.json` for the full schema.

Minimum required keys:

- `case_id`
- `category`
- `description`
- `expected_overall_status`
- `expected_field_results`
- `input_hint`

Allowed `expected_overall_status` and field statuses:

- `match`
- `normalized_match`
- `mismatch`
- `review`

## Practical Input Guidance

### Label-Only UI Mode

Use folders in any category with `label.*` and `expected.json`.
No application payload is required.

### Compare UI/API Mode

Use `expected.json.application_data` as the source for
`application_json` payloads.

### Batch Label-Only Mode

ZIP multiple `label.*` files from selected case folders.
Use `expected.json.expected_overall_status` for quick spot checks.

### Batch Compare Mode

Build CSV/JSON records from `expected.json.application_data` plus
image filename mappings.

## Synthetic Variant Generation Guidance

When creating synthetic variants from a base label:

- keep original text content intact unless intentionally testing text corruption
- vary one or two factors at a time for diagnosability
- capture transforms in `input_hint` and `notes.md`

Suggested transforms:

- gaussian blur
- low contrast
- perspective skew
- rotation (small and large)
- jpeg compression artifacts
- shadows or glare overlays

## AI/Adversarial Guidance

Mark cases as adversarial when they include at least one of:

- warning text spoof or partial warning mimicry
- conflicting ABV/proof statements
- manipulated brand/class text
- visually plausible but semantically inconsistent labels

Expected outcomes should prioritize conservative `review` where certainty is low.

## Current Placeholder Cases

This scaffold includes example sidecars for:

- `rr_001_accept_clean`
- `rr_002_reject_missing_warning`
- `sv_001_blur_low_contrast`
- `sv_002_rotation_perspective`
- `adv_001_warning_spoof`
- `adv_002_field_conflict`

Replace placeholder labels with real files later without changing schema.
