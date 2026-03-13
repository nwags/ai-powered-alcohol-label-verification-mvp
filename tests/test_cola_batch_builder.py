from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


def _load_builder_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "cola_batch_builder.py"
    spec = importlib.util.spec_from_file_location("cola_batch_builder", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_records_jsonl(input_root: Path) -> None:
    (input_root / "json").mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "ttbid": "1001",
            "detail_url": "https://example/1001",
            "html_path": "",
            "text_path": "",
            "fields": {"TYPE OF PRODUCT": "Distilled"},
            "images": [
                {
                    "local_path": "images/Distilled/Brand/1001_brand.jpg",
                    "product_type": "Distilled",
                    "image_type": "Brand",
                    "actual_dimensions": "800 x 1200",
                    "src_url": "https://img/1001_brand.jpg",
                },
                {
                    "local_path": "images/Distilled/Signatures/1001_sig.tiff",
                    "product_type": "Distilled",
                    "image_type": "Signatures",
                    "actual_dimensions": "400 x 200",
                    "src_url": "https://img/1001_sig.tiff",
                },
            ],
        },
        {
            "ttbid": "2002",
            "detail_url": "https://example/2002",
            "html_path": "",
            "text_path": "",
            "fields": {"TYPE OF PRODUCT": "Wine"},
            "images": [
                {
                    "local_path": "images/Wine/Back/2002_back.png",
                    "product_type": "Wine",
                    "image_type": "Back",
                    "actual_dimensions": "900 x 700",
                    "src_url": "https://img/2002_back.png",
                }
            ],
        },
    ]
    records_path = input_root / "json" / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _write_images(input_root: Path) -> None:
    targets = [
        input_root / "images" / "Distilled" / "Brand" / "1001_brand.jpg",
        input_root / "images" / "Distilled" / "Signatures" / "1001_sig.tiff",
        input_root / "images" / "Wine" / "Back" / "2002_back.png",
    ]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"image-bytes")


def _make_input_root(tmp_path: Path) -> Path:
    input_root = tmp_path / "source_run"
    _write_records_jsonl(input_root)
    _write_images(input_root)
    return input_root


def _build_pack(module, *, repo_root: Path, input_root: Path, output_root: Path, mode: str = "compare", include_signatures: bool = False):
    context = module.BuildContext(repo_root=repo_root, input_root=input_root, output_root=output_root)
    return module.build_benchmark_pack(
        context,
        records_jsonl=input_root / "json" / "records.jsonl",
        product_types=None,
        label_types=None,
        include_signatures=include_signatures,
        random_count=None,
        seed=42,
        batch_size=100,
        mode=mode,
        emit_compare_json=True,
        emit_compare_in_label_only=False,
        overwrite=True,
        dry_run=False,
    )


def test_default_output_root_is_repo_relative_to_script():
    module = _load_builder_module()
    expected = Path(module.__file__).resolve().parents[1] / "cola_batches" / "benchmark_v1"
    assert module.default_output_root() == expected


def test_label_only_mode_does_not_emit_compare_files_by_default(tmp_path: Path):
    module = _load_builder_module()
    input_root = _make_input_root(tmp_path)
    output_root = tmp_path / "benchmark_label_only"
    _build_pack(module, repo_root=tmp_path, input_root=input_root, output_root=output_root, mode="label-only")

    batch_dirs = sorted(path for path in output_root.iterdir() if path.is_dir())
    assert batch_dirs
    for batch_dir in batch_dirs:
        csv_files = list(batch_dir.glob("*.csv"))
        json_files = [path for path in batch_dir.glob("*.json") if not path.name.endswith("_manifest.json")]
        assert not csv_files
        assert not json_files
        assert list(batch_dir.glob("*_images.zip"))
        assert list(batch_dir.glob("*_manifest.json"))


def test_json_paths_are_repo_relative_posix(tmp_path: Path):
    module = _load_builder_module()
    input_root = _make_input_root(tmp_path)
    repo_root = tmp_path
    output_root = tmp_path / "cola_batches" / "benchmark_v1"

    _build_pack(module, repo_root=repo_root, input_root=input_root, output_root=output_root)

    meta = json.loads((output_root / "benchmark_meta.json").read_text(encoding="utf-8"))
    index = json.loads((output_root / "batch_index.json").read_text(encoding="utf-8"))
    manifest_path = tmp_path / index["batches"][0]["manifest_json"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not str(meta["source_input_path"]).startswith("/")
    assert "\\" not in str(meta["source_input_path"])

    first = index["batches"][0]
    for key in ("directory", "images_zip", "manifest_json"):
        assert not str(first[key]).startswith("/")
        assert "\\" not in str(first[key])

    assert manifest["images_zip"].endswith("_images.zip")


def test_signatures_excluded_by_default_and_counted(tmp_path: Path):
    module = _load_builder_module()
    input_root = _make_input_root(tmp_path)
    output_root = tmp_path / "benchmark"
    _build_pack(module, repo_root=tmp_path, input_root=input_root, output_root=output_root, include_signatures=False)

    meta = json.loads((output_root / "benchmark_meta.json").read_text(encoding="utf-8"))
    index = json.loads((output_root / "batch_index.json").read_text(encoding="utf-8"))

    assert meta["excluded_reason_counts"].get("signatures_excluded", 0) == 1
    assert all(batch["label_type"] in {"Brand", "Back", "Other"} for batch in index["batches"])


def test_signatures_can_be_included_with_flag(tmp_path: Path):
    module = _load_builder_module()
    input_root = _make_input_root(tmp_path)
    output_root = tmp_path / "benchmark_with_signatures"
    _build_pack(module, repo_root=tmp_path, input_root=input_root, output_root=output_root, include_signatures=True)

    index = json.loads((output_root / "batch_index.json").read_text(encoding="utf-8"))
    assert any(batch["label_type"] == "Signatures" for batch in index["batches"])


def test_compare_csv_and_json_rows_are_equivalent(tmp_path: Path):
    module = _load_builder_module()
    input_root = _make_input_root(tmp_path)
    output_root = tmp_path / "benchmark"
    _build_pack(module, repo_root=tmp_path, input_root=input_root, output_root=output_root, mode="compare")

    index = json.loads((output_root / "batch_index.json").read_text(encoding="utf-8"))
    first = index["batches"][0]
    csv_path = tmp_path / first["compare_csv"]
    json_path = tmp_path / first["compare_json"]

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    json_rows = json.loads(json_path.read_text(encoding="utf-8"))

    assert csv_rows == json_rows


def test_deterministic_batch_names_and_record_ids(tmp_path: Path):
    module = _load_builder_module()
    input_root = _make_input_root(tmp_path)

    output_a = tmp_path / "out_a"
    output_b = tmp_path / "out_b"
    _build_pack(module, repo_root=tmp_path, input_root=input_root, output_root=output_a)
    _build_pack(module, repo_root=tmp_path, input_root=input_root, output_root=output_b)

    index_a = json.loads((output_a / "batch_index.json").read_text(encoding="utf-8"))
    index_b = json.loads((output_b / "batch_index.json").read_text(encoding="utf-8"))

    assert [row["batch_name"] for row in index_a["batches"]] == [row["batch_name"] for row in index_b["batches"]]

    first_a = index_a["batches"][0]
    first_b = index_b["batches"][0]

    manifest_a_path = tmp_path / first_a["manifest_json"]
    manifest_b_path = tmp_path / first_b["manifest_json"]
    manifest_a = json.loads(manifest_a_path.read_text(encoding="utf-8"))
    manifest_b = json.loads(manifest_b_path.read_text(encoding="utf-8"))

    ids_a = [record["record_id"] for record in manifest_a["records"]]
    ids_b = [record["record_id"] for record in manifest_b["records"]]
    assert ids_a == ids_b
