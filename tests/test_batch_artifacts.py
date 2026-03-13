from pathlib import Path
import json

from app.services import batch_artifacts


def test_batch_artifact_paths_and_urls_are_consistent(tmp_path: Path):
    root = tmp_path / "runtime"
    batch_id = "batch-abc123"

    expected_dir = root / "outputs" / "batch" / batch_id
    assert batch_artifacts.batch_dir(root, batch_id) == expected_dir
    assert batch_artifacts.batch_summary_json_path(root, batch_id) == expected_dir / "summary.json"
    assert batch_artifacts.batch_summary_csv_path(root, batch_id) == expected_dir / "summary.csv"
    assert batch_artifacts.batch_images_dir(root, batch_id) == expected_dir / "images"

    assert batch_artifacts.batch_report_url(batch_id) == f"/ui/batch/{batch_id}"
    assert batch_artifacts.batch_summary_json_url(batch_id) == f"/storage/outputs/batch/{batch_id}/summary.json"
    assert batch_artifacts.batch_summary_csv_url(batch_id) == f"/storage/outputs/batch/{batch_id}/summary.csv"
    assert batch_artifacts.batch_detail_url(batch_id, "img-001") == f"/ui/batch/{batch_id}/record/img-001"
    assert batch_artifacts.batch_image_url(batch_id, "nested/path/label1.jpg") == f"/storage/outputs/batch/{batch_id}/images/label1.jpg"


def test_load_batch_summary_payload_uses_shared_summary_path(tmp_path: Path):
    root = tmp_path / "runtime"
    batch_id = "batch-abc123"
    payload = {"batch_id": batch_id, "summary": {"total": 1}}
    summary_path = batch_artifacts.batch_summary_json_path(root, batch_id)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = batch_artifacts.load_batch_summary_payload(root, batch_id)

    assert loaded == payload
    assert batch_artifacts.load_batch_summary_payload(root, "missing-batch") is None


def test_save_batch_summary_payload_overwrites_atomically(tmp_path: Path):
    root = tmp_path / "runtime"
    batch_id = "batch-atomic"
    first = {"batch_id": batch_id, "status": "queued", "processed_records": 0}
    second = {"batch_id": batch_id, "status": "completed", "processed_records": 2}

    first_path = batch_artifacts.save_batch_summary_payload(root, batch_id, first)
    second_path = batch_artifacts.save_batch_summary_payload(root, batch_id, second)

    assert first_path == second_path
    loaded = batch_artifacts.load_batch_summary_payload(root, batch_id)
    assert loaded == second


def test_load_batch_summary_payload_returns_none_for_malformed_json(tmp_path: Path):
    root = tmp_path / "runtime"
    batch_id = "batch-bad-json"
    summary_path = batch_artifacts.batch_summary_json_path(root, batch_id)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("{bad-json", encoding="utf-8")

    assert batch_artifacts.load_batch_summary_payload(root, batch_id) is None
