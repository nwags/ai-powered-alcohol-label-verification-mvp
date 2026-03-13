import io
import time
import zipfile
import csv
from io import StringIO

from app.domain.enums import OverallStatus
from app.domain.models import BatchResult
from app.services.batch_service import BatchService


def _build_images_zip_bytes() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label1.jpg", b"fake-image-content")
        archive.writestr("label2.jpg", b"fake-image-content")
    return zip_buffer.getvalue()


def _build_compare_csv_bytes() -> bytes:
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "record_id",
            "image_filename",
            "brand_name",
            "class_type",
            "alcohol_content",
            "net_contents",
            "bottler_producer",
            "country_of_origin",
            "government_warning",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "record_id": "001",
            "image_filename": "label1.jpg",
            "brand_name": "Stone's Throw Whiskey",
            "class_type": "Whiskey",
            "alcohol_content": "45% Alc./Vol.",
            "net_contents": "750 mL",
            "bottler_producer": "Bottled by Example Spirits Co.",
            "country_of_origin": "United States",
            "government_warning": "GOVERNMENT WARNING: SAMPLE",
        }
    )
    return buffer.getvalue().encode("utf-8")


def test_ui_batch_submit_redirects_immediately_to_report_resource(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers.get("location", "")
    assert location.startswith("/ui/batch/batch-")


def test_ui_batch_status_progress_is_monotonic_until_completion(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_id = response.headers["location"].rsplit("/", 1)[-1]

    previous_processed = -1
    completed_payload: dict[str, object] | None = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        status_response = client.get(f"/ui/batch/{batch_id}/status")
        assert status_response.status_code == 200
        payload = status_response.json()
        processed = int(payload.get("processed_records", 0))
        total = int(payload.get("total_records", 0))
        assert processed >= previous_processed
        assert processed <= total
        previous_processed = processed
        if payload.get("status") in {"completed", "failed"}:
            completed_payload = payload
            break
        time.sleep(0.02)

    assert completed_payload is not None
    assert completed_payload["status"] == "completed"
    assert completed_payload["processed_records"] == completed_payload["total_records"]
    assert isinstance(completed_payload.get("rows"), list)
    assert completed_payload.get("completed_at") is not None
    assert completed_payload.get("report_url") == f"/ui/batch/{batch_id}"
    assert isinstance(completed_payload.get("summary"), dict)


def test_ui_batch_compare_mode_enqueues_and_completes(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_compare_application"},
        files={
            "batch_file": ("batch.csv", _build_compare_csv_bytes(), "text/csv"),
            "images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_id = response.headers["location"].rsplit("/", 1)[-1]

    completed_payload: dict[str, object] | None = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        status_response = client.get(f"/ui/batch/{batch_id}/status")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload.get("status") in {"completed", "failed"}:
            completed_payload = payload
            break
        time.sleep(0.02)

    assert completed_payload is not None
    assert completed_payload["status"] == "completed"
    assert completed_payload["batch_review_mode"] == "batch_compare_application"
    assert isinstance(completed_payload.get("rows"), list)


def test_ui_batch_worker_failure_sets_failed_status(client, monkeypatch):
    def _raise_worker_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(BatchService, "_analyze_record", _raise_worker_error)

    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_id = response.headers["location"].rsplit("/", 1)[-1]

    failed_payload: dict[str, object] | None = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        status_response = client.get(f"/ui/batch/{batch_id}/status")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload.get("status") in {"completed", "failed"}:
            failed_payload = payload
            break
        time.sleep(0.02)

    assert failed_payload is not None
    assert failed_payload["status"] == "failed"
    assert failed_payload["completed_at"] is not None
    assert failed_payload["errors"]


def test_ui_batch_report_can_reload_while_job_is_running(client, monkeypatch):
    original_analyze_record = BatchService._analyze_record

    def _slow_analyze(self, *args, **kwargs):
        time.sleep(0.08)
        return original_analyze_record(self, *args, **kwargs)

    monkeypatch.setattr(BatchService, "_analyze_record", _slow_analyze)

    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_id = response.headers["location"].rsplit("/", 1)[-1]

    report = client.get(f"/ui/batch/{batch_id}")
    assert report.status_code == 200
    assert "Batch Summary" in report.text
    assert f"/ui/batch/{batch_id}/status" in report.text

    completed_payload: dict[str, object] | None = None
    deadline = time.time() + 3.0
    while time.time() < deadline:
        status_response = client.get(f"/ui/batch/{batch_id}/status")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload.get("status") in {"completed", "failed"}:
            completed_payload = payload
            break
        time.sleep(0.02)

    assert completed_payload is not None
    assert completed_payload["status"] == "completed"


def test_ui_batch_detail_returns_not_ready_for_incomplete_record(client, monkeypatch):
    def _slow_analyze_record(
        self,
        record,
        row_index,
        images_by_name,
        image_urls,
        ocr_service,
        label_type,
        product_profile,
        evaluation_mode,
    ):
        time.sleep(0.12)
        record_id = str(record.get("record_id") or f"row-{row_index:03d}")
        image_filename = record.get("image_filename")
        result = BatchResult(
            record_id=record_id,
            request_id=f"req-{record_id}",
            overall_status=OverallStatus.REVIEW,
            image_filename=image_filename,
            image_url=image_urls.get(str(image_filename).lower()) if image_filename else None,
            main_reason="Needs review",
            timing_ms=5,
        )
        detail = {
            "record_id": record_id,
            "request_id": f"req-{record_id}",
            "overall_status": "review",
            "image_filename": image_filename,
            "image_url": result.image_url,
            "main_reason": "Needs review",
            "timing_ms": 5,
            "evaluation_mode": evaluation_mode,
            "ocr_full_text": "",
            "field_rows": [],
            "field_results": {},
            "parsed": {},
            "review_reasons": ["Needs review"],
            "ocr_errors": [],
            "application": {},
            "inference": {"product_profile": {}, "label_type": {}},
            "rule_trace": {},
            "annotated_image_url": None,
        }
        return result, detail

    monkeypatch.setattr(BatchService, "_analyze_record", _slow_analyze_record)

    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_id = response.headers["location"].rsplit("/", 1)[-1]

    # img-002 should not be available before the second record is processed.
    not_ready = client.get(f"/ui/batch/{batch_id}/record/img-002")
    assert not_ready.status_code == 409
    assert "not ready" in not_ready.text.lower()
