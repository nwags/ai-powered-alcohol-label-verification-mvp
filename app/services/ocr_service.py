from __future__ import annotations

import inspect
import logging
import os
import threading
from pathlib import Path
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
    model_source: str,
    model_dirs: dict[str, Path | None],
) -> dict[str, Any]:
    parameters = inspect.signature(paddleocr_constructor).parameters
    kwargs: dict[str, Any] = {}

    if "use_angle_cls" in parameters:
        # MVP stability: disable optional angle classifier path.
        kwargs["use_angle_cls"] = False
    if "lang" in parameters:
        kwargs["lang"] = "en"
    if "show_log" in parameters:
        kwargs["show_log"] = False

    if "device" in parameters:
        kwargs["device"] = "gpu" if use_gpu else "cpu"
    elif "use_gpu" in parameters:
        kwargs["use_gpu"] = use_gpu

    if model_source == "local":
        det_dir = model_dirs.get("det")
        rec_dir = model_dirs.get("rec")
        cls_dir = model_dirs.get("cls")
        if "det_model_dir" in parameters and det_dir is not None:
            kwargs["det_model_dir"] = str(det_dir)
        if "rec_model_dir" in parameters and rec_dir is not None:
            kwargs["rec_model_dir"] = str(rec_dir)
        if "cls_model_dir" in parameters and cls_dir is not None:
            kwargs["cls_model_dir"] = str(cls_dir)

    return kwargs


def _build_paddleocr_runtime_kwargs(ocr_callable: Any) -> dict[str, Any]:
    parameters = inspect.signature(ocr_callable).parameters
    kwargs: dict[str, Any] = {}
    if "cls" in parameters:
        # MVP stability: disable optional classifier at inference call time.
        kwargs["cls"] = False
    return kwargs


def _invoke_paddleocr(engine: Any, image: np.ndarray) -> tuple[str, Any]:
    ocr_callable = getattr(engine, "ocr", None)
    if callable(ocr_callable):
        kwargs = _build_paddleocr_runtime_kwargs(ocr_callable)
        return "ocr", ocr_callable(image, **kwargs)

    predict_callable = getattr(engine, "predict", None)
    if callable(predict_callable):
        kwargs = _build_paddleocr_runtime_kwargs(predict_callable)
        return "predict", predict_callable(image, **kwargs)

    raise AttributeError("OCR engine does not expose an ocr() or predict() method")


class OCRService:
    def __init__(
        self,
        enabled: bool = True,
        use_gpu: bool = False,
        require_local_models: bool = True,
        model_source: str = "local",
        model_root: Path | None = None,
        det_model_dir: Path | None = None,
        rec_model_dir: Path | None = None,
        cls_model_dir: Path | None = None,
        max_dimension: int = 2200,
        max_variants: int = 3,
        enable_deskew: bool = False,
        mvp_color_only: bool = True,
    ) -> None:
        self.enabled = enabled
        self.use_gpu = use_gpu
        self.require_local_models = require_local_models
        self.model_source = model_source.strip().lower() if model_source else "local"
        self._model_dirs = self._resolve_model_dirs(
            model_root=model_root,
            det_model_dir=det_model_dir,
            rec_model_dir=rec_model_dir,
            cls_model_dir=cls_model_dir,
        )
        self._missing_model_assets: list[str] = []
        self._model_assets_ready = not require_local_models
        self.max_dimension = max_dimension
        self.max_variants = max_variants
        self.enable_deskew = enable_deskew
        self.mvp_color_only = mvp_color_only
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
            return {
                "state": "ready",
                "ready": True,
                "error": None,
                "model_source": self.model_source,
                "require_local_models": self.require_local_models,
                "model_assets_ready": True,
                "model_assets_missing": [],
            }
        return {
            "state": self._state,
            "ready": self._engine is not None,
            "error": self._init_error,
            "model_source": self.model_source,
            "require_local_models": self.require_local_models,
            "model_assets_ready": self._model_assets_ready,
            "model_assets_missing": self._missing_model_assets,
        }

    def _ensure_engine(self) -> None:
        if not self.enabled or self._engine is not None or self._init_error is not None:
            return
        with self._init_lock:
            if self._engine is not None or self._init_error is not None:
                return
            self._state = "warming"
        started = perf_counter()
        try:
            os.environ.setdefault("FLAGS_enable_pir_api", "0")
            missing_assets = self._validate_model_assets()
            self._missing_model_assets = missing_assets
            self._model_assets_ready = len(missing_assets) == 0
            if missing_assets and self.require_local_models:
                missing_text = ", ".join(missing_assets)
                self._init_error = f"ocr_model_assets_missing: {missing_text}"
                self._state = "failed"
                logger.error("OCR local model assets missing: %s", missing_text)
                return

            from paddleocr import PaddleOCR  # type: ignore

            kwargs = _build_paddleocr_kwargs(
                PaddleOCR,
                use_gpu=self.use_gpu,
                model_source=self.model_source,
                model_dirs=self._model_dirs,
            )
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
        result, errors, selected_variant, _ = self._run_ocr_for_image(image, source_label=image_path)
        if errors:
            raise RuntimeError("; ".join(errors))
        logger.info("OCR completed for %s using variant=%s lines=%d", image_path, selected_variant, len(result.lines))
        return result

    def run_ocr_bytes(
        self,
        image_bytes: bytes,
        source_label: str = "upload",
        return_variant_image: bool = False,
    ) -> tuple[OCRResult, list[str]] | tuple[OCRResult, list[str], np.ndarray | None]:
        try:
            image = decode_image_bytes(image_bytes)
        except Exception as exc:
            if return_variant_image:
                return OCRResult(full_text="", lines=[]), [f"invalid_image: {exc}"], None
            return OCRResult(full_text="", lines=[]), [f"invalid_image: {exc}"]
        result, errors, selected_variant, selected_variant_image = self._run_ocr_for_image(image, source_label=source_label)
        logger.info(
            "OCR bytes completed for %s using variant=%s lines=%d errors=%d",
            source_label,
            selected_variant,
            len(result.lines),
            len(errors),
        )
        if return_variant_image:
            return result, errors, selected_variant_image
        return result, errors

    # Backward-compatible alias for existing call sites/tests.
    def extract_text(self, image_bytes: bytes) -> tuple[OCRResult, list[str]]:
        return self.run_ocr_bytes(image_bytes)

    def _run_ocr_for_image(self, image: np.ndarray, source_label: str) -> tuple[OCRResult, list[str], str, np.ndarray | None]:
        errors: list[str] = []

        if not self.enabled:
            return OCRResult(full_text="", lines=[]), errors, "disabled", None

        self._ensure_engine()
        if self._engine is None:
            if self._init_error:
                errors.append(self._init_error)
            return OCRResult(full_text="", lines=[]), errors, "uninitialized", None

        started = perf_counter()
        variants = build_ocr_variants(
            image,
            max_dimension=self.max_dimension,
            enable_deskew=self.enable_deskew,
            max_variants=self.max_variants,
        )
        if self.mvp_color_only and variants:
            variants = [variants[0]]

        best_result = OCRResult(full_text="", lines=[])
        best_variant_name = "none"
        best_score = -1.0
        best_variant_image: np.ndarray | None = None

        for variant in variants:
            try:
                candidate = self._run_engine_ocr(variant)
            except Exception as exc:
                error_text = f"{exc.__class__.__name__}: {exc}"
                logger.warning(
                    "OCR variant failed source=%s variant=%s error=%s",
                    source_label,
                    variant.name,
                    error_text,
                )
                errors.append(f"ocr_variant_failed({variant.name}): {error_text}")
                continue
            score = self._score_result(candidate)
            if score > best_score:
                best_result = candidate
                best_variant_name = variant.name
                best_score = score
                best_variant_image = variant.image.copy()

        elapsed_ms = (perf_counter() - started) * 1000.0
        logger.info(
            "OCR run finished source=%s variants=%d best_variant=%s lines=%d score=%.2f elapsed_ms=%.1f",
            source_label,
            len(variants),
            best_variant_name,
            len(best_result.lines),
            best_score,
            elapsed_ms,
        )

        if best_score < 0:
            errors.append("ocr_failed: no variant produced usable output")
        return best_result, errors, best_variant_name, best_variant_image

    def _run_engine_ocr(self, variant: ImageVariant) -> OCRResult:
        callable_name, raw_result = _invoke_paddleocr(self._engine, variant.image)
        logger.info("OCR runtime call variant=%s callable=%s", variant.name, callable_name)
        logger.info(
            "OCR raw result variant=%s type=%s preview=%s",
            variant.name,
            type(raw_result).__name__,
            self._short_repr(raw_result),
        )
        lines: list[OCRLine] = []
        self._collect_lines(raw_result, lines)
        full_text = "\n".join(line.text for line in lines)
        return OCRResult(full_text=full_text, lines=lines)

    def _score_result(self, result: OCRResult) -> float:
        if not result.lines:
            return 0.0
        text_count = sum(len(line.text.strip()) for line in result.lines)
        confidence_sum = sum(line.confidence for line in result.lines)
        line_count = len(result.lines)
        return confidence_sum + (text_count / 32.0) + (line_count * 0.5)

    def _resolve_model_dirs(
        self,
        *,
        model_root: Path | None,
        det_model_dir: Path | None,
        rec_model_dir: Path | None,
        cls_model_dir: Path | None,
    ) -> dict[str, Path | None]:
        root = model_root
        if root is not None:
            root = Path(root)
        return {
            "det": Path(det_model_dir) if det_model_dir else (root / "det" if root else None),
            "rec": Path(rec_model_dir) if rec_model_dir else (root / "rec" if root else None),
            "cls": Path(cls_model_dir) if cls_model_dir else (root / "cls" if root else None),
        }

    def _validate_model_assets(self) -> list[str]:
        if self.model_source != "local" and not self.require_local_models:
            return []

        missing: list[str] = []
        for model_type in ("det", "rec", "cls"):
            model_dir = self._model_dirs.get(model_type)
            if model_dir is None:
                missing.append(f"{model_type}:unset")
                continue
            if not model_dir.exists() or not model_dir.is_dir():
                missing.append(f"{model_type}:{model_dir}")
                continue
            try:
                has_files = any(model_dir.iterdir())
            except OSError:
                has_files = False
            if not has_files:
                missing.append(f"{model_type}:{model_dir} (empty)")
        return missing

    def _collect_lines(self, node: Any, lines: list[OCRLine]) -> None:
        if node is None:
            return

        if isinstance(node, dict):
            self._collect_lines_from_mapping(node, lines)
            return

        if hasattr(node, "tolist"):
            self._collect_lines(node.tolist(), lines)
            return

        if isinstance(node, (list, tuple)):
            if self._looks_like_line_item(node):
                line = self._line_from_item(node)
                if line is not None:
                    lines.append(line)
                return
            for child in node:
                self._collect_lines(child, lines)
            return

    def _collect_lines_from_mapping(self, payload: dict[str, Any], lines: list[OCRLine]) -> None:
        # Paddle versions may expose compact arrays in dict form.
        rec_texts = self._as_list(payload.get("rec_texts"))
        rec_scores = self._as_list(payload.get("rec_scores"))
        dt_polys_raw = payload.get("dt_polys")
        if dt_polys_raw is None:
            dt_polys_raw = payload.get("boxes")
        dt_polys = self._as_list(dt_polys_raw)
        if isinstance(rec_texts, list):
            for idx, text_value in enumerate(rec_texts):
                text = str(text_value).strip()
                if not text:
                    continue
                confidence = 0.0
                if isinstance(rec_scores, list) and idx < len(rec_scores):
                    confidence = self._to_confidence(rec_scores[idx])
                bbox = self._normalize_bbox(dt_polys[idx]) if isinstance(dt_polys, list) and idx < len(dt_polys) else None
                lines.append(OCRLine(text=text, confidence=confidence, bbox=self._safe_bbox(bbox)))
            return

        # Some structures expose one line as text/score/bbox.
        direct_text = payload.get("text") or payload.get("transcription")
        if direct_text:
            text = str(direct_text).strip()
            if text:
                confidence = self._to_confidence(payload.get("score") or payload.get("confidence"))
                bbox = self._bbox_from_mapping(payload)
                lines.append(OCRLine(text=text, confidence=confidence, bbox=self._safe_bbox(bbox)))
                return

        for value in payload.values():
            self._collect_lines(value, lines)

    def _looks_like_line_item(self, item: tuple[Any, ...] | list[Any]) -> bool:
        if len(item) < 2:
            return False
        return self._is_bbox_like(item[0]) and self._payload_has_text(item[1])

    def _line_from_item(self, item: tuple[Any, ...] | list[Any]) -> OCRLine | None:
        bbox = self._normalize_bbox(item[0])
        text, confidence = self._text_and_confidence_from_payload(item[1])
        if not text:
            return None
        return OCRLine(text=text, confidence=confidence, bbox=self._safe_bbox(bbox))

    def _payload_has_text(self, payload: Any) -> bool:
        text, _ = self._text_and_confidence_from_payload(payload)
        return bool(text)

    def _text_and_confidence_from_payload(self, payload: Any) -> tuple[str, float]:
        if isinstance(payload, (list, tuple)):
            if not payload:
                return "", 0.0
            text = str(payload[0]).strip()
            confidence = self._to_confidence(payload[1]) if len(payload) > 1 else 0.0
            return text, confidence
        if isinstance(payload, dict):
            text = str(payload.get("text") or payload.get("transcription") or "").strip()
            confidence = self._to_confidence(payload.get("score") or payload.get("confidence"))
            return text, confidence
        if isinstance(payload, str):
            return payload.strip(), 0.0
        return "", 0.0

    def _bbox_from_mapping(self, payload: dict[str, Any]) -> list[list[float]] | None:
        for key in ("bbox", "points", "poly", "dt_poly", "dt_polys", "box"):
            if key in payload:
                return self._normalize_bbox(payload.get(key))
        return None

    def _is_bbox_like(self, value: Any) -> bool:
        value = self._as_list(value)
        if not isinstance(value, list) or len(value) < 2:
            return False
        first_point = value[0]
        if hasattr(first_point, "tolist"):
            first_point = first_point.tolist()
        return isinstance(first_point, (list, tuple)) and len(first_point) >= 2

    def _normalize_bbox(self, bbox: Any) -> list[list[float]] | None:
        bbox = self._as_list(bbox)
        if not self._is_bbox_like(bbox):
            return None
        normalized: list[list[float]] = []
        for point in bbox:
            point = self._as_list(point)
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return None
            try:
                normalized.append([float(point[0]), float(point[1])])
            except (TypeError, ValueError):
                return None
        return normalized

    def _as_list(self, value: Any) -> Any:
        if hasattr(value, "tolist"):
            try:
                return value.tolist()
            except Exception:
                return value
        return value

    def _to_confidence(self, value: Any) -> float:
        try:
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _safe_bbox(self, bbox: list[list[float]] | None) -> list[list[float]]:
        if bbox is not None and len(bbox) >= 4:
            return bbox
        return [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    def _short_repr(self, payload: Any, max_len: int = 240) -> str:
        text = repr(payload)
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 3]}..."
