from __future__ import annotations

import inspect
import logging
import os
import threading
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from app.services.ocr_backends.types import OCREvidenceLinePayload, OCRExtraction

logger = logging.getLogger(__name__)


def build_paddleocr_kwargs(
    paddleocr_constructor: Any,
    *,
    use_gpu: bool,
    model_source: str,
    model_dirs: dict[str, Path | None],
) -> dict[str, Any]:
    parameters = inspect.signature(paddleocr_constructor).parameters
    kwargs: dict[str, Any] = {}

    if "use_angle_cls" in parameters:
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


def build_paddleocr_runtime_kwargs(ocr_callable: Any) -> dict[str, Any]:
    parameters = inspect.signature(ocr_callable).parameters
    kwargs: dict[str, Any] = {}
    if "cls" in parameters:
        kwargs["cls"] = False
    return kwargs


class PaddleOCRBackend:
    def __init__(
        self,
        *,
        use_gpu: bool,
        model_source: str,
        model_dirs: dict[str, Path | None],
        require_local_models: bool,
    ) -> None:
        self.use_gpu = use_gpu
        self.model_source = model_source
        self.model_dirs = model_dirs
        self.require_local_models = require_local_models

        self._engine: Any = None
        self._state = "cold"
        self._init_error: str | None = None
        self._missing_model_assets: list[str] = []
        self._model_assets_ready = not require_local_models
        self._runtime_lock = threading.Lock()

    def warmup(self) -> None:
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

            kwargs = build_paddleocr_kwargs(
                PaddleOCR,
                use_gpu=self.use_gpu,
                model_source=self.model_source,
                model_dirs=self.model_dirs,
            )
            self._engine = PaddleOCR(**kwargs)
            self._state = "ready"
            logger.info("OCR backend initialized in %.1f ms", (perf_counter() - started) * 1000.0)
        except Exception as exc:  # pragma: no cover
            self._init_error = f"ocr_init_failed: {exc}"
            self._state = "failed"
            logger.exception("Failed to initialize PaddleOCR backend")

    def is_ready(self) -> bool:
        return self._engine is not None

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "ready": self.is_ready(),
            "error": self._init_error,
            "model_source": self.model_source,
            "require_local_models": self.require_local_models,
            "model_assets_ready": self._model_assets_ready,
            "model_assets_missing": self._missing_model_assets,
            "source_backend": "paddleocr",
        }

    def extract(self, image: np.ndarray, source_label: str, image_variant_id: str) -> OCRExtraction:
        if self._engine is None:
            self.warmup()
        if self._engine is None:
            errors: list[str] = []
            if self._init_error:
                errors.append(self._init_error)
            return OCRExtraction(full_text="", lines=[], errors=errors)

        with self._runtime_lock:
            callable_name, raw_result = self._invoke_engine(image)
            logger.info("OCR runtime call variant=%s callable=%s", image_variant_id, callable_name)
            logger.info(
                "OCR raw result variant=%s type=%s preview=%s",
                image_variant_id,
                type(raw_result).__name__,
                self._short_repr(raw_result),
            )

            lines: list[OCREvidenceLinePayload] = []
            self._collect_lines(raw_result, lines=lines, image_variant_id=image_variant_id)
        full_text = "\n".join(line.text for line in lines)
        return OCRExtraction(full_text=full_text, lines=lines, errors=[])

    def _invoke_engine(self, image: np.ndarray) -> tuple[str, Any]:
        ocr_callable = getattr(self._engine, "ocr", None)
        if callable(ocr_callable):
            kwargs = build_paddleocr_runtime_kwargs(ocr_callable)
            return "ocr", ocr_callable(image, **kwargs)

        predict_callable = getattr(self._engine, "predict", None)
        if callable(predict_callable):
            kwargs = build_paddleocr_runtime_kwargs(predict_callable)
            return "predict", predict_callable(image, **kwargs)

        raise AttributeError("OCR engine does not expose an ocr() or predict() method")

    def _collect_lines(self, node: Any, *, lines: list[OCREvidenceLinePayload], image_variant_id: str) -> None:
        if node is None:
            return

        if isinstance(node, dict):
            self._collect_lines_from_mapping(node, lines=lines, image_variant_id=image_variant_id)
            return

        if hasattr(node, "tolist"):
            self._collect_lines(node.tolist(), lines=lines, image_variant_id=image_variant_id)
            return

        if isinstance(node, (list, tuple)):
            if self._looks_like_line_item(node):
                line = self._line_from_item(node, image_variant_id=image_variant_id, line_index=len(lines) + 1)
                if line is not None:
                    lines.append(line)
                return
            for child in node:
                self._collect_lines(child, lines=lines, image_variant_id=image_variant_id)
            return

    def _collect_lines_from_mapping(
        self,
        payload: dict[str, Any],
        *,
        lines: list[OCREvidenceLinePayload],
        image_variant_id: str,
    ) -> None:
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
                line_id = f"{image_variant_id}:line-{len(lines) + 1:04d}"
                lines.append(
                    OCREvidenceLinePayload(
                        id=line_id,
                        text=text,
                        confidence=confidence,
                        bbox=self._safe_bbox(bbox),
                        bbox_space="render_pixels",
                        image_variant_id=image_variant_id,
                        source_backend="paddleocr",
                    )
                )
            return

        direct_text = payload.get("text") or payload.get("transcription")
        if direct_text:
            text = str(direct_text).strip()
            if text:
                confidence = self._to_confidence(payload.get("score") or payload.get("confidence"))
                bbox = self._bbox_from_mapping(payload)
                line_id = f"{image_variant_id}:line-{len(lines) + 1:04d}"
                lines.append(
                    OCREvidenceLinePayload(
                        id=line_id,
                        text=text,
                        confidence=confidence,
                        bbox=self._safe_bbox(bbox),
                        bbox_space="render_pixels",
                        image_variant_id=image_variant_id,
                        source_backend="paddleocr",
                    )
                )
                return

        for value in payload.values():
            self._collect_lines(value, lines=lines, image_variant_id=image_variant_id)

    def _looks_like_line_item(self, item: tuple[Any, ...] | list[Any]) -> bool:
        if len(item) < 2:
            return False
        return self._is_bbox_like(item[0]) and self._payload_has_text(item[1])

    def _line_from_item(
        self,
        item: tuple[Any, ...] | list[Any],
        *,
        image_variant_id: str,
        line_index: int,
    ) -> OCREvidenceLinePayload | None:
        bbox = self._normalize_bbox(item[0])
        text, confidence = self._text_and_confidence_from_payload(item[1])
        if not text:
            return None
        line_id = f"{image_variant_id}:line-{line_index:04d}"
        return OCREvidenceLinePayload(
            id=line_id,
            text=text,
            confidence=confidence,
            bbox=self._safe_bbox(bbox),
            bbox_space="render_pixels",
            image_variant_id=image_variant_id,
            source_backend="paddleocr",
        )

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

    def _validate_model_assets(self) -> list[str]:
        if self.model_source != "local" and not self.require_local_models:
            return []

        missing: list[str] = []
        for model_type in ("det", "rec", "cls"):
            model_dir = self.model_dirs.get(model_type)
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

    def _short_repr(self, payload: Any, max_len: int = 240) -> str:
        text = repr(payload)
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 3]}..."
