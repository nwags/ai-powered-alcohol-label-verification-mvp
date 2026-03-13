from app.services.ocr_backends.base import OCRBackend
from app.services.ocr_backends.paddle_backend import (
    PaddleOCRBackend,
    build_paddleocr_kwargs,
    build_paddleocr_runtime_kwargs,
)
from app.services.ocr_backends.types import OCREvidenceLinePayload, OCRExtraction

__all__ = [
    "OCRBackend",
    "OCRExtraction",
    "OCREvidenceLinePayload",
    "PaddleOCRBackend",
    "build_paddleocr_kwargs",
    "build_paddleocr_runtime_kwargs",
]
