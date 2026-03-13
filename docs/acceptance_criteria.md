# Acceptance Criteria

This document defines when the prototype is considered complete.

---

# Local Development

The application must run locally using:

docker compose up

The service must start successfully.

---

# Health Endpoints

The following endpoints must exist:

GET /healthz  
GET /readyz

Expected readiness behavior:

- `GET /healthz` returns HTTP 200 for basic liveness.
- `GET /readyz` returns HTTP 200 when dependencies are ready.
- `GET /readyz` returns HTTP 503 when dependencies are not ready.

---

# Single Label Analysis

Users must be able to:

1. upload a label image
2. enter application fields
3. submit for analysis

The system must return:

- extracted text
- field comparison results
- overall recommendation

---

# Status Values

Allowed field statuses:

match  
normalized_match  
mismatch  
review

No other status values are allowed.

---

# OCR Extraction

Text must be extracted using PaddleOCR.

The full extracted text must be included in the response.

---

# Parsing

The system must parse:

- alcohol content
- proof
- net contents
- warning statement

---

# Warning Detection

The government warning statement must be detected.

If detection fails:

status = review.

---

# User Interface

The UI must display:

- uploaded label image
- extracted OCR text
- parsed fields
- comparison results
- overall recommendation

Single-result table behavior:

- In Label-Only Review, hide the `Submitted` column.
- In Compare to Application Data mode, show the `Submitted` column.

Single/batch detail parity behavior (MVP groundwork):

- Batch record detail should use the same core result sections/semantics as single-label
  result rendering (badge semantics, field rows, confidence labels, rule snippets where available).
- The only intentional navigation difference is:
  - single result: analyze-another-label action
  - batch detail: back-to-batch-report action

---

# Error Handling

Invalid images must not crash the system.

Errors must return clear messages.

---

# Batch Mode (Optional)

Batch processing may accept:

CSV plus label images.

This feature is optional but recommended.

If batch UI is enabled, expected MVP behavior:

- batch submission enqueues work and redirects immediately to persisted report URL
- submit action immediately shows submitted/running state (disabled button + spinner/copy)
- report page shows queued/running/completed/failed status and polls persisted status endpoint
- summary counts and record rows refresh progressively from persisted artifacts
- resulting report is addressable at a persisted batch report URL
- batch detail pages provide a back-link to that exact report URL
- unfinished batch detail requests must return a clear not-ready response without crashing
- report and detail resources must load from persisted artifacts after redirect
  without relying on transient form-page state

---

# Deployment Readiness

The application must run in Docker and be deployable to Azure App Service.

No code changes should be required for deployment.

---

# Demo Readiness

The repository must include:

- README instructions
- sample images
- example application data

A reviewer must be able to run the demo in under 10 minutes.
