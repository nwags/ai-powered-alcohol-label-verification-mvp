# Project Scope

## Overview

This project builds a prototype AI-assisted alcohol label verification tool.

The system extracts text from label images and compares it with application
data to help reviewers detect mismatches.

The system assists human reviewers and does not make final approval decisions.

---

# Problem

Reviewers must manually compare label artwork against submitted application data.

This typically takes:

5–10 minutes per label.

The prototype should reduce this time by automatically highlighting likely
matches and mismatches.

---

# Target Users

Government label reviewers.

Users range from non-technical to moderately technical.

The interface must therefore be extremely simple.

---

# Core Workflow

User uploads:

- label image
- structured application fields

The system:

1. extracts text from the image
2. parses relevant fields
3. compares parsed values with application data
4. displays results

For batch workflows in this MVP phase, the UX is report-first:

- submit batch and enqueue background processing
- land on a persisted batch report URL immediately
- observe queued/running/completed/failed status with progressive report updates
- drill into per-record details and return to the same report
- persist report/detail artifacts as stable resources under the batch ID

---

# Required Fields

The prototype must verify the following:

- Brand Name
- Class / Type
- Alcohol Content
- Net Contents
- Bottler / Producer
- Country of Origin (imports)
- Government Warning Statement

These seven fields are shared across single-label compare mode and batch compare mode.

---

# System Output

Each field returns a status:

match  
normalized_match  
mismatch  
review

Results also include:

- extracted text
- parsed values
- overall recommendation

---

# Non-Goals

The prototype will NOT:

- integrate with existing government systems
- automatically approve labels
- implement advanced machine learning models
- perform full regulatory compliance checks

---

# Constraints

The prototype must:

- run locally
- run in Docker
- avoid external AI APIs
- be deployable to Azure App Service

---

# Performance Goal

Processing time per label:

≤ 5 seconds

Batch mode should support multiple labels.

---

# Technology Stack

Backend:

Python  
FastAPI

OCR:

PaddleOCR

Image preprocessing:

OpenCV

Deployment:

Docker  
Azure App Service

---

# Success Criteria

The prototype successfully demonstrates:

1. OCR extraction from label images
2. parsing of required fields
3. automated comparison against application data
4. clear result display
