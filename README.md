# AI-Powered Alcohol Label Verification

Time-boxed prototype for assisting human reviewers with alcohol label checks.

## What this prototype does and does not do

What it does:
- Extracts label text locally with OCR.
- Parses key fields and compares against submitted application data.
- Surfaces field-level statuses and review reasons for a human reviewer.
- Supports single-label and MVP batch workflows.

What it does not do:
- It does not auto-approve or replace reviewer judgment.
- It does not implement full legal/compliance interpretation.
- It does not use external/cloud AI services in the core pipeline.
- It is not optimized for high-throughput production scale.

## Stack

- FastAPI
- Jinja2
- PaddleOCR (not wired yet in this scaffold step)
- OpenCV
- SQLite
- Docker

## Run Locally (Docker)

```bash
docker compose up --build
```

App will be available at `http://localhost:8000`.

## Run Locally (Without Compose)

```bash
docker build -t alcohol-label-verifier .
docker run --rm -p 8000:8000 \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -e APP_ENV=development \
  -e STORAGE_DIR=/app/runtime \
  -e SAMPLE_DATA_DIR=/app/data \
  -v "$(pwd)/data:/app/data" \
  alcohol-label-verifier
```

## Key Endpoints

- `GET /` reviewer UI
- `GET /healthz`
- `GET /readyz`
- `POST /api/v1/analyze`
- `POST /api/v1/batch/analyze`

## Example Analyze Request

```bash
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -F "image=@data/samples/label.jpg" \
  -F 'application_json={"brand_name":"Example","class_type":"Whiskey","alcohol_content":"45% Alc./Vol.","net_contents":"750 mL","bottler_producer":"Bottled by Example","country_of_origin":"United States","government_warning":"GOVERNMENT WARNING: ..."}'
```

Current behavior runs local OCR and returns field-level match outcomes with conservative `review` behavior for uncertain detections.

## OCR Smoke Test

If the app is running and you have demo sample files in `data/sample_inputs/...`, run:

```bash
bash scripts/smoke_test.sh
```

Optional env overrides:
- `IMAGE_PATH=/path/to/label.jpg`
- `APP_JSON_PATH=/path/to/application.json`
- `BASE_URL=http://localhost:8000`
- `ENABLE_DIAGNOSTICS_UI=true` (enables developer-only `/ui/diagnostics`)

## Coverage Workflow (Developer)

Generate latest coverage artifacts without running tests on each diagnostics request:

```bash
make coverage
```

This writes:
- terminal coverage summary in command output
- HTML report at `runtime/coverage/html/index.html`
- JSON summary at `runtime/coverage/coverage.json`

When diagnostics UI is enabled, `/ui/diagnostics` shows the latest known coverage summary if the JSON artifact exists.

## UI Demo Flow

1. Open `http://localhost:8000`.
2. Upload one label image.
3. Keep default **Label-Only Review** for fast screening, or switch to **Compare to Application Data**.
4. In Compare mode, enter fields or paste `application_json`.
5. Click **Analyze Label**.
6. Review the result page:
   uploaded image, OCR text, side-by-side field table, status badges, timing, and overall recommendation.

Batch modes on `/ui/batch`:
- **Batch Label-Only Review** (default): upload an images ZIP to screen many labels without application records.
- **Batch Compare to Application Data**: upload CSV/JSON plus matching images ZIP for side-by-side validation.

## Demo Assets

Application JSON samples:
- `data/sample_inputs/applications/01_clean_passing.json`
- `data/sample_inputs/applications/02_normalized_brand_match.json`
- `data/sample_inputs/applications/03_warning_statement_issue.json`

Batch data samples:
- `data/sample_inputs/batches/demo_batch.csv`
- `data/sample_inputs/batches/demo_batch.json`

Placeholder image structure:
- `data/sample_inputs/labels/01_clean_passing/`
- `data/sample_inputs/labels/02_normalized_brand_match/`
- `data/sample_inputs/labels/03_warning_statement_issue/`

## Screenshots (Placeholders)

- `docs/screenshots/01-upload-form.png` (to be added)
- `docs/screenshots/02-result-summary.png` (to be added)
- `docs/screenshots/03-field-comparison-table.png` (to be added)

## Azure App Service Deployment

This repository is ready for Azure App Service custom Linux containers.

Key deployment points:
- Container listens on `0.0.0.0:8000`.
- Set `WEBSITES_PORT=8000` in App Service.
- Set health check path to `/healthz`.

Practical deployment guide and CLI examples:
- [infra/azure/appservice.md](infra/azure/appservice.md)
