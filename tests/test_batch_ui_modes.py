import csv
import io
import re
import zipfile
from types import SimpleNamespace

from app.api import routes_batch, routes_ui


def _build_images_zip_bytes() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label1.jpg", b"fake-image-content")
    return zip_buffer.getvalue()


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
        max_upload_bytes=1024 * 1024,
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
    )
    assert post_response.status_code == 200
    assert 'name="batch_review_mode" value="batch_label_only" checked' in post_response.text
    assert 'name="label_type" value="unknown" checked' in post_response.text
    assert 'name="product_profile" value="unknown" checked' in post_response.text


def test_batch_ui_shows_elapsed_and_processed_metadata(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    assert "Batch Summary" in response.text
    assert "Elapsed:" in response.text
    assert "Processed:" in response.text
    assert "Mode:" in response.text
    assert "Overall Result" in response.text
    assert "Internal Status" in response.text
    assert "View" in response.text


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

    detail = client.get(f"/ui/batch/{batch_id}/record/img-001")
    assert detail.status_code == 200
    assert "Batch Record Detail" in detail.text
    assert "Back to Batch Report" in detail.text
