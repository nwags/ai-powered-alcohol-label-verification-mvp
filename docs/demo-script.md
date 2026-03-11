# 5-Minute Demo Script

This script is designed for a quick, realistic walkthrough after startup.

## 0:00-0:45 Startup

1. Start the app:
```bash
docker compose up --build
```
2. Confirm health:
```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/readyz
```

## 0:45-2:30 Single Label Workflow

1. Open `http://localhost:8000`.
2. Upload an image from:
   `data/sample_inputs/labels/01_clean_passing/label_clean_passing.jpg`
3. Paste JSON from:
   `data/sample_inputs/applications/01_clean_passing.json`
4. Click **Analyze Label**.
5. Show result page sections:
   - uploaded image
   - extracted OCR text
   - field comparison table with status badges
   - overall recommendation and timing

## 2:30-3:45 Edge Case Examples

1. Repeat with:
   - `data/sample_inputs/applications/02_normalized_brand_match.json`
   - Expected: `normalized_match` behavior for brand formatting differences.
2. Repeat with:
   - `data/sample_inputs/applications/03_warning_statement_issue.json`
   - Expected: warning-related `review`/mismatch emphasis.

## 3:45-4:45 Batch Workflow

1. Open `http://localhost:8000/ui/batch`.
2. Upload a CSV/JSON batch file and image ZIP.
3. Run analysis and show:
   - summary counts
   - per-record table (record id, filename, overall status, reason, timing)
   - downloadable JSON/CSV summary artifacts

## 4:45-5:00 Close

Call out prototype boundaries:
- assists reviewers, does not auto-approve labels
- local OCR and deterministic matching
- ambiguous cases return `review`
