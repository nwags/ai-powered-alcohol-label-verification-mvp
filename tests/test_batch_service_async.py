import io
import time
import zipfile
from pathlib import Path

from app.domain.models import OCRLine, OCRResult
from app.services.batch_service import BatchService


class _StubOCRService:
    def run_ocr_bytes(self, image_bytes: bytes, source_label: str = "upload") -> tuple[OCRResult, list[str]]:
        _ = image_bytes, source_label
        return (
            OCRResult(
                full_text="SAMPLE LABEL TEXT",
                lines=[
                    OCRLine(
                        text="SAMPLE LABEL TEXT",
                        confidence=0.98,
                        bbox=[[0, 0], [12, 0], [12, 12], [0, 12]],
                    )
                ],
            ),
            [],
        )


def _build_images_zip_bytes() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label1.jpg", b"fake-image-content")
        archive.writestr("label2.jpg", b"fake-image-content")
    return zip_buffer.getvalue()


def _wait_for_terminal_status(service: BatchService, batch_id: str, timeout_s: float = 3.0) -> list[dict[str, object]]:
    seen: list[dict[str, object]] = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        payload = service.load_status_payload(batch_id=batch_id)
        assert payload is not None
        seen.append(payload)
        if payload.get("status") in {"completed", "failed"}:
            return seen
        time.sleep(0.02)
    return seen


def test_batch_service_async_lifecycle_is_monotonic(tmp_path: Path):
    service = BatchService(storage_dir=tmp_path / "runtime", async_max_workers=1)
    batch_id = service.enqueue_label_only(
        images_archive_bytes=_build_images_zip_bytes(),
        ocr_service=_StubOCRService(),
    )

    seen = _wait_for_terminal_status(service, batch_id)
    assert seen

    status_order = {"queued": 0, "running": 1, "completed": 2, "failed": 2}
    previous_status = -1
    previous_processed = -1
    for payload in seen:
        status_value = str(payload.get("status"))
        assert status_value in status_order
        assert status_order[status_value] >= previous_status
        previous_status = status_order[status_value]
        processed = int(payload.get("processed_records", 0))
        total = int(payload.get("total_records", 0))
        assert processed >= previous_processed
        assert processed <= total
        previous_processed = processed

    final_payload = seen[-1]
    assert final_payload["status"] == "completed"
    assert final_payload["completed_at"] is not None
    assert final_payload["processed_records"] == final_payload["total_records"]


def test_batch_service_async_failure_persists_error_and_terminal_metadata(tmp_path: Path):
    service = BatchService(storage_dir=tmp_path / "runtime", async_max_workers=1)

    def _raise_error(*args, **kwargs):
        raise RuntimeError("forced failure")

    service._analyze_record = _raise_error  # type: ignore[assignment]

    batch_id = service.enqueue_label_only(
        images_archive_bytes=_build_images_zip_bytes(),
        ocr_service=_StubOCRService(),
    )
    seen = _wait_for_terminal_status(service, batch_id)
    assert seen
    final_payload = seen[-1]
    assert final_payload["status"] == "failed"
    assert final_payload["completed_at"] is not None
    assert isinstance(final_payload.get("errors"), list)
    assert final_payload["errors"]


def test_batch_service_completed_status_payload_has_required_shape(tmp_path: Path):
    service = BatchService(storage_dir=tmp_path / "runtime", async_max_workers=1)
    batch_id = service.enqueue_label_only(
        images_archive_bytes=_build_images_zip_bytes(),
        ocr_service=_StubOCRService(),
    )

    seen = _wait_for_terminal_status(service, batch_id)
    assert seen
    payload = seen[-1]
    assert payload["status"] == "completed"
    assert payload["batch_id"] == batch_id
    assert payload["report_url"] == f"/ui/batch/{batch_id}"
    assert isinstance(payload.get("summary"), dict)
    assert isinstance(payload.get("rows"), list)
    assert payload["created_at"] is not None
    assert payload["started_at"] is not None
    assert payload["completed_at"] is not None
