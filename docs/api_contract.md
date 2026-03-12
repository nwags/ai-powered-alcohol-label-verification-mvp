# API Contract

This document defines the canonical HTTP contract for the prototype.

This file is authoritative for endpoint paths, methods, content types, and high-level response shapes.

If code introduces new endpoints or changes existing routes, this file must be updated.

---

# API Design Principles

1. Keep the API small and explicit.
2. Separate UI routes from JSON API routes.
3. Prefer synchronous single-label analysis for MVP.
4. Return structured errors.
5. Reuse the models defined in docs/data_models.md.

---

# Base Route Groups

UI routes:

- `GET /`
- `POST /ui/analyze`
- `GET /ui/batch`
- `POST /ui/batch`
- `GET /ui/batch/{batch_id}/record/{record_id}`
- `GET /ui/diagnostics` (developer-only, optional)
- `POST /ui/diagnostics/coverage` (developer-only, optional)
- `GET /ui/diagnostics/coverage/status` (developer-only, optional)

JSON API routes:

- `GET /healthz`
- `GET /readyz`
- `GET /api/v1/ocr/status`
- `POST /api/v1/analyze`
- `POST /api/v1/batch/analyze`

Optional demo/debug routes:

- `GET /api/v1/demo/sample/{name}`

No other public routes should be added in MVP unless this document is updated.

---

# Health Endpoints

## GET /healthz

Purpose:

Basic liveness check.

Response:

- HTTP 200 on success

Example:

```json
{
  "status": "ok"
}
```

---

## GET /readyz

Purpose:

Readiness check for app startup and dependencies.

Response:

- HTTP 200 when ready
- HTTP 503 when not ready

Example success:

```json
{
  "status": "ready",
  "ocr_loaded": true,
  "storage_ok": true,
  "db_ok": true
}
```

Example not ready:

```json
{
  "status": "not_ready",
  "ocr_loaded": false,
  "storage_ok": true,
  "db_ok": true
}
```

---

# UI Endpoints

## GET /

Purpose:

Render the main reviewer page.

Response:

- HTTP 200
- HTML page

---

## POST /ui/analyze

Purpose:

Accept a single uploaded image and application fields from the browser UI.

Request content type:

`multipart/form-data`

Fields:

- `image` required
- `review_mode` optional (`label_only` default, `compare_application` alternate)
- `label_type` optional (`unknown` default, `brand_label` or `other_label`)
- `product_profile` optional (`unknown` default, `distilled_spirits`, `malt_beverage`, `wine`)
- `application_json` optional (used in `compare_application` mode)

Response:

- HTTP 200
- HTML result page

This route should reuse the same internal service pipeline as `POST /api/v1/analyze`.

UI behavior:

- `label_only` mode is the default and hides application-data entry fields.
- `compare_application` mode reveals application-data entry fields for side-by-side checks.
- `label_type` is a lightweight hint for emphasis:
  - `brand_label`: prioritize brand/class/alcohol for overall aggregation.
  - `other_label`: prioritize warning/bottler/net/country for overall aggregation.
  - `unknown`: keep full-field aggregation.

---

## GET /ui/batch

Purpose:

Render the batch upload page.

Response:

- HTTP 200
- HTML page
- HTTP 404 when batch UI is disabled via `ENABLE_BATCH_UI=false`

This route may be omitted temporarily if batch mode is deferred

---

## POST /ui/batch

Purpose:

Accept batch upload from the browser UI.

Request content type:

`multipart/form-data`

Fields:

- `batch_review_mode` optional (`batch_label_only` default, `batch_compare_application` alternate)
- `label_type` optional (`unknown` default, batch-level hint for all records)
- `product_profile` optional (`unknown` default, batch-level profile hint for all records)
- `images_archive` required in label-only mode
- `batch_file` required in compare mode

Response:

- HTTP 200
- HTML batch result page
- HTTP 404 when batch UI is disabled via `ENABLE_BATCH_UI=false`

This route may be omitted temporarily if batch mode is deferred.

UI behavior:

- `batch_label_only` mode is the default and focuses on ZIP-only label screening.
- `batch_compare_application` mode preserves CSV/JSON + image ZIP comparison workflow.

## GET /ui/batch/{batch_id}/record/{record_id}

Purpose:

Render a lightweight per-record detail view linked from the batch report.

Response:

- HTTP 200
- HTML page
- HTTP 404 when batch UI is disabled or batch/record artifact is unavailable

Notes:

- This route reads persisted batch summary artifacts for the requested record.
- This route does not trigger re-analysis.

---

## GET /ui/diagnostics

Purpose:

Render developer diagnostics for local/demo debugging.

Response:

- HTTP 200 when diagnostics UI is enabled
- HTTP 404 when diagnostics UI is disabled

Notes:

- This route must be gated behind `ENABLE_DIAGNOSTICS_UI=true`.
- This route is developer-oriented and should not be part of normal reviewer workflow.
- This route may display latest test coverage summary from local pytest-cov artifacts when available.
- This route must not execute full test suites on page load.

## POST /ui/diagnostics/coverage

Purpose:

Trigger manual coverage generation from the diagnostics UI.

Response:

- HTTP 303 redirect to `/ui/diagnostics`
- HTTP 404 when diagnostics UI is disabled

Notes:

- Coverage generation must only run when this action is requested.
- Coverage generation state should be surfaced in `/ui/diagnostics` (idle/running/success/failure).

## GET /ui/diagnostics/coverage/status

Purpose:

Return machine-readable coverage run state for diagnostics UI polling.

Response:

- HTTP 200 with JSON payload including:
  - `coverage_run` (`state`, `message`, `last_exit_code`)
  - `coverage` summary snapshot (`available`, `total_percent`, `covered_lines`, `num_statements`, `html_url`)
- HTTP 404 when diagnostics UI is disabled

Notes:

- This endpoint must be gated behind `ENABLE_DIAGNOSTICS_UI=true`.
- This endpoint must not trigger coverage generation.

---

# JSON API Endpoints

## POST /api/v1/analyze

Purpose:

Analyze one label image against submitted application data.

Request content type:

`multipart/form-data`

Required parts:

- `image`
- `application_json`

Optional parts:

- `label_type` (`unknown` default; allowed values: `unknown`, `brand_label`, `other_label`)
- `product_profile` (`unknown` default; allowed values: `unknown`, `distilled_spirits`, `malt_beverage`, `wine`)

Success response:

- HTTP 200
- `application/json`

Response body:

Must follow the single-label response model defined in `docs/data_models.md`.

Minimum top-level keys:

- `request_id`
- `overall_status`
- `timing_ms`
- `ocr`
- `parsed`
- `field_results`
- `artifacts`
- `errors`

Error responses:

- HTTP 400 for invalid request
- HTTP 415 for unsupported image type
- HTTP 422 for malformed input fields
- HTTP 500 for unexpected internal failure

---

## GET /api/v1/ocr/status

Purpose:

Expose current OCR engine lifecycle state for UI feedback.

Response:

- HTTP 200 with OCR status payload

Example:

```json
{
  "state": "warming",
  "ready": false,
  "message": "OCR warmup is in progress.",
  "error": null
}
```

Allowed `state` values:

- `cold`
- `warming`
- `ready`
- `failed`

---

## POST /api/v1/batch/analyze

Purpose:

Analyze multiple label/application pairs in one request.

Request content type:

`multipart/form-data`

Optional fields:

- `label_type` (`unknown` default; batch-level hint applied to all records)

Required parts:

- `batch_file`

Optional parts:

- `images_archive`

Success response:

- HTTP 200
- `application/json`

Response body:

Must follow the batch response model defined in `docs/data_models.md`.

Minimum top-level keys:

- `batch_id`
- `summary`
- `results`
- `errors`

This endpoint is optional for MVP but reserved now so route names stay stable.

---

## GET /api/v1/demo/sample/{name}

Purpose:

Return a predefined sample result or run analysis on a bundled sample.

Response:

- HTTP 200 on known sample
- HTTP 404 if sample name is unknown

This route is optional and should not be required for core functionality.

---

# Error Contract

All JSON API errors should use this shape:

```json
{
  "error": {
    "code": "invalid_image",
    "message": "Uploaded file is not a supported image format."
  }
}
```

Allowed error codes:

- `invalid_request`
- `invalid_image`
- `image_too_large`
- `ocr_failed`
- `not_ready`
- `internal_error`

Do not return stack traces to clients.

---

# Content Types

Supported request content types:

- `multipart/form-data` for image and batch uploads
- `application/json` only for future extensions if explicitly added later

Supported response content types:

- `text/html` for UI routes
- `application/json` for JSON API routes

---

# Route Stability Rules

1. Do not rename endpoints without updating this file.
2. Do not create duplicate analyze routes with different shapes.
3. UI routes must call the same internal pipeline as JSON routes.
4. Health routes must remain lightweight and fast.

---

# Implementation Notes

Recommended route files:

- `app/api/routes_health.py`
- `app/api/routes_ui.py`
- `app/api/routes_analyze.py`
- `app/api/routes_batch.py`

Recommended behavior:

- keep route handlers thin
- move OCR, parsing, and matching into services
- keep request/response models aligned with `docs/data_models.md`

---

# Change Control

If any endpoint, method, request shape, or response shape changes, update this file and `docs/data_models.md` together.
