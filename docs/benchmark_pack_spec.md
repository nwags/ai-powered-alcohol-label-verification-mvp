# Benchmark Pack Specification

## Purpose

A Benchmark Pack is the canonical on-disk format for running repeatable OCR and field-verification experiments against the AI-Powered Alcohol Label Verification app.

It supports both:
- compare-mode evaluation (`compare.csv` or `compare.json` + `images.zip`)
- label-only evaluation (`images.zip` only, optionally with `manifest.json`)

The format is designed to:
- align with the app's existing batch contract
- preserve provenance back to COLA scrape outputs
- support categorical experiment slicing by Product Type and Label Type
- remain stable across repeated OCR experiments

---

## Top-Level Layout

```text
cola_batches/
  benchmark_v1/
    benchmark_meta.json
    batch_index.json
    batch_0001__Distilled__Brand/
      batch_0001__Distilled__Brand_images.zip
      batch_0001__Distilled__Brand.csv
      batch_0001__Distilled__Brand.json
      batch_0001__Distilled__Brand_manifest.json
    batch_0002__Wine__Back/
      ...
```

Notes:
- `benchmark_v1` is the immutable benchmark-pack version identifier.
- Each batch directory is a self-contained batch input unit.
- A batch may include both `.csv` and `.json` compare files. The contents must be equivalent.
- If both are present, either may be used by the app runner. They are alternate encodings of the same compare dataset.

---

## Naming Convention

### Benchmark Root
- `benchmark_v1`
- `benchmark_v2`
- etc.

### Batch Directory

Recommended pattern:

```text
batch_<NNNN>__<ProductType>__<LabelType>
```

Examples:
- `batch_0001__Distilled__Brand`
- `batch_0002__Wine__Back`
- `batch_0003__Beer__Other`

### Canonical Category Values

#### Product Type
- `Beer`
- `Wine`
- `Distilled`

#### Label Type
- `Brand`
- `Back`
- `Other`

If future rule review changes these values, the benchmark pack version should change rather than silently renaming old packs.

---

## Required Files

### 1. `benchmark_meta.json`

Required once per benchmark root.

Purpose:
- describes the benchmark pack as a whole

Required fields:
- `benchmark_name`
- `benchmark_version`
- `created_at`
- `source_runs`
- `category_axes`
- `notes`

Example:

```json
{
  "benchmark_name": "ocr_benchmark",
  "benchmark_version": "benchmark_v1",
  "created_at": "2026-03-13T12:00:00Z",
  "source_runs": [
    "data/cola_raw/20260313_run"
  ],
  "category_axes": {
    "product_type": ["Beer", "Wine", "Distilled"],
    "label_type": ["Brand", "Back", "Other"]
  },
  "notes": "Initial benchmark pack built from COLA scrape outputs."
}
```

### 2. `batch_index.json`

Required once per benchmark root.

Purpose:
- inventory of all batch directories and their metadata
- enables bulk iteration without scanning directory contents heuristically

Required fields:
- `benchmark_version`
- `batches`

Each batch entry must include:
- `batch_id`
- `batch_name`
- `product_type`
- `label_type`
- `record_count`
- `image_count`
- `has_compare_csv`
- `has_compare_json`
- `images_zip`
- `manifest_path`
- `directory`

Example:

```json
{
  "benchmark_version": "benchmark_v1",
  "batches": [
    {
      "batch_id": "batch_0001",
      "batch_name": "batch_0001__Distilled__Brand",
      "product_type": "Distilled",
      "label_type": "Brand",
      "record_count": 250,
      "image_count": 250,
      "has_compare_csv": true,
      "has_compare_json": true,
      "images_zip": "batch_0001__Distilled__Brand/batch_0001__Distilled__Brand_images.zip",
      "manifest_path": "batch_0001__Distilled__Brand/batch_0001__Distilled__Brand_manifest.json",
      "directory": "batch_0001__Distilled__Brand"
    }
  ]
}
```

---

## Per-Batch Files

### 1. `*_images.zip`

Required.

Purpose:
- image archive used by the app batch flow

Rules:
- archive contents must contain the actual image files referenced by `image_filename`
- filenames inside the ZIP must match the `image_filename` values in compare files exactly
- preserve original extensions when possible (`.jpg`, `.jpeg`, `.png`, `.webp`, `.tif`, `.tiff`, etc.)

### 2. `*.csv`

Optional but recommended for compare-mode packs.

Purpose:
- compare-mode application-record input in CSV form

Header must be:

```text
record_id,image_filename,brand_name,class_type,alcohol_content,net_contents,bottler_producer,country_of_origin,government_warning
```

Additional columns are allowed if they are clearly additive metadata, but the app-facing canonical compare schema is the field set above.

### 3. `*.json`

Optional but recommended for compare-mode packs.

Purpose:
- compare-mode application-record input in JSON array form

Each object must contain:
- `record_id`
- `image_filename`
- `brand_name`
- `class_type`
- `alcohol_content`
- `net_contents`
- `bottler_producer`
- `country_of_origin`
- `government_warning`

### 4. `*_manifest.json`

Required.

Purpose:
- provenance and batch-local metadata not required by the app compare contract itself

Required top-level fields:
- `batch_id`
- `batch_name`
- `benchmark_version`
- `product_type`
- `label_type`
- `record_count`
- `image_count`
- `compare_csv`
- `compare_json`
- `images_zip`
- `records`

Each `records` entry should include:
- `record_id`
- `image_filename`
- `product_type`
- `label_type`
- `ttbid` if known
- `detail_url` if known
- `src_url` if known
- `actual_dimensions` if known
- `raw_run_path` if known
- `raw_html_path` if known
- `raw_text_path` if known
- `raw_record_ref` if known

Example:

```json
{
  "batch_id": "batch_0001",
  "batch_name": "batch_0001__Distilled__Brand",
  "benchmark_version": "benchmark_v1",
  "product_type": "Distilled",
  "label_type": "Brand",
  "record_count": 2,
  "image_count": 2,
  "compare_csv": "batch_0001__Distilled__Brand.csv",
  "compare_json": "batch_0001__Distilled__Brand.json",
  "images_zip": "batch_0001__Distilled__Brand_images.zip",
  "records": [
    {
      "record_id": "cola-12345-brand-001",
      "image_filename": "cola-12345-brand-front.jpg",
      "product_type": "Distilled",
      "label_type": "Brand",
      "ttbid": "12345",
      "detail_url": "https://...",
      "src_url": "https://...",
      "actual_dimensions": "800 x 1200",
      "raw_run_path": "data/cola_raw/20260313_run",
      "raw_html_path": "data/cola_raw/20260313_run/html/12345.html",
      "raw_text_path": "data/cola_raw/20260313_run/text/12345.txt",
      "raw_record_ref": "records.jsonl#12345"
    }
  ]
}
```

---

## Compare-Mode Semantics

A batch is compare-mode compatible if it includes:
- `*_images.zip`
- and at least one of:
  - `*.csv`
  - `*.json`

CSV and JSON must be semantically equivalent if both exist.

The app may ingest either encoding.

---

## Label-Only Semantics

A batch is label-only compatible if it includes:
- `*_images.zip`

A label-only-only pack may omit compare CSV/JSON, but must still include `*_manifest.json`.

---

## Record ID Rules

`record_id` must:
- be unique within the batch
- be stable across experiment runs
- not depend on temporary file ordering

Recommended pattern:

```text
<source>-<ttbid>-<labeltype>-<seq>
```

Examples:
- `cola-12345-brand-001`
- `cola-12345-back-001`

---

## Image Filename Rules

`image_filename` must:
- match the file inside the ZIP exactly
- preserve extension
- remain stable across runs
- not require directory prefixes inside compare files

Examples:
- `cola-12345-brand-front.jpg`
- `cola-67890-back-warning.tiff`

---

## Compatibility Rules

### Backward Compatibility

Older batch-builder outputs may be adapted into this format if:
- compare CSV/JSON conforms to the canonical schema
- images ZIP filenames match `image_filename`
- a manifest is added or transformed to the required format

### Forward Compatibility

New additive manifest fields are allowed.
Canonical compare fields must not be renamed without a benchmark version bump.

---

## Validation Rules

A valid Benchmark Pack must satisfy:
1. `benchmark_meta.json` exists
2. `batch_index.json` exists
3. every indexed batch directory exists
4. every indexed batch has `*_images.zip`
5. every indexed batch has `*_manifest.json`
6. every compare-mode batch has at least one of `*.csv` or `*.json`
7. every `image_filename` in compare files exists inside the ZIP
8. every `record_id` is unique within the batch

---

## Raw Source Linkage

Benchmark packs are derived from `cola_raw` runs, which are expected to use this shape:

```text
data/
  cola_raw/
    YYYYMMDD_run/
      html/
      text/
      json/
        records.jsonl
        taxonomy.json
        summary.json
      images/
```

This raw layout mirrors the scraper’s current output model and should remain the canonical provenance source for benchmark-pack generation.
