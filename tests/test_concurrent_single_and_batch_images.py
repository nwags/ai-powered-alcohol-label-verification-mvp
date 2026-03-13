import io
import time
import zipfile

import numpy as np

from app.dependencies import get_ocr_service
from app.domain.models import OCREvidenceLine, OCRLine, OCRResult
from app.main import app
from app.services.batch_service import BatchService
from conftest import build_test_image_bytes


def _build_images_zip_bytes() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label1.jpg", b"fake-image-content")
        archive.writestr("label2.jpg", b"fake-image-content")
    return zip_buffer.getvalue()


def test_single_review_images_persist_while_async_batch_runs(client, monkeypatch):
    original_analyze_record = BatchService._analyze_record

    def _slow_analyze(self, *args, **kwargs):
        time.sleep(0.15)
        return original_analyze_record(self, *args, **kwargs)

    monkeypatch.setattr(BatchService, "_analyze_record", _slow_analyze)

    class CanonicalEvidenceOCRService:
        def get_status(self) -> dict[str, object]:
            return {"state": "ready", "ready": True, "error": None}

        def run_ocr_bytes(
            self,
            image_bytes: bytes,
            source_label: str = "upload",
            return_variant_image: bool = False,
            return_variant_metadata: bool = False,
        ):
            _ = image_bytes, source_label
            ocr = OCRResult(
                full_text="STONE'S THROW WHISKEY\n45% Alc./Vol.",
                lines=[
                    OCRLine(
                        text="STONE'S THROW WHISKEY",
                        confidence=0.99,
                        bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
                    )
                ],
            )
            evidence = [
                OCREvidenceLine(
                    id="color_resized:line-0001",
                    text="STONE'S THROW WHISKEY",
                    confidence=0.99,
                    bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
                    bbox_space="render_pixels",
                    image_variant_id="color_resized",
                    source_backend="paddleocr",
                ).model_dump()
            ]
            if return_variant_image or return_variant_metadata:
                variant_image = np.zeros((32, 32, 3), dtype=np.uint8)
                return (
                    ocr,
                    [],
                    variant_image,
                    {
                        "source_variant_id": "color_resized",
                        "bbox_space": "render_pixels",
                        "evidence_lines": evidence,
                    },
                )
            return ocr, []

    previous_override = app.dependency_overrides.get(get_ocr_service)
    app.dependency_overrides[get_ocr_service] = lambda: CanonicalEvidenceOCRService()
    try:
        batch_submit = client.post(
            "/ui/batch",
            data={"batch_review_mode": "batch_label_only"},
            files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
            follow_redirects=False,
        )
        assert batch_submit.status_code == 303
        batch_location = batch_submit.headers.get("location", "")
        assert batch_location.startswith("/ui/batch/batch-")
        batch_id = batch_location.rsplit("/", 1)[-1]

        single_result = client.post(
            "/ui/analyze",
            data={"review_mode": "label_only", "label_type": "unknown"},
            files={"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")},
        )
        assert single_result.status_code == 200
        assert "Analyze Another Label" in single_result.text
        assert "/storage/uploads/" in single_result.text
        assert "/storage/outputs/annotated/" in single_result.text
        assert "No uploaded image available for this run." not in single_result.text
        assert "No annotated image available for this run." not in single_result.text

        completed_payload: dict[str, object] | None = None
        deadline = time.time() + 3.0
        while time.time() < deadline:
            status_response = client.get(f"/ui/batch/{batch_id}/status")
            assert status_response.status_code == 200
            payload = status_response.json()
            if payload.get("status") in {"completed", "failed"}:
                completed_payload = payload
                break
            time.sleep(0.02)

        assert completed_payload is not None
        assert completed_payload["status"] == "completed"
        assert completed_payload["processed_records"] == completed_payload["total_records"]
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_ocr_service, None)
        else:
            app.dependency_overrides[get_ocr_service] = previous_override
