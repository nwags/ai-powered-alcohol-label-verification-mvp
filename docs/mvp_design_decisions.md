# MVP Design Decisions

This document summarizes why the MVP is structured the way it is and how those choices map to the assignment constraints.

## 1) Reviewer Assistant, Not Auto-Approver

The app is intentionally designed as a reviewer-assistance tool. It highlights likely matches/mismatches and uncertain fields, but it does not issue final approval decisions. This matches the stated human-review context and reduces risk from overconfident automation.

## 2) OCR-First Approach and PaddleOCR Selection

OCR is the core enabling capability for label review assistance. PaddleOCR was selected to keep inference local, avoid reliance on external AI endpoints, and support the MVP local-first constraint. This also supports environments with constrained outbound network access.

## 3) Single-Label Flow First

The single-label flow was prioritized because it is the shortest path to proving core value:

- upload a label,
- extract text,
- parse and compare key fields,
- produce reviewer-readable results.

This made it possible to stabilize result semantics before scaling to batch behavior.

## 4) Batch Flow Added as Report-First Async UI

Batch was introduced after single-flow stabilization. The UI batch path was then evolved to async report-first behavior so users can submit and observe progress at a stable report URL. This improves usability during larger runs while preserving clear report/detail resources.

## 5) Two Operating Contexts

The MVP supports two complementary contexts:

- **Reviewer-oriented operation**: single and batch UI for day-to-day review support.
- **Developer/benchmark operation**: controlled data curation and repeatable OCR experiments.

Keeping both contexts explicit avoids mixing benchmarking concerns into reviewer workflows.

## 6) Product Type and Label Type as Category Axes

`Product Type` and `Label Type` are used as primary benchmark slicing dimensions because OCR and field-extraction behavior is not uniform across label categories. Category-level analysis helps prioritize meaningful OCR improvements.

## 7) Modular OCR Boundary

OCR internals were separated behind a backend boundary and normalized evidence models. This keeps the current Paddle path stable while reducing coupling and making future backend experimentation less disruptive.

## 8) Traceable Rules, Not Full COLA Recreation

The MVP rule structure supports field-level rationale and traceability, but it is intentionally not a full legal/compliance engine. This keeps scope realistic for a prototype and maintains the conservative “review when uncertain” stance.

## 9) Local-First Runtime + Docker + Azure Portability

The project emphasizes:

- local execution,
- containerized reproducibility,
- practical path to Azure App Service Linux container deployment.

This satisfies prototype constraints while keeping deployment options open.

## 10) COLA Utilities and Benchmark Packs as Improvement Infrastructure

`scripts/cola_registry_scraper.py` and `scripts/cola_batch_builder.py` provide a repeatable path from raw data collection to benchmark-pack generation. Combined with experiment logs, this creates a disciplined OCR-improvement loop beyond one-off manual testing.

## 11) Real Accepted Labels Before Synthetic Data

At this stage of the MVP, synthetic data generation was not treated as a priority because there is already enough useful signal available from existing accepted alcohol labels. Real accepted labels provide immediate value for:

- OCR benchmarking on authentic label layouts,
- category-sliced evaluation by Product Type and Label Type,
- identifying practical parsing and rule-trace weaknesses,
- improving the app against realistic data before adding synthetic complexity.

The existing accepted-label corpus is also flexible enough to support negative and stress testing. Labels can be intentionally mixed across categories or paired against incorrect application data to evaluate mismatch detection and conservative review behavior without needing a synthetic data pipeline first.

Synthetic or augmented data may still become useful later, especially for rare edge cases or controlled error injection, but it is not necessary to establish a strong MVP evaluation loop.
