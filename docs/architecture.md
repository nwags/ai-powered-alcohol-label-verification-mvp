# System Architecture

This document defines the intended architecture of the prototype.

The goal is to prevent unnecessary complexity and keep the system easy
for both humans and AI agents to modify.

---

# Architectural Principles

1. Single service application
2. Clear separation of concerns
3. Deterministic rule-based verification
4. Minimal dependencies
5. Local-first processing

---

# High Level Architecture

The system consists of three layers.

API Layer  
Services Layer  
Domain Logic

Flow:

User Upload  
→ FastAPI Endpoint  
→ OCR Service  
→ Parsing Service  
→ Matching Service  
→ Result Response

---

# Application Structure

app/

api/  
FastAPI route definitions

services/  
Core processing logic

domain/  
Data models and enums

utils/  
Reusable helpers

templates/  
HTML UI templates

static/  
CSS and JavaScript

storage/  
Uploads and outputs

---

# API Layer

Located in:

app/api/

Responsibilities:

- receive requests
- validate input
- call services
- return responses

Endpoints:

GET /healthz  
GET /readyz  
POST /analyze  
POST /batch

The API layer should contain minimal logic.

---

# Services Layer

Located in:

app/services/

Responsibilities:

- OCR extraction
- image preprocessing
- text parsing
- matching logic
- visualization

Each service should perform a single responsibility.

---

# Core Services

ocr_service.py

Runs PaddleOCR to extract text and bounding boxes.

---

image_preprocess.py

Performs image cleanup:

- grayscale conversion
- contrast improvement
- deskew
- resizing

---

parser_service.py

Extracts structured values from OCR text.

Examples:

- alcohol percentage
- proof
- net contents
- warning statement

---

matching_service.py

Compares parsed label values with application data.
Applies optional `label_type` hint routing to prioritize
brand-focused vs other-label-focused field aggregation for MVP.
Applies optional `product_profile` hint/inference to use
profile-aware normalization and evaluation heuristics.

Returns:

match  
normalized_match  
mismatch  
review

---

warning_service.py

Validates the government warning statement.

---

visualization_service.py

Highlights bounding boxes where fields were detected.

---

inference_service.py

Performs explainable, heuristic inference for:

- product profile (`distilled_spirits`, `malt_beverage`, `wine`, `unknown`)
- label type (`brand_label`, `other_label`, `unknown`)

Inference metadata is stored in analysis artifacts for UI transparency.

---

rule_registry.py

Provides lightweight rule metadata registry and traceability helpers.
Evaluators attach rule IDs, and artifacts keep machine-readable rule traces.

---

result_explanation_service.py

Builds reviewer-facing overall explanations from existing analysis outputs,
inference metadata, and rule traces.
This is a UI explanation layer (not a full rule executor) and intentionally
serves as a bridge for future rules-engine expansion.

---

# Domain Layer

Located in:

app/domain/

Contains:

models.py  
enums.py  
constants.py

Defines:

- field names
- status enums
- parsed result structures

This layer must contain no business logic.

---

# Data Flow

Step 1  
User uploads label image.

Step 2  
Image preprocessing runs.

Step 3  
OCR extracts text and bounding boxes.

Step 4  
Parser extracts structured fields.

Step 5  
Matching logic compares fields with application data.

Step 6  
Results returned to UI.

---

# Response Structure

Example response:

{
  "fields": {
    "brand": "match",
    "abv": "match",
    "net_contents": "normalized_match",
    "warning": "review"
  },
  "overall_status": "review"
}

---

# Deployment Architecture

The application runs as:

Docker container.

Container runs:

Gunicorn  
Uvicorn worker  
FastAPI app.

Deployment target:

Azure App Service Linux container.

---

# Performance Considerations

To achieve ≤5 second runtime:

- reuse OCR model instance
- minimize image resizing
- avoid unnecessary file IO
- keep parsing rule-based

---

# Future Extensions

Possible improvements:

- batch processing queue
- better layout detection
- improved warning validation
- UI highlighting

These should not be implemented in the prototype unless time permits.
