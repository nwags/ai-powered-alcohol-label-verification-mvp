from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from app.services.ocr_backends.types import OCRExtraction


class OCRBackend(Protocol):
    """Internal OCR backend contract for engine-specific adapters."""

    def warmup(self) -> None:
        ...

    def is_ready(self) -> bool:
        ...

    def get_status(self) -> dict[str, Any]:
        ...

    def extract(self, image: np.ndarray, source_label: str, image_variant_id: str) -> OCRExtraction:
        ...
