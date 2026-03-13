import csv
import io
import json
import logging
import threading
import time
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.domain.enums import FieldStatus, LabelType, OverallStatus, ProductProfile
from app.domain.models import ApplicationData, BatchResponse, BatchResult, BatchSummary, OCREvidenceLine
from app.services.inference_service import coerce_product_profile, infer_label_type, infer_product_profile
from app.services.matching_service import build_field_results, coerce_label_type
from app.services.parser_service import parse_ocr_text
from app.services.result_presenter import build_batch_report_rows
from app.services.rule_registry import build_rule_trace
from app.services.visualization_service import create_annotated_ocr_artifact
from app.services.batch_artifacts import (
    batch_dir,
    batch_detail_url,
    batch_image_url,
    batch_images_dir,
    load_batch_summary_payload,
    save_batch_summary_payload,
    batch_report_url,
    batch_summary_csv_path,
    batch_summary_csv_url,
    batch_summary_json_url,
)

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService

logger = logging.getLogger(__name__)

FIELD_LABELS = {
    "brand_name": "Brand Name",
    "class_type": "Class / Type",
    "alcohol_content": "Alcohol Content",
    "net_contents": "Net Contents",
    "bottler_producer": "Bottler / Producer",
    "country_of_origin": "Country of Origin",
    "government_warning": "Government Warning",
}


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
        async_max_workers: int = 1,
    ) -> None:
        self.storage_dir = storage_dir
        self.max_records = max_records
        self.max_images = max_images
        self._executor = ThreadPoolExecutor(max_workers=max(1, async_max_workers), thread_name_prefix="batch-runner")
        self._jobs_lock = threading.Lock()
        self._jobs: dict[str, Future[None]] = {}

    def analyze(
        self,
        batch_file_bytes: bytes,
        batch_filename: str,
        images_archive_bytes: bytes | None,
        ocr_service: "OCRService",
        label_type: LabelType = LabelType.UNKNOWN,
        product_profile: ProductProfile = ProductProfile.UNKNOWN,
    ) -> BatchResponse:
        started = time.perf_counter()
        records = _parse_batch_records(batch_file_bytes, batch_filename)
        created_at = _iso_now()
        started_at = _iso_now()
        if len(records) > self.max_records:
            raise ValueError(f"Batch contains {len(records)} records, which exceeds the limit of {self.max_records}.")

        images_by_name = _extract_images_from_zip(images_archive_bytes, max_images=self.max_images) if images_archive_bytes else {}
        logger.info(
            "Batch compare started filename=%s records=%d images=%d label_type=%s product_profile=%s",
            batch_filename,
            len(records),
            len(images_by_name),
            label_type.value,
            product_profile.value,
        )

        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        output_dir = batch_dir(self.storage_dir, batch_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        image_urls = self._persist_batch_images(images_by_name=images_by_name, batch_id=batch_id)
        results: list[BatchResult] = []
        detail_records: list[dict[str, Any]] = []
        errors: list[str] = []

        for index, record in enumerate(records, start=1):
            logger.info("Batch compare progress %d/%d record_id=%s", index, len(records), record.get("record_id", ""))
            result, detail_record = self._analyze_record(
                record=record,
                row_index=index,
                images_by_name=images_by_name,
                image_urls=image_urls,
                ocr_service=ocr_service,
                label_type=label_type,
                product_profile=product_profile,
                evaluation_mode="compare",
            )
            results.append(result)
            detail_records.append(detail_record)
            if result.main_reason and result.overall_status.value == "review" and result.main_reason.startswith("Image"):
                errors.append(f"{result.record_id}: {result.main_reason}")

        summary = _summarize(results)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        completed_at = _iso_now()
        artifacts = self._write_summary_artifacts(
            batch_id=batch_id,
            results=results,
            summary=summary,
            detail_records=detail_records,
            batch_review_mode="batch_compare_application",
            label_type=label_type,
            product_profile=product_profile,
            elapsed_ms=elapsed_ms,
            errors=errors,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
        )
        logger.info(
            "Batch compare finished batch_id=%s total=%d elapsed_ms=%d",
            batch_id,
            len(results),
            elapsed_ms,
        )
        return BatchResponse(batch_id=batch_id, summary=summary, results=results, artifacts=artifacts, errors=errors)

    def analyze_label_only(
        self,
        images_archive_bytes: bytes,
        ocr_service: "OCRService",
        label_type: LabelType = LabelType.UNKNOWN,
        product_profile: ProductProfile = ProductProfile.UNKNOWN,
    ) -> BatchResponse:
        started = time.perf_counter()
        images_by_name = _extract_images_from_zip(images_archive_bytes, max_images=self.max_images)
        created_at = _iso_now()
        started_at = _iso_now()
        if not images_by_name:
            raise ValueError("Image ZIP archive is empty.")

        records = _build_label_only_records(images_by_name)
        logger.info(
            "Batch label-only started images=%d label_type=%s product_profile=%s",
            len(images_by_name),
            label_type.value,
            product_profile.value,
        )
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        output_dir = batch_dir(self.storage_dir, batch_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        image_urls = self._persist_batch_images(images_by_name=images_by_name, batch_id=batch_id)
        results: list[BatchResult] = []
        detail_records: list[dict[str, Any]] = []
        errors: list[str] = []

        for index, record in enumerate(records, start=1):
            logger.info("Batch label-only progress %d/%d image=%s", index, len(records), record.get("image_filename", ""))
            result, detail_record = self._analyze_record(
                record=record,
                row_index=index,
                images_by_name=images_by_name,
                image_urls=image_urls,
                ocr_service=ocr_service,
                label_type=label_type,
                product_profile=product_profile,
                evaluation_mode="label_only",
            )
            results.append(result)
            detail_records.append(detail_record)
            if result.main_reason and result.overall_status.value == "review" and result.main_reason.startswith("Image"):
                errors.append(f"{result.record_id}: {result.main_reason}")

        summary = _summarize(results)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        completed_at = _iso_now()
        artifacts = self._write_summary_artifacts(
            batch_id=batch_id,
            results=results,
            summary=summary,
            detail_records=detail_records,
            batch_review_mode="batch_label_only",
            label_type=label_type,
            product_profile=product_profile,
            elapsed_ms=elapsed_ms,
            errors=errors,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
        )
        logger.info(
            "Batch label-only finished batch_id=%s total=%d elapsed_ms=%d",
            batch_id,
            len(results),
            elapsed_ms,
        )
        return BatchResponse(batch_id=batch_id, summary=summary, results=results, artifacts=artifacts, errors=errors)

    def enqueue_compare(
        self,
        *,
        batch_file_bytes: bytes,
        batch_filename: str,
        images_archive_bytes: bytes | None,
        ocr_service: "OCRService",
        label_type: LabelType = LabelType.UNKNOWN,
        product_profile: ProductProfile = ProductProfile.UNKNOWN,
    ) -> str:
        records = _parse_batch_records(batch_file_bytes, batch_filename)
        if len(records) > self.max_records:
            raise ValueError(f"Batch contains {len(records)} records, which exceeds the limit of {self.max_records}.")
        images_by_name = _extract_images_from_zip(images_archive_bytes, max_images=self.max_images) if images_archive_bytes else {}
        batch_id = self._create_initial_batch_payload(
            total_records=len(records),
            batch_review_mode="batch_compare_application",
            label_type=label_type,
            product_profile=product_profile,
        )
        image_urls = self._persist_batch_images(images_by_name=images_by_name, batch_id=batch_id)
        self._submit_background_job(
            batch_id,
            self._run_batch_job,
            records=records,
            images_by_name=images_by_name,
            image_urls=image_urls,
            ocr_service=ocr_service,
            label_type=label_type,
            product_profile=product_profile,
            evaluation_mode="compare",
        )
        return batch_id

    def enqueue_label_only(
        self,
        *,
        images_archive_bytes: bytes,
        ocr_service: "OCRService",
        label_type: LabelType = LabelType.UNKNOWN,
        product_profile: ProductProfile = ProductProfile.UNKNOWN,
    ) -> str:
        images_by_name = _extract_images_from_zip(images_archive_bytes, max_images=self.max_images)
        if not images_by_name:
            raise ValueError("Image ZIP archive is empty.")
        records = _build_label_only_records(images_by_name)
        batch_id = self._create_initial_batch_payload(
            total_records=len(records),
            batch_review_mode="batch_label_only",
            label_type=label_type,
            product_profile=product_profile,
        )
        image_urls = self._persist_batch_images(images_by_name=images_by_name, batch_id=batch_id)
        self._submit_background_job(
            batch_id,
            self._run_batch_job,
            records=records,
            images_by_name=images_by_name,
            image_urls=image_urls,
            ocr_service=ocr_service,
            label_type=label_type,
            product_profile=product_profile,
            evaluation_mode="label_only",
        )
        return batch_id

    def _analyze_record(
        self,
        record: dict[str, Any],
        row_index: int,
        images_by_name: dict[str, bytes],
        image_urls: dict[str, str],
        ocr_service: "OCRService",
        label_type: LabelType,
        product_profile: ProductProfile,
        evaluation_mode: str,
    ) -> tuple[BatchResult, dict[str, Any]]:
        started = time.perf_counter()
        record_id = str(record.get("record_id") or f"row-{row_index:03d}")
        image_filename = _extract_image_filename(record)
        if not image_filename:
            result = BatchResult(
                record_id=record_id,
                request_id=str(uuid.uuid4()),
                overall_status=OverallStatus.REVIEW,
                image_filename=None,
                main_reason="Image filename missing in batch record.",
                timing_ms=int((time.perf_counter() - started) * 1000),
            )
            return result, self._empty_detail_payload(result=result, evaluation_mode=evaluation_mode)

        image_bytes = images_by_name.get(image_filename.lower())
        if image_bytes is None:
            result = BatchResult(
                record_id=record_id,
                request_id=str(uuid.uuid4()),
                overall_status=OverallStatus.REVIEW,
                image_filename=image_filename,
                image_url=image_urls.get(image_filename.lower()),
                main_reason="Image not found in uploaded ZIP archive.",
                timing_ms=int((time.perf_counter() - started) * 1000),
            )
            return result, self._empty_detail_payload(result=result, evaluation_mode=evaluation_mode)

        application = ApplicationData.model_validate(record)
        variant_image = None
        variant_metadata: dict[str, Any] = {}
        try:
            ocr_run = ocr_service.run_ocr_bytes(
                image_bytes,
                source_label=image_filename,
                return_variant_image=True,
                return_variant_metadata=True,
            )
        except TypeError:
            ocr_run = ocr_service.run_ocr_bytes(image_bytes, source_label=image_filename)

        if isinstance(ocr_run, tuple) and len(ocr_run) == 4:
            ocr, ocr_errors, variant_image, variant_metadata = ocr_run
        elif isinstance(ocr_run, tuple) and len(ocr_run) == 3:
            ocr, ocr_errors, variant_image = ocr_run
        else:
            ocr, ocr_errors = ocr_run
        pre_parsed = parse_ocr_text(ocr, product_profile=ProductProfile.UNKNOWN)
        profile_inference = infer_product_profile(selected_hint=product_profile, ocr=ocr, parsed=pre_parsed)
        effective_profile = coerce_product_profile(profile_inference.get("effective_profile"))
        parsed = parse_ocr_text(ocr, product_profile=effective_profile)
        label_inference = infer_label_type(
            selected_hint=label_type,
            effective_profile=effective_profile,
            ocr=ocr,
            parsed=parsed,
        )
        effective_label_type = coerce_label_type(label_inference.get("effective_label_type"))
        rule_ids_by_field: dict[str, list[str]] = {}
        if isinstance(profile_inference.get("rule_ids"), list):
            rule_ids_by_field["profile_inference"] = [str(value) for value in profile_inference["rule_ids"]]
        if isinstance(label_inference.get("rule_ids"), list):
            rule_ids_by_field["label_type_inference"] = [str(value) for value in label_inference["rule_ids"]]
        field_results, overall_status, review_reasons = build_field_results(
            application,
            parsed,
            label_type=effective_label_type,
            evaluation_mode=evaluation_mode,
            product_profile=effective_profile,
            rule_ids_by_field=rule_ids_by_field,
        )

        main_reason = _pick_main_reason(field_results=field_results, review_reasons=review_reasons, ocr_errors=ocr_errors)
        result = BatchResult(
            record_id=record_id,
            request_id=str(uuid.uuid4()),
            overall_status=overall_status,
            image_filename=image_filename,
            image_url=image_urls.get(image_filename.lower()),
            main_reason=main_reason,
            timing_ms=int((time.perf_counter() - started) * 1000),
        )
        canonical_evidence_lines: list[OCREvidenceLine] = []
        raw_evidence = variant_metadata.get("evidence_lines")
        if isinstance(raw_evidence, list):
            for raw in raw_evidence:
                if not isinstance(raw, dict):
                    continue
                try:
                    canonical_evidence_lines.append(OCREvidenceLine.model_validate(raw))
                except Exception:
                    continue

        annotated_image_url: str | None = None
        annotation_payload: dict[str, Any] | None = None
        annotation_debug: dict[str, Any] | None = None
        annotation_attempted = False
        source_variant_id = variant_metadata.get("source_variant_id")
        if (
            canonical_evidence_lines
            and isinstance(source_variant_id, str)
            and source_variant_id
        ):
            annotation_attempted = True
            bbox_space_hint = variant_metadata.get("bbox_space")
            annotation_result = create_annotated_ocr_artifact(
                image_bytes=image_bytes,
                ocr=ocr,
                storage_dir=self.storage_dir,
                parsed=parsed,
                base_image=variant_image,
                evidence_lines=canonical_evidence_lines,
                source_variant_id=source_variant_id,
                bbox_space_hint=str(bbox_space_hint) if isinstance(bbox_space_hint, str) and bbox_space_hint else "unknown",
                allow_legacy_fallback=False,
                return_metadata=True,
            )
            annotated_path, annotation_payload, annotation_debug = annotation_result
            if annotated_path:
                annotated_image_url = f"/storage/{annotated_path}"
            else:
                if not isinstance(annotation_debug, dict):
                    annotation_debug = {}
                reasons = annotation_debug.get("skip_reasons")
                if isinstance(reasons, list):
                    if "annotation_attempted_no_artifact_path" not in reasons:
                        reasons.append("annotation_attempted_no_artifact_path")
                else:
                    annotation_debug["skip_reasons"] = ["annotation_attempted_no_artifact_path"]
        if annotation_attempted and annotation_debug is None:
            annotation_debug = {"skip_reasons": ["annotation_attempted_no_artifact_path"]}
        detail = {
            "record_id": result.record_id,
            "request_id": result.request_id,
            "overall_status": result.overall_status.value,
            "image_filename": result.image_filename,
            "image_url": result.image_url,
            "main_reason": result.main_reason,
            "timing_ms": result.timing_ms,
            "evaluation_mode": evaluation_mode,
            "ocr_full_text": ocr.full_text,
            "field_rows": _field_rows_for_detail(field_results),
            "field_results": {name: result.model_dump() for name, result in field_results.items()},
            "parsed": parsed.model_dump(),
            "review_reasons": review_reasons,
            "ocr_errors": ocr_errors,
            "application": application.model_dump(),
            "inference": {"product_profile": profile_inference, "label_type": label_inference},
            "rule_trace": build_rule_trace(rule_ids_by_field),
            "annotated_image_url": annotated_image_url,
        }
        if annotation_payload is not None:
            detail["annotation"] = annotation_payload
        if annotation_debug is not None:
            detail["annotation_debug"] = annotation_debug
        return result, detail

    def _submit_background_job(self, batch_id: str, fn: Any, **kwargs: Any) -> None:
        future = self._executor.submit(fn, batch_id=batch_id, **kwargs)
        with self._jobs_lock:
            self._jobs[batch_id] = future

        def _cleanup(done_future: Future[None]) -> None:
            _ = done_future
            with self._jobs_lock:
                self._jobs.pop(batch_id, None)

        future.add_done_callback(_cleanup)

    def _create_initial_batch_payload(
        self,
        *,
        total_records: int,
        batch_review_mode: str,
        label_type: LabelType,
        product_profile: ProductProfile,
    ) -> str:
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        created_at = _iso_now()
        payload: dict[str, Any] = {
            "batch_id": batch_id,
            "status": "queued",
            "created_at": created_at,
            "started_at": None,
            "completed_at": None,
            "total_records": total_records,
            "processed_records": 0,
            "summary": BatchSummary(total=total_records, match=0, normalized_match=0, mismatch=0, review=0).model_dump(),
            "results": [],
            "record_details": [],
            "batch_review_mode": batch_review_mode,
            "label_type": label_type.value,
            "product_profile": product_profile.value,
            "elapsed_ms": 0,
            "artifacts": {
                "summary_json_url": batch_summary_json_url(batch_id),
                "summary_csv_url": batch_summary_csv_url(batch_id),
                "report_url": batch_report_url(batch_id),
            },
            "errors": [],
        }
        self._persist_summary_payload(batch_id=batch_id, payload=payload)
        return batch_id

    def _run_batch_job(
        self,
        *,
        batch_id: str,
        records: list[dict[str, Any]],
        images_by_name: dict[str, bytes],
        image_urls: dict[str, str],
        ocr_service: "OCRService",
        label_type: LabelType,
        product_profile: ProductProfile,
        evaluation_mode: str,
    ) -> None:
        started = time.perf_counter()
        payload = self.load_summary_payload(batch_id=batch_id)
        if payload is None:
            return
        current_status = str(payload.get("status") or "queued")
        if current_status not in {"queued", "running"}:
            return
        total_records = len(records)
        if isinstance(payload.get("total_records"), int) and int(payload["total_records"]) > 0:
            total_records = int(payload["total_records"])
        payload["total_records"] = total_records
        payload["status"] = "running"
        if not payload.get("started_at"):
            payload["started_at"] = _iso_now()
        payload["errors"] = []
        self._persist_summary_payload(batch_id=batch_id, payload=payload)

        results: list[BatchResult] = []
        detail_records: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            for index, record in enumerate(records, start=1):
                result, detail_record = self._analyze_record(
                    record=record,
                    row_index=index,
                    images_by_name=images_by_name,
                    image_urls=image_urls,
                    ocr_service=ocr_service,
                    label_type=label_type,
                    product_profile=product_profile,
                    evaluation_mode=evaluation_mode,
                )
                results.append(result)
                detail_records.append(detail_record)
                if result.main_reason and result.overall_status.value == "review" and result.main_reason.startswith("Image"):
                    errors.append(f"{result.record_id}: {result.main_reason}")

                processed = min(index, total_records)
                previous_processed = int(payload.get("processed_records") or 0)
                payload["processed_records"] = max(previous_processed, processed)
                payload["summary"] = _summarize(results).model_dump()
                payload["results"] = [item.model_dump() for item in results]
                payload["record_details"] = detail_records
                payload["errors"] = errors
                payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
                self._persist_summary_payload(batch_id=batch_id, payload=payload)

            payload["status"] = "completed"
            payload["completed_at"] = _iso_now()
            payload["processed_records"] = total_records
            payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            self._persist_summary_payload(batch_id=batch_id, payload=payload)
            self._write_summary_csv(batch_id=batch_id, results=results)
        except Exception as exc:  # pragma: no cover - defensive for background worker stability
            payload["status"] = "failed"
            payload["completed_at"] = _iso_now()
            processed = int(payload.get("processed_records") or 0)
            payload["processed_records"] = min(total_records, max(0, processed))
            payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            errors.append(f"batch_failed: {exc.__class__.__name__}: {exc}")
            payload["errors"] = errors
            self._persist_summary_payload(batch_id=batch_id, payload=payload)

    def _persist_summary_payload(self, *, batch_id: str, payload: dict[str, Any]) -> None:
        save_batch_summary_payload(self.storage_dir, batch_id, payload)

    def _write_summary_csv(self, *, batch_id: str, results: list[BatchResult]) -> None:
        csv_path = batch_summary_csv_path(self.storage_dir, batch_id)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
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

    def _write_summary_artifacts(
        self,
        batch_id: str,
        results: list[BatchResult],
        summary: BatchSummary,
        detail_records: list[dict[str, Any]],
        batch_review_mode: str,
        label_type: LabelType,
        product_profile: ProductProfile,
        elapsed_ms: int,
        errors: list[str],
        created_at: str,
        started_at: str,
        completed_at: str,
    ) -> dict[str, Any]:
        output_dir = batch_dir(self.storage_dir, batch_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        artifacts = {
            "summary_json_url": batch_summary_json_url(batch_id),
            "summary_csv_url": batch_summary_csv_url(batch_id),
            "report_url": batch_report_url(batch_id),
        }
        json_payload = {
            "batch_id": batch_id,
            "status": "completed",
            "created_at": created_at,
            "started_at": started_at,
            "completed_at": completed_at,
            "total_records": len(results),
            "processed_records": len(results),
            "summary": summary.model_dump(),
            "results": [result.model_dump() for result in results],
            "record_details": detail_records,
            "batch_review_mode": batch_review_mode,
            "label_type": label_type.value,
            "product_profile": product_profile.value,
            "elapsed_ms": elapsed_ms,
            "artifacts": artifacts,
            "errors": errors,
        }
        self._persist_summary_payload(batch_id=batch_id, payload=json_payload)
        self._write_summary_csv(batch_id=batch_id, results=results)

        return artifacts

    def load_summary_payload(self, *, batch_id: str) -> dict[str, Any] | None:
        payload = load_batch_summary_payload(self.storage_dir, batch_id)
        if payload is None:
            return None
        return payload

    def load_record_detail(self, *, batch_id: str, record_id: str) -> dict[str, Any] | None:
        payload = self.load_summary_payload(batch_id=batch_id)
        if payload is None:
            return None
        details = payload.get("record_details")
        if not isinstance(details, list):
            return None
        for item in details:
            if isinstance(item, dict) and str(item.get("record_id")) == record_id:
                return item
        return None

    def load_status_payload(self, *, batch_id: str) -> dict[str, Any] | None:
        payload = self.load_summary_payload(batch_id=batch_id)
        if payload is None:
            return None
        raw_results = payload.get("results", [])
        safe_results: list[BatchResult] = []
        for row in raw_results:
            if not isinstance(row, dict):
                continue
            try:
                safe_results.append(BatchResult.model_validate(row))
            except Exception:
                continue
        batch_mode = str(payload.get("batch_review_mode", "batch_label_only"))
        rows = build_batch_report_rows(safe_results, batch_mode)
        for row in rows:
            row["detail_url"] = batch_detail_url(batch_id, str(row["record_id"]))
        total_records = int(payload.get("total_records") or 0)
        processed_records = int(payload.get("processed_records") or 0)
        if total_records < 0:
            total_records = 0
        if processed_records < 0:
            processed_records = 0
        if total_records > 0:
            processed_records = min(processed_records, total_records)
        status_value = str(payload.get("status", "queued")).strip().lower()
        if status_value not in {"queued", "running", "completed", "failed"}:
            status_value = "queued"
        return {
            "batch_id": batch_id,
            "status": status_value,
            "created_at": payload.get("created_at"),
            "started_at": payload.get("started_at"),
            "completed_at": payload.get("completed_at"),
            "total_records": total_records,
            "processed_records": processed_records,
            "elapsed_ms": int(payload.get("elapsed_ms") or 0),
            "summary": payload.get("summary", {}),
            "errors": payload.get("errors", []),
            "report_url": batch_report_url(batch_id),
            "rows": rows,
            "batch_review_mode": batch_mode,
        }

    def _persist_batch_images(self, images_by_name: dict[str, bytes], batch_id: str) -> dict[str, str]:
        if not images_by_name:
            return {}
        images_dir = batch_images_dir(self.storage_dir, batch_id)
        images_dir.mkdir(parents=True, exist_ok=True)
        urls: dict[str, str] = {}
        for basename, payload in images_by_name.items():
            safe_name = Path(basename).name
            target_path = images_dir / safe_name
            target_path.write_bytes(payload)
            urls[basename] = batch_image_url(batch_id, safe_name)
        return urls

    def _empty_detail_payload(self, result: BatchResult, evaluation_mode: str) -> dict[str, Any]:
        return {
            "record_id": result.record_id,
            "request_id": result.request_id,
            "overall_status": result.overall_status.value,
            "image_filename": result.image_filename,
            "image_url": result.image_url,
            "main_reason": result.main_reason,
            "timing_ms": result.timing_ms,
            "evaluation_mode": evaluation_mode,
            "ocr_full_text": "",
            "field_rows": [],
            "field_results": {},
            "parsed": {},
            "review_reasons": [result.main_reason] if result.main_reason else [],
            "ocr_errors": [],
            "application": {},
            "inference": {"product_profile": {}, "label_type": {}},
            "rule_trace": {},
            "annotated_image_url": None,
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


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


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


def _build_label_only_records(images_by_name: dict[str, bytes]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for index, image_filename in enumerate(sorted(images_by_name.keys()), start=1):
        records.append(
            {
                "record_id": f"img-{index:03d}",
                "image_filename": image_filename,
            }
        )
    return records


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


def _field_rows_for_detail(field_results: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, label in FIELD_LABELS.items():
        result = field_results.get(field_name)
        if result is None:
            continue
        rows.append(
            {
                "field_name": field_name,
                "label": label,
                "submitted_value": result.submitted_value,
                "detected_value": result.detected_value,
                "status": result.status.value,
                "notes": result.notes,
            }
        )
    return rows
