from __future__ import annotations

import inspect
import logging
import threading
from time import perf_counter
from typing import Any

import numpy as np

from app.domain.models import OCRLine, OCRResult
from app.services.image_preprocess import ImageVariant, build_ocr_variants, decode_image_bytes, read_image

logger = logging.getLogger(__name__)


def _build_paddleocr_kwargs(
    paddleocr_constructor: Any,
    *,
    use_gpu: bool,
) -> dict[str, Any]:
    parameters = inspect.signature(paddleocr_constructor).parameters
    kwargs: dict[str, Any] = {}

    if "use_angle_cls" in parameters:
        kwargs["use_angle_cls"] = True
    if "lang" in parameters:
        kwargs["lang"] = "en"
    if "show_log" in parameters:
        kwargs["show_log"] = False

    if "device" in parameters:
        kwargs["device"] = "gpu" if use_gpu else "cpu"
    elif "use_gpu" in parameters:
        kwargs["use_gpu"] = use_gpu

    return kwargs


def _build_paddleocr_runtime_kwargs(ocr_callable: Any) -> dict[str, Any]:
    parameters = inspect.signature(ocr_callable).parameters
    kwargs: dict[str, Any] = {}
    if "cls" in parameters:
        kwargs["cls"] = True
    return kwargs


def _invoke_paddleocr(engine: Any, image: np.ndarray) -> Any:
    ocr_callable = getattr(engine, "ocr", None)
    if callable(ocr_callable):
        kwargs = _build_paddleocr_runtime_kwargs(ocr_callable)
        return ocr_callable(image, **kwargs)

    predict_callable = getattr(engine, "predict", None)
    if callable(predict_callable):
        kwargs = _build_paddleocr_runtime_kwargs(predict_callable)
        return predict_callable(image, **kwargs)

    raise AttributeError("OCR engine does not expose an ocr() or predict() method")


class OCRService:
    def __init__(
        self,
        enabled: bool = True,
        use_gpu: bool = False,
        max_dimension: int = 2200,
        max_variants: int = 3,
        enable_deskew: bool = False,
    ) -> None:
        self.enabled = enabled
        self.use_gpu = use_gpu
        self.max_dimension = max_dimension
        self.max_variants = max_variants
        self.enable_deskew = enable_deskew
        self._engine: Any = None
        self._init_error: str | None = None
        self._init_lock = threading.Lock()
        self._warmup_thread: threading.Thread | None = None
        self._state = "ready" if not enabled else "cold"

    def start_warmup_background(self) -> None:
        if not self.enabled:
            self._state = "ready"
            return

        if self._engine is not None or self._init_error is not None:
            return
        if self._warmup_thread is not None and self._warmup_thread.is_alive():
            return

        self._state = "warming"
        self._warmup_thread = threading.Thread(target=self._ensure_engine, name="ocr-warmup", daemon=True)
        self._warmup_thread.start()

    def get_status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"state": "ready", "ready": True, "error": None}
        return {"state": self._state, "ready": self._engine is not None, "error": self._init_error}

    def _ensure_engine(self) -> None:
        if not self.enabled or self._engine is not None or self._init_error is not None:
            return
        with self._init_lock:
            if self._engine is not None or self._init_error is not None:
                return
            self._state = "warming"
        started = perf_counter()
        try:
            from paddleocr import PaddleOCR  # type: ignore

            kwargs = _build_paddleocr_kwargs(PaddleOCR, use_gpu=self.use_gpu)
            self._engine = PaddleOCR(**kwargs)
            self._state = "ready"
            logger.info("OCR engine initialized in %.1f ms", (perf_counter() - started) * 1000.0)
        except Exception as exc:  # pragma: no cover - depends on runtime image
            self._init_error = f"ocr_init_failed: {exc}"
            self._state = "failed"
            logger.exception("Failed to initialize OCR engine")

    def is_ready(self) -> bool:
        return bool(self.get_status()["ready"])

    def run_ocr(self, image_path: str) -> OCRResult:
        image = read_image(image_path)
        result, errors, selected_variant = self._run_ocr_for_image(image, source_label=image_path)
        if errors:
            raise RuntimeError("; ".join(errors))
        logger.info("OCR completed for %s using variant=%s lines=%d", image_path, selected_variant, len(result.lines))
        return result

    def run_ocr_bytes(self, image_bytes: bytes, source_label: str = "upload") -> tuple[OCRResult, list[str]]:
        try:
            image = decode_image_bytes(image_bytes)
        except Exception as exc:
            return OCRResult(full_text="", lines=[]), [f"invalid_image: {exc}"]
        result, errors, selected_variant = self._run_ocr_for_image(image, source_label=source_label)
        logger.info(
            "OCR bytes completed for %s using variant=%s lines=%d errors=%d",
            source_label,
            selected_variant,
            len(result.lines),
            len(errors),
        )
        return result, errors

    # Backward-compatible alias for existing call sites/tests.
    def extract_text(self, image_bytes: bytes) -> tuple[OCRResult, list[str]]:
        return self.run_ocr_bytes(image_bytes)

    def _run_ocr_for_image(self, image: np.ndarray, source_label: str) -> tuple[OCRResult, list[str], str]:
        errors: list[str] = []

        if not self.enabled:
            return OCRResult(full_text="", lines=[]), errors, "disabled"

        self._ensure_engine()
        if self._engine is None:
            if self._init_error:
                errors.append(self._init_error)
            return OCRResult(full_text="", lines=[]), errors, "uninitialized"

        started = perf_counter()
        variants = build_ocr_variants(
            image,
            max_dimension=self.max_dimension,
            enable_deskew=self.enable_deskew,
            max_variants=self.max_variants,
        )

        best_result = OCRResult(full_text="", lines=[])
        best_variant_name = "none"
        best_score = -1.0

        for variant in variants:
            try:
                candidate = self._run_engine_ocr(variant)
            except Exception as exc:
                errors.append(f"ocr_variant_failed({variant.name}): {exc}")
                continue
            score = self._score_result(candidate)
            if score > best_score:
                best_result = candidate
                best_variant_name = variant.name
                best_score = score

        elapsed_ms = (perf_counter() - started) * 1000.0
        logger.info(
            "OCR run finished source=%s variants=%d best_variant=%s score=%.2f elapsed_ms=%.1f",
            source_label,
            len(variants),
            best_variant_name,
            best_score,
            elapsed_ms,
        )

        if best_score < 0:
            errors.append("ocr_failed: no variant produced usable output")
        return best_result, errors, best_variant_name

    def _run_engine_ocr(self, variant: ImageVariant) -> OCRResult:
        raw_result = _invoke_paddleocr(self._engine, variant.image)
        lines: list[OCRLine] = []
        for page in raw_result or []:
            for item in page or []:
                if not item or len(item) < 2:
                    continue
                bbox, payload = item
                text = str(payload[0]).strip() if payload else ""
                confidence = float(payload[1]) if payload and len(payload) > 1 else 0.0
                if not text:
                    continue
                normalized_bbox = [[float(point[0]), float(point[1])] for point in bbox]
                lines.append(OCRLine(text=text, confidence=confidence, bbox=normalized_bbox))
        full_text = "\n".join(line.text for line in lines)
        return OCRResult(full_text=full_text, lines=lines)

    def _score_result(self, result: OCRResult) -> float:
        if not result.lines:
            return 0.0
        text_count = sum(len(line.text.strip()) for line in result.lines)
        confidence_sum = sum(line.confidence for line in result.lines)
        line_count = len(result.lines)
        return confidence_sum + (text_count / 32.0) + (line_count * 0.5)
