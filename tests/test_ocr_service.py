import sys
import types

import numpy as np

from app.domain.models import OCRLine, OCRResult
from app.services.image_preprocess import ImageVariant, build_ocr_variants
from app.services.ocr_service import (
    OCRService,
    _build_paddleocr_kwargs,
    _build_paddleocr_runtime_kwargs,
)


def test_run_ocr_bytes_invalid_image_returns_error():
    service = OCRService(enabled=True, require_local_models=False)
    result, errors = service.run_ocr_bytes(b"not-an-image")
    assert result.full_text == ""
    assert errors
    assert errors[0].startswith("invalid_image:")


def test_variant_selection_uses_first_variant_in_mvp_color_only_mode(monkeypatch):
    service = OCRService(enabled=True, require_local_models=False)
    service._engine = object()

    variants = [
        ImageVariant(name="v1", image=np.zeros((10, 10, 3), dtype=np.uint8)),
        ImageVariant(name="v2", image=np.zeros((10, 10), dtype=np.uint8)),
    ]

    def fake_build_variants(*args, **kwargs):
        _ = args, kwargs
        return variants

    def fake_run_engine_ocr(variant):
        if variant.name == "v1":
            return OCRResult(full_text="SHORT", lines=[OCRLine(text="SHORT", confidence=0.40, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]])])
        return OCRResult(
            full_text="LONGER TEXT\nANOTHER LINE",
            lines=[
                OCRLine(text="LONGER TEXT", confidence=0.90, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
                OCRLine(text="ANOTHER LINE", confidence=0.92, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            ],
        )

    monkeypatch.setattr("app.services.ocr_service.build_ocr_variants", fake_build_variants)
    monkeypatch.setattr(service, "_run_engine_ocr", fake_run_engine_ocr)

    result, errors, selected_variant = service._run_ocr_for_image(np.zeros((10, 10, 3), dtype=np.uint8), "test")
    assert not errors
    assert selected_variant == "v1"
    assert result.full_text == "SHORT"


def test_build_paddleocr_kwargs_prefers_device_for_cpu():
    def fake_ctor(*, device, lang, show_log, use_angle_cls):
        _ = device, lang, show_log, use_angle_cls

    kwargs = _build_paddleocr_kwargs(
        fake_ctor,
        use_gpu=False,
        model_source="local",
        model_dirs={"det": None, "rec": None, "cls": None},
    )
    assert kwargs["device"] == "cpu"
    assert "use_gpu" not in kwargs


def test_build_paddleocr_kwargs_falls_back_to_use_gpu():
    def fake_ctor(*, use_gpu, lang, show_log, use_angle_cls):
        _ = use_gpu, lang, show_log, use_angle_cls

    kwargs = _build_paddleocr_kwargs(
        fake_ctor,
        use_gpu=False,
        model_source="local",
        model_dirs={"det": None, "rec": None, "cls": None},
    )
    assert kwargs["use_gpu"] is False
    assert "device" not in kwargs


def test_ensure_engine_initializes_with_device_constructor(monkeypatch):
    captured: dict[str, object] = {}

    class FakePaddleOCR:
        def __init__(self, *, device, lang, show_log, use_angle_cls):
            captured["device"] = device
            captured["lang"] = lang
            captured["show_log"] = show_log
            captured["use_angle_cls"] = use_angle_cls

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))

    service = OCRService(enabled=True, use_gpu=False, require_local_models=False)
    service._ensure_engine()

    assert service._engine is not None
    assert service._init_error is None
    assert captured["device"] == "cpu"
    assert captured["use_angle_cls"] is False


def test_ensure_engine_initializes_with_use_gpu_constructor(monkeypatch):
    captured: dict[str, object] = {}

    class FakePaddleOCR:
        def __init__(self, *, use_gpu, lang, show_log, use_angle_cls):
            captured["use_gpu"] = use_gpu
            captured["lang"] = lang
            captured["show_log"] = show_log
            captured["use_angle_cls"] = use_angle_cls

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))

    service = OCRService(enabled=True, use_gpu=False, require_local_models=False)
    service._ensure_engine()

    assert service._engine is not None
    assert service._init_error is None
    assert captured["use_gpu"] is False
    assert captured["use_angle_cls"] is False


def test_build_paddleocr_runtime_kwargs_includes_cls_when_supported():
    def fake_ocr(image, cls):
        _ = image, cls

    kwargs = _build_paddleocr_runtime_kwargs(fake_ocr)
    assert kwargs == {"cls": False}


def test_build_paddleocr_runtime_kwargs_omits_cls_when_not_supported():
    def fake_ocr(image):
        _ = image

    kwargs = _build_paddleocr_runtime_kwargs(fake_ocr)
    assert kwargs == {}


def test_run_engine_ocr_works_without_cls_kwarg():
    class FakeEngine:
        def ocr(self, image):
            _ = image
            return [
                [
                    (
                        [[0, 0], [1, 0], [1, 1], [0, 1]],
                        ("SAMPLE TEXT", 0.91),
                    )
                ]
            ]

    service = OCRService(enabled=True, require_local_models=False)
    service._engine = FakeEngine()
    variant = ImageVariant(name="no_cls", image=np.zeros((8, 8, 3), dtype=np.uint8))

    result = service._run_engine_ocr(variant)
    assert result.full_text == "SAMPLE TEXT"
    assert len(result.lines) == 1
    assert result.lines[0].confidence == 0.91


def test_ensure_engine_fails_when_local_models_required_and_missing():
    service = OCRService(
        enabled=True,
        require_local_models=True,
        model_root=None,
        det_model_dir=None,
        rec_model_dir=None,
        cls_model_dir=None,
    )
    service._ensure_engine()

    assert service._engine is None
    assert service._state == "failed"
    assert service._init_error is not None
    assert service._init_error.startswith("ocr_model_assets_missing:")


def test_run_engine_ocr_supports_dict_result_shape():
    class FakeEngine:
        def ocr(self, image):
            _ = image
            return {
                "rec_texts": ["STONE'S THROW", "45% ALC/VOL"],
                "rec_scores": [0.97, 0.95],
                "dt_polys": [
                    [[0, 0], [1, 0], [1, 1], [0, 1]],
                    [[0, 2], [1, 2], [1, 3], [0, 3]],
                ],
            }

    service = OCRService(enabled=True, require_local_models=False)
    service._engine = FakeEngine()
    variant = ImageVariant(name="dict_shape", image=np.zeros((8, 8, 3), dtype=np.uint8))

    result = service._run_engine_ocr(variant)
    assert len(result.lines) == 2
    assert "STONE'S THROW" in result.full_text


def test_run_engine_ocr_supports_flat_line_item_shape():
    class FakeEngine:
        def predict(self, image):
            _ = image
            return [
                (
                    [[0, 0], [1, 0], [1, 1], [0, 1]],
                    ("GOVERNMENT WARNING", 0.91),
                )
            ]

    service = OCRService(enabled=True, require_local_models=False)
    service._engine = FakeEngine()
    variant = ImageVariant(name="flat_item_shape", image=np.zeros((8, 8, 3), dtype=np.uint8))

    result = service._run_engine_ocr(variant)
    assert len(result.lines) == 1
    assert result.lines[0].text == "GOVERNMENT WARNING"


def test_build_ocr_variants_returns_bgr_images_for_all_variants():
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    variants = build_ocr_variants(image, max_variants=3)

    assert len(variants) == 3
    for variant in variants:
        assert variant.image.ndim == 3
        assert variant.image.shape[2] == 3


def test_run_ocr_for_image_uses_only_color_variant_in_mvp_mode(monkeypatch):
    service = OCRService(enabled=True, require_local_models=False, mvp_color_only=True)
    service._engine = object()

    variants = [
        ImageVariant(name="color_resized", image=np.zeros((10, 10, 3), dtype=np.uint8)),
        ImageVariant(name="gray_clean_bgr", image=np.zeros((10, 10, 3), dtype=np.uint8)),
    ]

    def fake_build_variants(*args, **kwargs):
        _ = args, kwargs
        return variants

    calls: list[str] = []

    def fake_run_engine_ocr(variant):
        calls.append(variant.name)
        return OCRResult(
            full_text="TEXT",
            lines=[OCRLine(text="TEXT", confidence=0.9, bbox=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])],
        )

    monkeypatch.setattr("app.services.ocr_service.build_ocr_variants", fake_build_variants)
    monkeypatch.setattr(service, "_run_engine_ocr", fake_run_engine_ocr)

    result, errors, selected_variant = service._run_ocr_for_image(np.zeros((10, 10, 3), dtype=np.uint8), "mvp")
    assert not errors
    assert selected_variant == "color_resized"
    assert result.full_text == "TEXT"
    assert calls == ["color_resized"]
