import csv
import io
import re
import time
import zipfile
from types import SimpleNamespace

import numpy as np

from app.api import routes_batch, routes_ui
from app.dependencies import get_ocr_service
from app.domain.models import OCREvidenceLine, OCRLine, OCRResult
from app.main import app


def _build_images_zip_bytes() -> bytes:
    return _build_images_zip_with_name("label1.jpg")


def _build_images_zip_with_name(filename: str) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, b"fake-image-content")
    return zip_buffer.getvalue()


def _wait_for_batch_completion(client, batch_id: str, timeout_s: float = 2.0) -> dict[str, object]:
    deadline = time.time() + timeout_s
    latest: dict[str, object] = {}
    while time.time() < deadline:
        response = client.get(f"/ui/batch/{batch_id}/status")
        assert response.status_code == 200
        latest = response.json()
        if latest.get("status") in {"completed", "failed"}:
            return latest
        time.sleep(0.02)
    return latest


def test_batch_ui_label_only_mode_accepts_images_zip_only(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only", "label_type": "brand_label", "product_profile": "wine"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    assert "Batch Summary" in response.text
    assert 'name="label_type" value="brand_label" checked' in response.text
    assert 'name="product_profile" value="wine" checked' in response.text


def test_batch_ui_compare_mode_requires_batch_file(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_compare_application"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 422
    assert "Batch file is required in Compare to Application Data mode." in response.text


def test_batch_ui_compare_mode_preserves_existing_compare_flow(client):
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(
        csv_buffer,
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

    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_compare_application"},
        files={
            "batch_file": ("batch.csv", csv_buffer.getvalue().encode("utf-8"), "text/csv"),
            "images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip"),
        },
    )

    assert response.status_code == 200
    assert "Batch Summary" in response.text


def test_batch_ui_returns_404_when_batch_ui_disabled(client, monkeypatch):
    fake_settings = SimpleNamespace(enable_batch_ui=False)
    monkeypatch.setattr(routes_batch, "get_settings", lambda: fake_settings)

    response = client.get("/ui/batch")

    assert response.status_code == 404


def test_index_hides_batch_link_when_batch_ui_disabled(client, monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        enable_batch_ui=False,
        enable_diagnostics_ui=False,
        max_upload_bytes=1024,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_require_local_models=True,
        ocr_model_source="local",
        ocr_model_root=tmp_path / "models" / "paddleocr",
        ocr_det_model_dir=None,
        ocr_rec_model_dir=None,
        ocr_cls_model_dir=None,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        coverage_dir=tmp_path / "runtime" / "coverage",
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)

    response = client.get("/")

    assert response.status_code == 200
    assert "Go To Batch Mode" not in response.text


def test_index_renders_only_allowed_single_label_options(client, monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        enable_batch_ui=True,
        enable_diagnostics_ui=False,
        max_upload_bytes=1024,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_require_local_models=True,
        ocr_model_source="local",
        ocr_model_root=tmp_path / "models" / "paddleocr",
        ocr_det_model_dir=None,
        ocr_rec_model_dir=None,
        ocr_cls_model_dir=None,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        coverage_dir=tmp_path / "runtime" / "coverage",
        allowed_review_modes="label_only",
        allowed_label_types="unknown",
        allowed_product_profiles="unknown,wine",
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)

    response = client.get("/")

    assert response.status_code == 200
    assert "Compare to Application Data" not in response.text
    assert 'name="label_type" value="brand_label"' not in response.text
    assert 'name="label_type" value="other_label"' not in response.text
    assert 'name="product_profile" value="wine"' in response.text
    assert 'name="product_profile" value="distilled_spirits"' not in response.text


def test_batch_ui_renders_only_allowed_options_and_coerces_disallowed_submission(client, monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        enable_batch_ui=True,
        enable_diagnostics_ui=False,
        max_upload_bytes=1024 * 1024,
        storage_dir=tmp_path / "runtime",
        allowed_review_modes="label_only",
        allowed_label_types="unknown",
        allowed_product_profiles="unknown",
    )
    monkeypatch.setattr(routes_batch, "get_settings", lambda: fake_settings)

    get_response = client.get("/ui/batch")
    assert get_response.status_code == 200
    assert "Batch Compare to Application Data" not in get_response.text
    assert 'name="label_type" value="brand_label"' not in get_response.text
    assert 'name="product_profile" value="wine"' not in get_response.text

    post_response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_compare_application", "label_type": "brand_label", "product_profile": "wine"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    location = post_response.headers.get("location", "")
    assert location.startswith("/ui/batch/batch-")

    report_response = client.get(location)
    assert report_response.status_code == 200
    assert 'name="batch_review_mode" value="batch_label_only" checked' in report_response.text
    assert 'name="label_type" value="unknown" checked' in report_response.text
    assert 'name="product_profile" value="unknown" checked' in report_response.text


def test_batch_ui_shows_elapsed_and_processed_metadata(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    batch_id_match = re.search(r"Batch ID:\s*<code>([^<]+)</code>", response.text)
    assert batch_id_match is not None
    batch_id = batch_id_match.group(1)
    status_payload = _wait_for_batch_completion(client, batch_id)
    assert status_payload.get("status") == "completed"

    report = client.get(f"/ui/batch/{batch_id}")
    assert report.status_code == 200
    assert "Batch Summary" in report.text
    assert "Elapsed:" in report.text
    assert "Processed:" in report.text
    assert "Mode:" in report.text
    assert "Overall Result" in report.text
    assert "Internal Status" in report.text
    assert "View" in report.text
    assert "Report URL:" in report.text
    assert 'class="batch-results-table"' in report.text
    assert 'class="col-details"' in report.text
    assert 'class="col-record-id"' in report.text
    assert 'class="col-image"' in report.text
    assert 'class="col-timing"' in report.text
    assert '<span class="th-stack">Timing <span class="th-sub">(ms)</span></span>' in report.text
    assert "batch-thumb" in report.text
    assert "js-lightbox-image" in report.text
    assert 'id="image-lightbox"' in report.text
    assert re.search(r'target="_blank"[^>]*>\s*<img[^>]*batch-thumb', report.text) is None


def test_batch_ui_record_detail_page_loads_from_summary_artifact(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )
    assert response.status_code == 200
    batch_id_match = re.search(r"Batch ID:\s*<code>([^<]+)</code>", response.text)
    assert batch_id_match is not None
    batch_id = batch_id_match.group(1)
    status_payload = _wait_for_batch_completion(client, batch_id)
    assert status_payload.get("status") == "completed"

    detail = client.get(f"/ui/batch/{batch_id}/record/img-001")
    assert detail.status_code == 200
    assert "Batch Record Detail" in detail.text
    assert f'href="/ui/batch/{batch_id}"' in detail.text
    assert "No annotated image available for this run." in detail.text
    assert "/storage/outputs/annotated/" not in detail.text


def test_batch_ui_record_detail_shows_annotated_image_when_canonical_evidence_present(client):
    class CanonicalEvidenceOCRService:
        def run_ocr_bytes(
            self,
            image_bytes: bytes,
            source_label: str = "upload",
            return_variant_image: bool = False,
            return_variant_metadata: bool = False,
        ):
            _ = image_bytes, source_label
            ocr = OCRResult(
                full_text="STONE'S THROW WHISKEY",
                lines=[
                    OCRLine(
                        text="STONE'S THROW WHISKEY",
                        confidence=0.98,
                        bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
                    )
                ],
            )
            evidence = [
                OCREvidenceLine(
                    id="color_resized:line-0001",
                    text="STONE'S THROW WHISKEY",
                    confidence=0.98,
                    bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
                    bbox_space="render_pixels",
                    image_variant_id="color_resized",
                    source_backend="paddleocr",
                ).model_dump()
            ]
            if return_variant_image or return_variant_metadata:
                variant_image = np.zeros((32, 32, 3), dtype=np.uint8)
                return (
                    ocr,
                    [],
                    variant_image,
                    {
                        "source_variant_id": "color_resized",
                        "bbox_space": "render_pixels",
                        "evidence_lines": evidence,
                    },
                )
            return ocr, []

    previous_override = app.dependency_overrides.get(get_ocr_service)
    app.dependency_overrides[get_ocr_service] = lambda: CanonicalEvidenceOCRService()
    try:
        response = client.post(
            "/ui/batch",
            data={"batch_review_mode": "batch_label_only"},
            files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        )
        assert response.status_code == 200
        batch_id_match = re.search(r"Batch ID:\s*<code>([^<]+)</code>", response.text)
        assert batch_id_match is not None
        batch_id = batch_id_match.group(1)
        status_payload = _wait_for_batch_completion(client, batch_id)
        assert status_payload.get("status") == "completed"

        detail = client.get(f"/ui/batch/{batch_id}/record/img-001")
        assert detail.status_code == 200
        assert "Annotated OCR Evidence" in detail.text
        assert "/storage/outputs/annotated/" in detail.text
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_ocr_service, None)
        else:
            app.dependency_overrides[get_ocr_service] = previous_override


def test_batch_report_route_loads_persisted_summary(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )
    assert response.status_code == 200
    batch_id_match = re.search(r"Batch ID:\s*<code>([^<]+)</code>", response.text)
    assert batch_id_match is not None
    batch_id = batch_id_match.group(1)
    status_payload = _wait_for_batch_completion(client, batch_id)
    assert status_payload.get("status") == "completed"

    report = client.get(f"/ui/batch/{batch_id}")
    assert report.status_code == 200
    assert f"/ui/batch/{batch_id}" in report.text
    assert "Batch Summary" in report.text


def test_batch_ui_tiff_rows_show_preview_unavailable_with_open_file_link(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_with_name("label1.tiff"), "application/zip")},
    )
    assert response.status_code == 200
    batch_id_match = re.search(r"Batch ID:\s*<code>([^<]+)</code>", response.text)
    assert batch_id_match is not None
    batch_id = batch_id_match.group(1)
    status_payload = _wait_for_batch_completion(client, batch_id)
    assert status_payload.get("status") == "completed"

    report = client.get(f"/ui/batch/{batch_id}")
    assert report.status_code == 200
    assert "Preview unavailable" in report.text
    assert "Open File" in report.text
    assert "TIFF" in report.text
    assert "js-lightbox-image" not in report.text


def test_batch_page_contains_running_state_markup(client):
    response = client.get("/ui/batch")

    assert response.status_code == 200
    assert 'id="batch-review-form"' in response.text
    assert 'id="batch-submit-btn"' in response.text
    assert 'id="batch-running-state"' in response.text


def test_batch_status_endpoint_returns_progress_fields(client):
    post_response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
        follow_redirects=False,
    )
    assert post_response.status_code == 303
    location = post_response.headers.get("location", "")
    batch_id = location.rsplit("/", 1)[-1]
    status_response = client.get(f"/ui/batch/{batch_id}/status")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["batch_id"] == batch_id
    assert payload["status"] in {"queued", "running", "completed", "failed"}
    assert "total_records" in payload
    assert "processed_records" in payload
    assert "summary" in payload
    assert "rows" in payload
