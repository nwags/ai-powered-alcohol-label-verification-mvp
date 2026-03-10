# AGENTS.md

This file defines how AI coding agents (including OpenAI Codex) should work
within this repository.

Agents must read the following files BEFORE making changes:

- docs/project_scope.md
- docs/ttb_rules_distilled_spirits.md
- docs/acceptance_criteria.md
- docs/architecture.md

The goal of this repository is to implement a 3-day prototype for an
AI-assisted alcohol label verification tool.

The system extracts text from alcohol labels and compares it with
application data to assist a human reviewer.

The system DOES NOT replace human judgment.

---

# Core Development Rules

## 1. Incremental Changes Only

Changes must be small and reviewable.

Avoid large rewrites.

The application must remain runnable after each change.

---

## 2. Simplicity Over Complexity

Prefer:

- simple Python implementations
- minimal dependencies
- deterministic rule systems
- readable code

Avoid:

- heavy ML pipelines
- complex microservices
- unnecessary frameworks

This is a prototype, not a production system.

---

## 3. Local-First Processing

All OCR and processing must run locally inside the container.

Do NOT call:

- OpenAI APIs
- external OCR services
- cloud AI services

The prototype must work without internet access.

---

## 4. Architecture Constraints

The system must remain a single service:

FastAPI + PaddleOCR.

Structure:

FastAPI API  
→ Services  
→ Domain Logic

Do not introduce queues or multiple services.

---

## 5. Configuration

Configuration must be environment driven.

Use:

app/config.py  
.env

Never hardcode secrets or environment values.

---

## 6. File Change Protocol

Before making changes:

1. List files to be changed
2. Explain why
3. Implement changes
4. Summarize results

---

## 7. Error Handling

Failures must return safe results.

If OCR or parsing fails:

status = "review"

Never crash the API for normal user input.

---

## 8. Human Review Principle

The system assists reviewers.

When uncertain:

status = "review"

Never claim certainty when rules cannot determine correctness.

---

## 9. Performance Goal

Target runtime per label:

≤ 5 seconds

Avoid expensive operations.

---

## 10. Testing

Tests belong in:

tests/

Focus on:

- parsing logic
- matching rules
- warning detection

---

# Authoritative Documents

These documents define the project requirements:

- docs/project_scope.md
- docs/ttb_rules_distilled_spirits.md
- docs/acceptance_criteria.md

If conflicts occur, these documents override assumptions.

---

# Development Workflow

Agents should implement features in this order:

1. API scaffold
2. OCR extraction
3. Field parsing
4. Matching logic
5. Warning validation
6. UI display
7. Batch processing
8. Deployment readiness

---

# Deployment Model

The application must run in Docker and be deployable to:

Azure App Service (Linux container).

Local development must NOT require Azure.
