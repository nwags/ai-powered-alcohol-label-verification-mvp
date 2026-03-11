import sys
import types

import numpy as np

from app.domain.models import OCRLine, OCRResult
from app.services.image_preprocess import ImageVariant
from app.services.ocr_service import (
    OCRService,
    _build_paddleocr_kwargs,
    _build_paddleocr_runtime_kwargs,
)


def test_run_ocr_bytes_invalid_image_returns_error():
    service = OCRService(enabled=True)
    result, errors = service.run_ocr_bytes(b"not-an-image")
    assert result.full_text == ""
    assert errors
    assert errors[0].startswith("invalid_image:")


def test_variant_selection_prefers_higher_scored_result(monkeypatch):
    service = OCRService(enabled=True)
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
    assert selected_variant == "v2"
    assert "ANOTHER LINE" in result.full_text


def test_build_paddleocr_kwargs_prefers_device_for_cpu():
    def fake_ctor(*, device, lang, show_log, use_angle_cls):
        _ = device, lang, show_log, use_angle_cls

    kwargs = _build_paddleocr_kwargs(fake_ctor, use_gpu=False)
    assert kwargs["device"] == "cpu"
    assert "use_gpu" not in kwargs


def test_build_paddleocr_kwargs_falls_back_to_use_gpu():
    def fake_ctor(*, use_gpu, lang, show_log, use_angle_cls):
        _ = use_gpu, lang, show_log, use_angle_cls

    kwargs = _build_paddleocr_kwargs(fake_ctor, use_gpu=False)
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

    service = OCRService(enabled=True, use_gpu=False)
    service._ensure_engine()

    assert service._engine is not None
    assert service._init_error is None
    assert captured["device"] == "cpu"


def test_ensure_engine_initializes_with_use_gpu_constructor(monkeypatch):
    captured: dict[str, object] = {}

    class FakePaddleOCR:
        def __init__(self, *, use_gpu, lang, show_log, use_angle_cls):
            captured["use_gpu"] = use_gpu
            captured["lang"] = lang
            captured["show_log"] = show_log
            captured["use_angle_cls"] = use_angle_cls

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))

    service = OCRService(enabled=True, use_gpu=False)
    service._ensure_engine()

    assert service._engine is not None
    assert service._init_error is None
    assert captured["use_gpu"] is False


def test_build_paddleocr_runtime_kwargs_includes_cls_when_supported():
    def fake_ocr(image, cls):
        _ = image, cls

    kwargs = _build_paddleocr_runtime_kwargs(fake_ocr)
    assert kwargs == {"cls": True}


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

    service = OCRService(enabled=True)
    service._engine = FakeEngine()
    variant = ImageVariant(name="no_cls", image=np.zeros((8, 8, 3), dtype=np.uint8))

    result = service._run_engine_ocr(variant)
    assert result.full_text == "SAMPLE TEXT"
    assert len(result.lines) == 1
    assert result.lines[0].confidence == 0.91
