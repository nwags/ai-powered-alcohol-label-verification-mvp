from __future__ import annotations

import logging
import threading
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from app.domain.models import OCREvidenceLine, OCRLine, OCRResult
from app.services.image_preprocess import build_ocr_variants, decode_image_bytes, read_image
from app.services.ocr_backends import (
    OCRBackend,
    OCREvidenceLinePayload,
    PaddleOCRBackend,
    build_paddleocr_kwargs,
    build_paddleocr_runtime_kwargs,
)

logger = logging.getLogger(__name__)

# Backward-compatible exports for existing tests/import sites.
_build_paddleocr_kwargs = build_paddleocr_kwargs
_build_paddleocr_runtime_kwargs = build_paddleocr_runtime_kwargs


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
        backend: OCRBackend | None = None,
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

        self._backend: OCRBackend = backend or PaddleOCRBackend(
            use_gpu=self.use_gpu,
            model_source=self.model_source,
            model_dirs=self._model_dirs,
            require_local_models=self.require_local_models,
        )
        self._engine: Any = None
        self._init_error: str | None = None
        self._init_lock = threading.Lock()
        self._warmup_thread: threading.Thread | None = None
        self._state = "ready" if not enabled else "cold"

    def start_warmup_background(self) -> None:
        if not self.enabled:
            self._state = "ready"
            return

        if self.is_ready() or self._init_error is not None:
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

        backend_status = self._backend.get_status()
        self._state = str(backend_status.get("state", self._state))
        self._init_error = backend_status.get("error") if isinstance(backend_status.get("error"), str) else None
        raw_missing = backend_status.get("model_assets_missing", [])
        self._missing_model_assets = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
        self._model_assets_ready = bool(backend_status.get("model_assets_ready", False))

        return {
            "state": self._state,
            "ready": bool(backend_status.get("ready", False)),
            "error": self._init_error,
            "model_source": self.model_source,
            "require_local_models": self.require_local_models,
            "model_assets_ready": self._model_assets_ready,
            "model_assets_missing": self._missing_model_assets,
            "source_backend": backend_status.get("source_backend", "paddleocr"),
        }

    def _ensure_engine(self) -> None:
        if not self.enabled:
            return
        with self._init_lock:
            self._state = "warming"
            self._backend.warmup()
            backend_status = self._backend.get_status()
            self._state = str(backend_status.get("state", self._state))
            self._init_error = backend_status.get("error") if isinstance(backend_status.get("error"), str) else None
            raw_missing = backend_status.get("model_assets_missing", [])
            self._missing_model_assets = [str(item) for item in raw_missing] if isinstance(raw_missing, list) else []
            self._model_assets_ready = bool(backend_status.get("model_assets_ready", False))
            # Keep compatibility for existing diagnostics/tests that inspect _engine.
            self._engine = getattr(self._backend, "_engine", self._engine)

    def is_ready(self) -> bool:
        return bool(self.get_status()["ready"])

    def run_ocr(self, image_path: str) -> OCRResult:
        image = read_image(image_path)
        result, errors, selected_variant, _, _ = self._run_ocr_for_image(image, source_label=image_path)
        if errors:
            raise RuntimeError("; ".join(errors))
        logger.info("OCR completed for %s using variant=%s lines=%d", image_path, selected_variant, len(result.lines))
        return result

    def run_ocr_bytes(
        self,
        image_bytes: bytes,
        source_label: str = "upload",
        return_variant_image: bool = False,
        return_variant_metadata: bool = False,
    ) -> (
        tuple[OCRResult, list[str]]
        | tuple[OCRResult, list[str], np.ndarray | None]
        | tuple[OCRResult, list[str], np.ndarray | None, dict[str, Any]]
    ):
        try:
            image = decode_image_bytes(image_bytes)
        except Exception as exc:
            if return_variant_image and return_variant_metadata:
                return OCRResult(full_text="", lines=[]), [f"invalid_image: {exc}"], None, {}
            if return_variant_image:
                return OCRResult(full_text="", lines=[]), [f"invalid_image: {exc}"], None
            return OCRResult(full_text="", lines=[]), [f"invalid_image: {exc}"]

        result, errors, selected_variant, selected_variant_image, selected_evidence = self._run_ocr_for_image(
            image,
            source_label=source_label,
        )
        logger.info(
            "OCR bytes completed for %s using variant=%s lines=%d errors=%d",
            source_label,
            selected_variant,
            len(result.lines),
            len(errors),
        )

        source_variant_id: str | None = selected_variant if selected_variant not in {"none", "disabled", "uninitialized"} else None
        if not selected_evidence:
            source_variant_id = None
        variant_metadata: dict[str, Any] = {
            "source_variant_id": source_variant_id,
            "bbox_space": "render_pixels" if selected_evidence else None,
            "source_backend": "paddleocr",
            "evidence_lines": [line.model_dump() for line in selected_evidence],
        }
        if selected_variant_image is not None:
            variant_height, variant_width = selected_variant_image.shape[:2]
            variant_metadata["image_width"] = int(variant_width)
            variant_metadata["image_height"] = int(variant_height)

        if return_variant_image and return_variant_metadata:
            return result, errors, selected_variant_image, variant_metadata
        if return_variant_image:
            return result, errors, selected_variant_image
        return result, errors

    def extract_text(self, image_bytes: bytes) -> tuple[OCRResult, list[str]]:
        return self.run_ocr_bytes(image_bytes)

    def _run_ocr_for_image(
        self,
        image: np.ndarray,
        source_label: str,
    ) -> tuple[OCRResult, list[str], str, np.ndarray | None, list[OCREvidenceLine]]:
        errors: list[str] = []

        if not self.enabled:
            return OCRResult(full_text="", lines=[]), errors, "disabled", None, []

        self._ensure_engine()
        if not self._backend.is_ready():
            if self._init_error:
                errors.append(self._init_error)
            return OCRResult(full_text="", lines=[]), errors, "uninitialized", None, []

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
        best_evidence: list[OCREvidenceLine] = []
        best_variant_name = "none"
        best_score = -1.0
        best_variant_image: np.ndarray | None = None

        for variant in variants:
            try:
                extraction = self._backend.extract(variant.image, source_label=source_label, image_variant_id=variant.name)
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

            if extraction.errors:
                for error in extraction.errors:
                    errors.append(f"ocr_variant_failed({variant.name}): {error}")
                continue

            candidate_result = self._result_from_extraction(extraction)
            score = self._score_result(candidate_result)
            if score > best_score:
                best_result = candidate_result
                best_evidence = [self._to_evidence_line(line) for line in extraction.lines]
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
        return best_result, errors, best_variant_name, best_variant_image, best_evidence

    def _run_engine_ocr(self, variant: Any) -> OCRResult:
        extraction = self._backend.extract(variant.image, source_label="internal", image_variant_id=variant.name)
        return self._result_from_extraction(extraction)

    def _result_from_extraction(self, extraction: Any) -> OCRResult:
        lines = [OCRLine(text=line.text, confidence=line.confidence, bbox=line.bbox) for line in extraction.lines]
        if extraction.full_text:
            full_text = extraction.full_text
        else:
            full_text = "\n".join(line.text for line in lines)
        return OCRResult(full_text=full_text, lines=lines)

    def _to_evidence_line(self, line: OCREvidenceLinePayload) -> OCREvidenceLine:
        return OCREvidenceLine(
            id=line.id,
            text=line.text,
            confidence=line.confidence,
            bbox=line.bbox,
            bbox_space=line.bbox_space,
            image_variant_id=line.image_variant_id,
            source_backend=line.source_backend,
        )

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
