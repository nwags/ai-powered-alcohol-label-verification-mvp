#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
IMAGE_PATH="${IMAGE_PATH:-data/sample_inputs/labels/01_clean_passing/label_clean_passing.jpg}"
APP_JSON_PATH="${APP_JSON_PATH:-data/sample_inputs/applications/01_clean_passing.json}"

if [[ ! -f "${IMAGE_PATH}" ]]; then
  echo "Missing image file: ${IMAGE_PATH}" >&2
  echo "Add a demo image to the placeholder directory before running smoke test." >&2
  exit 1
fi

if [[ ! -f "${APP_JSON_PATH}" ]]; then
  echo "Missing application JSON file: ${APP_JSON_PATH}" >&2
  exit 1
fi

APP_JSON_COMPACT="$(tr -d '\n' < "${APP_JSON_PATH}")"

echo "Checking health endpoints..."
curl -fsS "${BASE_URL}/healthz" >/dev/null
curl -fsS "${BASE_URL}/readyz" >/dev/null
echo "Health checks passed."

echo "Running analyze smoke test..."
RESPONSE="$(curl -fsS -X POST "${BASE_URL}/api/v1/analyze" \
  -F "image=@${IMAGE_PATH}" \
  -F "application_json=${APP_JSON_COMPACT}")"

echo "Analyze response (truncated):"
echo "${RESPONSE}" | cut -c1-600

echo
echo "Smoke test completed."
