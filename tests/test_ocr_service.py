import numpy as np

from conftest import build_test_image_bytes

from app.services.image_preprocess import ImageVariant
from app.services.ocr_backends.paddle_backend import (
    PaddleOCRBackend,
    build_paddleocr_kwargs,
    build_paddleocr_runtime_kwargs,
)
from app.services.ocr_backends.types import OCREvidenceLinePayload, OCRExtraction
from app.services.ocr_service import OCRService


class FakeBackend:
    def __init__(self) -> None:
        self._ready = True
        self.calls: list[str] = []

    def warmup(self) -> None:
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    def get_status(self) -> dict[str, object]:
        return {
            "state": "ready",
            "ready": self._ready,
            "error": None,
            "model_assets_ready": True,
            "model_assets_missing": [],
            "source_backend": "fake",
        }

    def extract(self, image: np.ndarray, source_label: str, image_variant_id: str) -> OCRExtraction:
        _ = image, source_label
        self.calls.append(image_variant_id)
        if image_variant_id == "color_resized":
            return OCRExtraction(
                full_text="SHORT",
                lines=[
                    OCREvidenceLinePayload(
                        id=f"{image_variant_id}:line-0001",
                        text="SHORT",
                        confidence=0.4,
                        bbox=[[0, 0], [10, 0], [10, 10], [0, 10]],
                        bbox_space="render_pixels",
                        image_variant_id=image_variant_id,
                        source_backend="fake",
                    )
                ],
                errors=[],
            )
        return OCRExtraction(
            full_text="LONGER TEXT\nANOTHER LINE",
            lines=[
                OCREvidenceLinePayload(
                    id=f"{image_variant_id}:line-0001",
                    text="LONGER TEXT",
                    confidence=0.90,
                    bbox=[[0, 0], [10, 0], [10, 10], [0, 10]],
                    bbox_space="render_pixels",
                    image_variant_id=image_variant_id,
                    source_backend="fake",
                ),
                OCREvidenceLinePayload(
                    id=f"{image_variant_id}:line-0002",
                    text="ANOTHER LINE",
                    confidence=0.92,
                    bbox=[[0, 12], [10, 12], [10, 22], [0, 22]],
                    bbox_space="render_pixels",
                    image_variant_id=image_variant_id,
                    source_backend="fake",
                ),
            ],
            errors=[],
        )


def test_run_ocr_bytes_invalid_image_returns_error():
    service = OCRService(enabled=True, require_local_models=False, backend=FakeBackend())
    result, errors = service.run_ocr_bytes(b"not-an-image")
    assert result.full_text == ""
    assert errors
    assert errors[0].startswith("invalid_image:")


def test_variant_selection_uses_first_variant_in_mvp_color_only_mode(monkeypatch):
    service = OCRService(enabled=True, require_local_models=False, backend=FakeBackend())

    variants = [
        ImageVariant(name="color_resized", image=np.zeros((10, 10, 3), dtype=np.uint8)),
        ImageVariant(name="gray_clean_bgr", image=np.zeros((10, 10, 3), dtype=np.uint8)),
    ]

    def fake_build_variants(*args, **kwargs):
        _ = args, kwargs
        return variants

    monkeypatch.setattr("app.services.ocr_service.build_ocr_variants", fake_build_variants)

    result, errors, selected_variant, selected_variant_image, selected_evidence = service._run_ocr_for_image(
        np.zeros((10, 10, 3), dtype=np.uint8),
        "test",
    )
    assert not errors
    assert selected_variant == "color_resized"
    assert result.full_text == "SHORT"
    assert selected_variant_image is not None
    assert len(selected_evidence) == 1
    assert selected_evidence[0].source_backend == "fake"


def test_build_paddleocr_kwargs_prefers_device_for_cpu():
    def fake_ctor(*, device, lang, show_log, use_angle_cls):
        _ = device, lang, show_log, use_angle_cls

    kwargs = build_paddleocr_kwargs(
        fake_ctor,
        use_gpu=False,
        model_source="local",
        model_dirs={"det": None, "rec": None, "cls": None},
    )
    assert kwargs["device"] == "cpu"
    assert "use_gpu" not in kwargs


def test_build_paddleocr_runtime_kwargs_includes_cls_when_supported():
    def fake_ocr(image, cls):
        _ = image, cls

    kwargs = build_paddleocr_runtime_kwargs(fake_ocr)
    assert kwargs == {"cls": False}


def test_paddle_backend_extract_supports_dict_shape():
    class FakeEngine:
        def ocr(self, image):
            _ = image
            return {
                "rec_texts": ["STONE'S THROW", "45% ALC/VOL"],
                "rec_scores": [0.97, 0.95],
                "dt_polys": [
                    [[0, 0], [10, 0], [10, 10], [0, 10]],
                    [[0, 12], [10, 12], [10, 22], [0, 22]],
                ],
            }

    backend = PaddleOCRBackend(
        use_gpu=False,
        model_source="local",
        model_dirs={"det": None, "rec": None, "cls": None},
        require_local_models=False,
    )
    backend._engine = FakeEngine()
    backend._state = "ready"

    extraction = backend.extract(np.zeros((8, 8, 3), dtype=np.uint8), source_label="sample", image_variant_id="color_resized")
    assert extraction.errors == []
    assert len(extraction.lines) == 2
    assert extraction.lines[0].bbox_space == "render_pixels"


def test_run_ocr_bytes_returns_variant_metadata_with_evidence_lines():
    service = OCRService(enabled=True, require_local_models=False, backend=FakeBackend())

    result, errors, variant_image, variant_metadata = service.run_ocr_bytes(
        build_test_image_bytes(),
        source_label="label.jpg",
        return_variant_image=True,
        return_variant_metadata=True,
    )

    assert result.full_text
    assert isinstance(errors, list)
    assert variant_image is not None
    assert variant_metadata["source_variant_id"] == "color_resized"
    assert isinstance(variant_metadata.get("evidence_lines"), list)
    assert variant_metadata["evidence_lines"][0]["source_backend"] == "fake"
