# Tradeoffs and Demo Risks

This document captures practical engineering tradeoffs from the 3-day prototype sprint and the top demo risks to watch during handoff.

## Sprint Tradeoffs

1. In-process batch mode over background jobs.
Reason: fastest path to demo with minimal infrastructure.
Tradeoff: large batches can block requests.

2. Rule-based parsing/matching over advanced ML.
Reason: deterministic behavior, easy debugging, no external dependencies.
Tradeoff: lower recall on noisy/complex labels.

3. Conservative `review` defaults over aggressive auto-decisions.
Reason: human-review principle and safer compliance posture.
Tradeoff: more manual follow-up in borderline cases.

4. Local file artifacts under `STORAGE_DIR`.
Reason: simple demo artifact retrieval.
Tradeoff: lifecycle cleanup is not automated yet.

## Top 10 Demo Risks (and Status)

1. Malformed batch JSON causes 500.
Status: Mitigated in code.
Mitigation: batch parser now catches JSON decode failures and returns safe request errors.

2. Invalid ZIP upload causes 500.
Status: Mitigated in code.
Mitigation: ZIP parsing now catches `BadZipFile` and returns safe request errors.

3. Oversized uploads can crash or stall the app.
Status: Mitigated in code.
Mitigation: env-driven size limits added (`MAX_UPLOAD_BYTES`) and enforced in analyze/batch routes.

4. Huge batch record sets can exceed demo time budget.
Status: Mitigated in code.
Mitigation: env-driven record/image caps (`BATCH_MAX_RECORDS`, `BATCH_MAX_IMAGES`) enforced in batch service.

5. Storage static mount may fail if directory missing.
Status: Mitigated in code.
Mitigation: storage directory is created before static mount.

6. Internal parser/matcher exceptions can produce 500 during demos.
Status: Mitigated in code.
Mitigation: defensive fallback path now returns `review` results instead of crashing.

7. OCR cold start latency may delay first request.
Status: Accepted.
Mitigation: keep model singleton and include `/readyz`; pre-hit endpoints before demo.

8. Warning statement OCR quality can be weak on poor scans.
Status: Accepted.
Mitigation: strict warning logic prefers `review` to avoid false certainty.

9. No background retries for batch processing.
Status: Accepted.
Mitigation: keep batch sizes small for demos and rerun failed rows quickly.

10. Artifact files can accumulate over repeated runs.
Status: Partially mitigated.
Mitigation: deterministic output structure exists; cleanup policy still manual for MVP.
