import csv
import io
import json
import time
import uuid
import zipfile
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.domain.enums import FieldStatus, OverallStatus
from app.domain.models import ApplicationData, BatchResponse, BatchResult, BatchSummary
from app.services.matching_service import build_field_results
from app.services.parser_service import parse_ocr_text

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService


class BatchService:
    """In-process batch analyzer for MVP demos.

    This service intentionally avoids background workers and external queues.
    It keeps execution deterministic and simple for local/Azure demo usage.
    """

    def __init__(
        self,
        storage_dir: Path,
        max_records: int = 200,
        max_images: int = 500,
    ) -> None:
        self.storage_dir = storage_dir
        self.max_records = max_records
        self.max_images = max_images

    def analyze(
        self,
        batch_file_bytes: bytes,
        batch_filename: str,
        images_archive_bytes: bytes | None,
        ocr_service: "OCRService",
    ) -> BatchResponse:
        records = _parse_batch_records(batch_file_bytes, batch_filename)
        if len(records) > self.max_records:
            raise ValueError(f"Batch contains {len(records)} records, which exceeds the limit of {self.max_records}.")

        images_by_name = _extract_images_from_zip(images_archive_bytes, max_images=self.max_images) if images_archive_bytes else {}

        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        results: list[BatchResult] = []
        errors: list[str] = []

        for index, record in enumerate(records, start=1):
            result = self._analyze_record(record=record, row_index=index, images_by_name=images_by_name, ocr_service=ocr_service)
            results.append(result)
            if result.main_reason and result.overall_status.value == "review" and result.main_reason.startswith("Image"):
                errors.append(f"{result.record_id}: {result.main_reason}")

        summary = _summarize(results)
        artifacts = self._write_summary_artifacts(batch_id=batch_id, results=results, summary=summary)
        return BatchResponse(batch_id=batch_id, summary=summary, results=results, artifacts=artifacts, errors=errors)

    def _analyze_record(
        self,
        record: dict[str, Any],
        row_index: int,
        images_by_name: dict[str, bytes],
        ocr_service: "OCRService",
    ) -> BatchResult:
        started = time.perf_counter()
        record_id = str(record.get("record_id") or f"row-{row_index:03d}")
        image_filename = _extract_image_filename(record)
        if not image_filename:
            return BatchResult(
                record_id=record_id,
                request_id=str(uuid.uuid4()),
                overall_status=OverallStatus.REVIEW,
                image_filename=None,
                main_reason="Image filename missing in batch record.",
                timing_ms=int((time.perf_counter() - started) * 1000),
            )

        image_bytes = images_by_name.get(image_filename.lower())
        if image_bytes is None:
            return BatchResult(
                record_id=record_id,
                request_id=str(uuid.uuid4()),
                overall_status=OverallStatus.REVIEW,
                image_filename=image_filename,
                main_reason="Image not found in uploaded ZIP archive.",
                timing_ms=int((time.perf_counter() - started) * 1000),
            )

        application = ApplicationData.model_validate(record)
        ocr, ocr_errors = ocr_service.run_ocr_bytes(image_bytes, source_label=image_filename)
        parsed = parse_ocr_text(ocr)
        field_results, overall_status, review_reasons = build_field_results(application, parsed)

        main_reason = _pick_main_reason(field_results=field_results, review_reasons=review_reasons, ocr_errors=ocr_errors)
        return BatchResult(
            record_id=record_id,
            request_id=str(uuid.uuid4()),
            overall_status=overall_status,
            image_filename=image_filename,
            main_reason=main_reason,
            timing_ms=int((time.perf_counter() - started) * 1000),
        )

    def _write_summary_artifacts(self, batch_id: str, results: list[BatchResult], summary: BatchSummary) -> dict[str, str]:
        output_dir = self.storage_dir / "outputs" / "batch" / batch_id
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "summary.json"
        csv_path = output_dir / "summary.csv"

        json_payload = {
            "batch_id": batch_id,
            "summary": summary.model_dump(),
            "results": [result.model_dump() for result in results],
        }
        json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

        with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=["record_id", "image_filename", "overall_status", "main_reason", "timing_ms", "request_id"],
            )
            writer.writeheader()
            for row in results:
                writer.writerow(
                    {
                        "record_id": row.record_id,
                        "image_filename": row.image_filename or "",
                        "overall_status": row.overall_status.value,
                        "main_reason": row.main_reason or "",
                        "timing_ms": row.timing_ms,
                        "request_id": row.request_id,
                    }
                )

        return {
            "summary_json_url": f"/storage/outputs/batch/{batch_id}/summary.json",
            "summary_csv_url": f"/storage/outputs/batch/{batch_id}/summary.csv",
        }


def _parse_batch_records(batch_file_bytes: bytes, batch_filename: str) -> list[dict[str, Any]]:
    extension = Path(batch_filename or "").suffix.lower()
    if extension == ".json":
        try:
            payload = json.loads(batch_file_bytes.decode("utf-8"))
        except JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON batch file: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError("JSON batch file must contain an array of records.")
        return [dict(item) for item in payload]

    if extension == ".csv":
        try:
            text = batch_file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV batch file must be UTF-8 encoded.") from exc
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(row) for row in reader]
        if reader.fieldnames is None:
            raise ValueError("CSV batch file is missing a header row.")
        return rows

    raise ValueError("Batch file must be .csv or .json")


def _extract_images_from_zip(images_archive_bytes: bytes, max_images: int) -> dict[str, bytes]:
    images_by_name: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(images_archive_bytes)) as archive:
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                basename = Path(member).name.lower()
                images_by_name[basename] = archive.read(member)
                if len(images_by_name) > max_images:
                    raise ValueError(f"Image ZIP contains more than {max_images} files.")
    except zipfile.BadZipFile as exc:
        raise ValueError("images_archive must be a valid .zip file.") from exc
    return images_by_name


def _extract_image_filename(record: dict[str, Any]) -> str | None:
    for key in ("image_filename", "filename", "image_file", "image"):
        value = record.get(key)
        if value and isinstance(value, str):
            return Path(value).name
    return None


def _pick_main_reason(
    field_results: dict[str, Any],
    review_reasons: list[str],
    ocr_errors: list[str],
) -> str:
    if ocr_errors:
        return ocr_errors[0]

    for field in field_results.values():
        if field.status == FieldStatus.MISMATCH:
            return field.notes or "Detected mismatch."
    if review_reasons:
        return review_reasons[0]
    for field in field_results.values():
        if field.status == FieldStatus.REVIEW:
            return field.notes or "Needs reviewer attention."
    return "No major issues detected."


def _summarize(results: list[BatchResult]) -> BatchSummary:
    counts = {"match": 0, "normalized_match": 0, "mismatch": 0, "review": 0}
    for result in results:
        counts[result.overall_status.value] += 1
    return BatchSummary(
        total=len(results),
        match=counts["match"],
        normalized_match=counts["normalized_match"],
        mismatch=counts["mismatch"],
        review=counts["review"],
    )
