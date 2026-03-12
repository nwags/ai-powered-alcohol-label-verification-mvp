from types import SimpleNamespace

from app.api import routes_ui
from conftest import build_test_image_bytes


def test_ui_label_only_uses_mode_aware_field_rationales_and_shows_annotation(client):
    response = client.post(
        "/ui/analyze",
        data={"review_mode": "label_only", "label_type": "unknown"},
        files={"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert "Analysis Result" in response.text
    assert "missing submitted or OCR value" not in response.text
    assert "Why This Result" in response.text
    assert "Product Profile:" in response.text
    assert "Evidence Confidence:" in response.text
    assert "Rule Scope" in response.text
    assert "badge-confidence-" in response.text
    assert "Annotated OCR Evidence" in response.text
    assert "/storage/outputs/annotated/" in response.text
    assert "Uploaded file:" in response.text
    assert "label.jpg" in response.text
    assert 'id="image-lightbox"' in response.text
    assert "[rules:" in response.text


def test_ui_analyze_coerces_disallowed_options_to_safe_defaults(client, monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        enable_batch_ui=True,
        enable_diagnostics_ui=False,
        max_upload_bytes=1024 * 1024,
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
        allowed_product_profiles="unknown",
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)

    response = client.post(
        "/ui/analyze",
        data={"review_mode": "compare_application", "label_type": "brand_label", "product_profile": "wine"},
        files={"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert "Label-Only Review: overall" in response.text
