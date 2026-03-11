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

---

# Error Handling

Invalid images must not crash the system.

Errors must return clear messages.

---

# Batch Mode (Optional)

Batch processing may accept:

CSV plus label images.

This feature is optional but recommended.

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
