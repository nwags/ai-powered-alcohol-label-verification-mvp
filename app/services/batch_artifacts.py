from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def batch_dir(storage_root: Path, batch_id: str) -> Path:
    return Path(storage_root) / "outputs" / "batch" / batch_id


def batch_summary_json_path(storage_root: Path, batch_id: str) -> Path:
    return batch_dir(storage_root, batch_id) / "summary.json"


def batch_summary_csv_path(storage_root: Path, batch_id: str) -> Path:
    return batch_dir(storage_root, batch_id) / "summary.csv"


def batch_images_dir(storage_root: Path, batch_id: str) -> Path:
    return batch_dir(storage_root, batch_id) / "images"


def batch_summary_json_url(batch_id: str) -> str:
    return f"/storage/outputs/batch/{batch_id}/summary.json"


def batch_summary_csv_url(batch_id: str) -> str:
    return f"/storage/outputs/batch/{batch_id}/summary.csv"


def batch_report_url(batch_id: str) -> str:
    return f"/ui/batch/{batch_id}"


def batch_image_url(batch_id: str, filename: str) -> str:
    safe_name = Path(filename).name
    return f"/storage/outputs/batch/{batch_id}/images/{safe_name}"


def batch_detail_url(batch_id: str, record_id: str) -> str:
    return f"/ui/batch/{batch_id}/record/{record_id}"


def load_batch_summary_payload(storage_root: Path, batch_id: str) -> dict[str, Any] | None:
    summary_path = batch_summary_json_path(storage_root, batch_id)
    if not summary_path.exists():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def save_batch_summary_payload(storage_root: Path, batch_id: str, payload: dict[str, Any]) -> Path:
    summary_path = batch_summary_json_path(storage_root, batch_id)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = summary_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(summary_path)
    return summary_path
