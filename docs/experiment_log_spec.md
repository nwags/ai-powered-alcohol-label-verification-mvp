# Experiment Log Specification

## Purpose

An Experiment Log records every OCR/app evaluation run performed against a Benchmark Pack.

It exists to make OCR improvement work repeatable, comparable, and attributable.
This log format is designed for:
- PaddleOCR tuning
- preprocessing experiments
- model/version comparisons
- parser/rule changes
- category-sliced evaluation across Product Type and Label Type

---

## Top-Level Layout

```text
experiments/
  ocr_benchmark_v1/
    pack/
      benchmark_meta.json
      batch_index.json
    runs/
      2026-03-13_ppocr_baseline/
        run_config.json
        run_summary.json
        notes.md
        outputs/
      2026-03-14_ppocr_preproc_a/
        run_config.json
        run_summary.json
        notes.md
        outputs/
```

Notes:
- `ocr_benchmark_v1` ties experiment runs to a specific benchmark pack version.
- each run directory is immutable once complete
- `outputs/` stores copied or linked app batch results

---

## Run Directory Requirements

Each run directory must contain:
- `run_config.json`
- `run_summary.json`
- `notes.md`
- `outputs/`

---

## `run_config.json`

Purpose:
- exact machine-readable description of what was tested

Required fields:
- `run_id`
- `started_at`
- `benchmark_version`
- `benchmark_root`
- `app_version`
- `ocr_backend`
- `ocr_backend_version`
- `ocr_model_config`
- `preprocessing_config`
- `input_mode`
- `batch_selection`
- `execution_mode`
- `notes`

Recommended schema:

```json
{
  "run_id": "2026-03-13_ppocr_baseline",
  "started_at": "2026-03-13T14:00:00Z",
  "benchmark_version": "benchmark_v1",
  "benchmark_root": "cola_batches/benchmark_v1",
  "app_version": "git:<commit-or-tag>",
  "ocr_backend": "paddleocr",
  "ocr_backend_version": "3.x",
  "ocr_model_config": {
    "model_family": "PP-OCRv5",
    "profile": "server",
    "det_model": "default",
    "rec_model": "default",
    "use_doc_orientation_classify": false,
    "use_doc_unwarping": false,
    "use_textline_orientation": false
  },
  "preprocessing_config": {
    "variant_policy": "default",
    "max_dimension": 2200,
    "deskew": false,
    "extra_steps": []
  },
  "input_mode": "compare_csv",
  "batch_selection": {
    "include_batches": [
      "batch_0001__Distilled__Brand",
      "batch_0002__Wine__Back"
    ],
    "product_type_filter": ["Distilled", "Wine"],
    "label_type_filter": ["Brand", "Back"]
  },
  "execution_mode": {
    "single_review": false,
    "ui_batch_async": true,
    "api_batch_sync": false
  },
  "notes": "Baseline OCR run."
}
```

### `input_mode` allowed values
- `compare_csv`
- `compare_json`
- `label_only`

---

## `run_summary.json`

Purpose:
- machine-readable summary of experiment results

Required fields:
- `run_id`
- `completed_at`
- `status`
- `benchmark_version`
- `aggregate_metrics`
- `batch_results`

Recommended schema:

```json
{
  "run_id": "2026-03-13_ppocr_baseline",
  "completed_at": "2026-03-13T14:22:10Z",
  "status": "completed",
  "benchmark_version": "benchmark_v1",
  "aggregate_metrics": {
    "total_records": 500,
    "match": 220,
    "normalized_match": 90,
    "mismatch": 70,
    "review": 120,
    "field_accuracy": {
      "brand_name": 0.94,
      "class_type": 0.88,
      "alcohol_content": 0.91,
      "net_contents": 0.96,
      "bottler_producer": 0.73,
      "country_of_origin": 0.82,
      "government_warning": 0.89
    }
  },
  "batch_results": [
    {
      "batch_name": "batch_0001__Distilled__Brand",
      "batch_id": "batch-abc123",
      "input_mode": "compare_csv",
      "summary_json": "outputs/batch_0001__Distilled__Brand/summary.json",
      "summary_csv": "outputs/batch_0001__Distilled__Brand/summary.csv",
      "record_count": 250,
      "status": "completed"
    }
  ]
}
```

### `status` allowed values
- `completed`
- `failed`
- `partial`

---

## `notes.md`

Purpose:
- human-readable experiment notes

Recommended sections:
- objective
- config change from prior run
- qualitative observations
- major failure modes
- next change to test

Template:

```md
# Experiment Notes

## Objective
Evaluate baseline PP-OCR configuration on benchmark_v1.

## Change Compared to Previous Run
Initial run.

## Observations
- Brand labels on distilled spirits are strong.
- Back-label bottler/producer extraction remains weak.
- TIFF scans often require review.

## Major Failure Modes
- Small serif back-label text
- Dense government warning blocks
- Curved foil highlights

## Next Run
Enable orientation support and compare on Wine/Back.
```

---

## `outputs/` Layout

Purpose:
- preserve app-produced artifacts for the run

Recommended structure:

```text
outputs/
  batch_0001__Distilled__Brand/
    summary.json
    summary.csv
    copied_manifest.json
  batch_0002__Wine__Back/
    summary.json
    summary.csv
    copied_manifest.json
```

Rules:
- `summary.json` and `summary.csv` should be copied from app batch outputs or exported into this directory
- `copied_manifest.json` should match the benchmark batch manifest used for the run
- additive diagnostics artifacts are allowed

---

## Run ID Convention

Recommended:

```text
YYYY-MM-DD_<backend>_<descriptor>
```

Examples:
- `2026-03-13_ppocr_baseline`
- `2026-03-14_ppocr_preproc_contrast_a`
- `2026-03-15_ppocr_orientation_on`
- `2026-03-16_ppocr_det_tuned_wine_back`

Run IDs should be stable and human-readable.

---

## Category Attribution

Each run should explicitly record:
- which Product Type categories were included
- which Label Type categories were included

This is required because:
- rule expectations differ by category
- OCR difficulty differs by category
- iterative improvement often targets a category slice rather than the entire corpus

---

## Comparison Policy

When comparing runs, keep constant unless intentionally changed:
- benchmark version
- included batches
- input mode (`compare_csv` vs `compare_json`)
- app version where possible

If any of those change, record it explicitly in `run_config.json`.

---

## Minimal Required Metrics

Every completed run should record at least:
- total record count
- match / normalized_match / mismatch / review counts
- per-field accuracy for the seven canonical fields when compare-mode data exists
- batch-level output locations

---

## Optional Extended Metrics

Allowed but not required:
- CER/WER
- OCR latency distributions
- per-category confusion matrices
- TIFF-only performance slice
- Brand vs Back vs Other performance slice
- Beer vs Wine vs Distilled performance slice

---

## Validation Rules

A valid experiment run must satisfy:
1. `run_config.json` exists
2. `run_summary.json` exists
3. `notes.md` exists
4. `outputs/` exists
5. `run_id` matches between config and summary
6. `benchmark_version` matches the benchmark pack used
7. every referenced batch result path exists or is intentionally omitted with a failure status

---

## CSV vs JSON Compare Source Rule

If a batch includes both compare CSV and compare JSON:
- the run must declare which one was used in `input_mode`
- CSV and JSON are considered equivalent encodings of the same batch dataset
- differences between the two are treated as benchmark-pack defects, not experiment differences

---

## Recommended Workflow

1. build or update raw COLA run under `data/cola_raw/...`
2. generate benchmark pack under `cola_batches/benchmark_vN/...`
3. freeze benchmark pack version
4. run app batch evaluations against selected batches
5. copy/export results into `experiments/.../runs/<run_id>/outputs/`
6. write notes and compare metrics against prior run
