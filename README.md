# AI-Powered Alcohol Label Verification (MVP)

AI-assisted alcohol label review prototype for human reviewers.

This MVP extracts label text locally, parses key fields, compares against submitted application data (when provided), and presents conservative reviewer guidance. It is designed to help reviewers work faster, not replace reviewer judgment.

## What This MVP Does

- Runs OCR locally with PaddleOCR (no cloud OCR/API calls in the core path).
- Supports **Single Label Review** for rapid per-label analysis.
- Supports **Batch Label Review** with a report-first async UI workflow.
- Returns field-level outcomes (`match`, `normalized_match`, `mismatch`, `review`) and a conservative overall recommendation.
- Preserves canonical result/detail URLs for batch reports.

## What This MVP Does Not Do

- Does not auto-approve labels or make final compliance decisions.
- Does not implement full legal/compliance adjudication.
- Does not target production-scale distributed processing in this phase.
- Does not claim formal legal/procurement/security/accessibility certification.

## Architecture Snapshot

- **Single service** FastAPI application.
- **Thin routes** in API/UI layers.
- Business logic in services/domain modules.
- Local-first OCR pipeline with PaddleOCR.
- Rule-traceable, deterministic reviewer assistance with human-review-first fallbacks.

See canonical architecture docs:
- [docs/architecture.md](docs/architecture.md)
- [docs/api_contract.md](docs/api_contract.md)
- [docs/data_models.md](docs/data_models.md)

## Quick Start (Docker)

```bash
docker compose up --build
```

Open:
- `http://localhost:8000/` (single review)
- `http://localhost:8000/ui/batch` (batch review)

Health checks:

```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/readyz
```

## Main Workflows

### Single Label Review

1. Upload one label image on `/`.
2. Choose mode:
   - **Label-Only Review** (no application fields required), or
   - **Compare to Application Data** (submitted fields/JSON).
3. Analyze and review:
   - result badge,
   - field rows with rationales,
   - OCR text,
   - uploaded image and annotated OCR evidence (when canonical evidence is available).

### Batch Label Review

1. Open `/ui/batch`.
2. Choose mode:
   - **Batch Label-Only Review**: images ZIP only.
   - **Batch Compare to Application Data**: compare CSV/JSON + images ZIP.
3. Submit batch and land on persisted report URL (`/ui/batch/{batch_id}`).
4. Monitor queued/running/completed/failed status and drill into record detail pages.

## Reviewer Use vs Developer Benchmark Use

- **Reviewer-facing use**: single and batch UI workflows for label assessment support.
- **Developer/benchmark use**: scrape COLA records, build benchmark packs, run repeatable OCR experiments.

## Repository Layout

- `data/cola_raw/...` — raw COLA scrape outputs.
- `cola_batches/benchmark_v1/...` — benchmark pack artifacts.
- `experiments/...` — experiment runs/logs/results.
- `scripts/` — utility tooling (`cola_registry_scraper.py`, `cola_batch_builder.py`, etc.).

## Deeper Documentation

- [Benchmark Pack Spec](docs/benchmark_pack_spec.md)
- [Experiment Log Spec](docs/experiment_log_spec.md)
- [Developer Data + Experiment Workflow](docs/developer_data_and_experiment_workflow.md)
- [MVP Design Decisions](docs/mvp_design_decisions.md)
- [Requirements Traceability](docs/requirements_traceability.md)
- [Azure Deployment (Canonical)](docs/deployment_azure.md)
- [Policy Alignment Notes (Cautious)](docs/policy_alignment_notes.md)
- [Acceptance Criteria](docs/acceptance_criteria.md)
- [Project Scope](docs/project_scope.md)
- [Rule Registry](docs/rule_registry.md)

## Current Limitations and Next-Step Areas

- OCR quality can vary by image quality, typography, and label complexity.
- Some ambiguous results are intentionally surfaced as `review`.
- Async UI batch execution is local/in-process MVP groundwork, not a production-grade distributed worker model.
- Additional OCR/backend tuning is expected via benchmark-pack experiment loops.
