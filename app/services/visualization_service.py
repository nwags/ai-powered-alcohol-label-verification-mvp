from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np

from app.domain.models import OCRResult


def create_annotated_ocr_artifact(image_bytes: bytes, ocr: OCRResult, storage_dir: Path) -> str | None:
    """Render OCR line bounding boxes and return storage-relative artifact path."""
    if not ocr.lines:
        return None

    np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return None

    annotated = image.copy()
    for line in ocr.lines:
        points = np.array([[int(x), int(y)] for x, y in line.bbox], dtype=np.int32)
        if points.shape[0] < 4:
            continue
        cv2.polylines(annotated, [points], isClosed=True, color=(0, 255, 0), thickness=2)
        origin = (max(0, points[0][0]), max(10, points[0][1] - 4))
        cv2.putText(
            annotated,
            f"{line.confidence:.2f}",
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    output_dir = Path(storage_dir) / "outputs" / "annotated"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"
    output_path = output_dir / filename
    if not cv2.imwrite(str(output_path), annotated):
        return None
    return f"outputs/annotated/{filename}"
