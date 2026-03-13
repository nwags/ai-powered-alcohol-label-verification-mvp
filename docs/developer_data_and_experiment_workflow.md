# Developer Data and Experiment Workflow

This guide describes a practical OCR-improvement workflow using:

- `scripts/cola_registry_scraper.py`
- `scripts/cola_batch_builder.py`
- `docs/benchmark_pack_spec.md`
- `docs/experiment_log_spec.md`

Use this flow for repeatable benchmarking and controlled OCR tuning.

## 1. Scrape Raw COLA Data

Run the scraper to collect public COLA details and images.

```bash
python scripts/cola_registry_scraper.py --date-from 03/01/2026 --date-to 03/13/2026
```

Default output root is repo-relative:

- `data/cola_raw/<YYYYMMDD>_run/`

Typical structure:

- `html/`
- `text/`
- `json/records.jsonl`
- `json/taxonomy.json`
- `json/summary.json`
- `images/`

You can override output explicitly:

```bash
python scripts/cola_registry_scraper.py --out-dir data/cola_raw/custom_run
```

## 2. Build Benchmark Pack Artifacts

Convert raw scrape output into benchmark-pack format.

```bash
python scripts/cola_batch_builder.py --input-root data/cola_raw/20260313_run
```

Default benchmark output root:

- `cola_batches/benchmark_v1/`

Per `docs/benchmark_pack_spec.md`, this emits top-level metadata/index and per-batch directories with:

- images ZIP
- manifest JSON
- compare CSV/JSON in compare mode

### Compare vs Label-Only

Compare mode (default):

```bash
python scripts/cola_batch_builder.py \
  --input-root data/cola_raw/20260313_run \
  --mode compare
```

Label-only mode:

```bash
python scripts/cola_batch_builder.py \
  --input-root data/cola_raw/20260313_run \
  --mode label-only
```

Notes:

- In label-only mode, compare files are not emitted by default.
- Use `--emit-compare-in-label-only` only when explicitly needed and fields are available.

### Category Slicing

Slice by canonical axes:

- Product Type: `Beer`, `Wine`, `Distilled` (plus `Unknown` as needed)
- Label Type: `Brand`, `Back`, `Other` (optional `Signatures` include flag)

Examples:

```bash
python scripts/cola_batch_builder.py \
  --input-root data/cola_raw/20260313_run \
  --product-types Wine,Distilled \
  --label-types Back,Brand \
  --batch-size 50
```

Include signatures explicitly:

```bash
python scripts/cola_batch_builder.py \
  --input-root data/cola_raw/20260313_run \
  --include-signatures
```

## 3. Run App Evaluations

### Reviewer-oriented UI checks

- Single review: `http://localhost:8000/`
- Batch review: `http://localhost:8000/ui/batch`

### Benchmark-oriented runs

Use benchmark-pack artifacts as batch inputs:

- compare mode: per-batch `.csv` or `.json` + images ZIP
- label-only mode: images ZIP (manifest used for provenance/analysis)

## 4. Log Experiments

Use `docs/experiment_log_spec.md` as the required run log structure.

Recommended layout:

- `experiments/ocr_benchmark_v1/pack/`
- `experiments/ocr_benchmark_v1/runs/<run_id>/`

For each run, capture:

- `run_config.json`
- `run_summary.json`
- `notes.md`
- `outputs/` (copied summaries/manifests)

## 5. Recommended PaddleOCR Iteration Loop

1. Freeze a benchmark pack version.
2. Run a baseline and log it.
3. Classify failures by category and failure mode.
4. Change one variable at a time (model/preprocessing/config).
5. Re-run the same batch set.
6. Compare aggregate and category-sliced results.
7. Keep uncertain cases conservative (`review`) and document trade-offs.

## 6. Practical Tips

- Keep benchmark packs immutable once used for comparisons.
- Prefer deterministic sampling and explicit seeds for repeatability.
- Track app commit/version in experiment logs.
- Distinguish reviewer UX improvements from OCR-core changes in notes.

