from types import SimpleNamespace

from app.dependencies import get_ocr_service
from app.domain.models import OCREvidenceLine, OCRLine, OCRResult
from app.main import app
from app.api import routes_ui
from conftest import build_test_image_bytes


def test_ui_label_only_uses_mode_aware_field_rationales_and_shows_annotation(client):
    class CanonicalEvidenceOCRService:
        def get_status(self) -> dict[str, object]:
            return {"state": "ready", "ready": True, "error": None}

        def run_ocr_bytes(
            self,
            image_bytes: bytes,
            source_label: str = "upload",
            return_variant_image: bool = False,
            return_variant_metadata: bool = False,
        ):
            _ = image_bytes, source_label
            ocr = OCRResult(
                full_text="STONE'S THROW WHISKEY\n45% Alc./Vol.",
                lines=[
                    OCRLine(
                        text="STONE'S THROW WHISKEY",
                        confidence=0.99,
                        bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
                    )
                ],
            )
            evidence = [
                OCREvidenceLine(
                    id="color_resized:line-0001",
                    text="STONE'S THROW WHISKEY",
                    confidence=0.99,
                    bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
                    bbox_space="render_pixels",
                    image_variant_id="color_resized",
                    source_backend="paddleocr",
                ).model_dump()
            ]
            if return_variant_image or return_variant_metadata:
                return (
                    ocr,
                    [],
                    None,
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
            "/ui/analyze",
            data={"review_mode": "label_only", "label_type": "unknown"},
            files={"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")},
        )
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_ocr_service, None)
        else:
            app.dependency_overrides[get_ocr_service] = previous_override

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
    assert "[INF-" in response.text or "[WARN-" in response.text or "[PARSE-" in response.text
    assert "<th>Submitted</th>" not in response.text
    assert "Annotation Debug Metadata" in response.text


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


def test_ui_compare_mode_shows_submitted_column(client):
    response = client.post(
        "/ui/analyze",
        data={
            "review_mode": "compare_application",
            "application_json": "{\"brand_name\":\"Stone's Throw\"}",
        },
        files={"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert "<th>Submitted</th>" in response.text
