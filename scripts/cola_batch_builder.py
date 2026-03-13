#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover - optional for script runtime
    BeautifulSoup = None
    Tag = object

BENCHMARK_VERSION = "benchmark_v1"
BENCHMARK_NAME = "ocr_benchmark"

CANONICAL_PRODUCT_TYPES = {"Beer", "Wine", "Distilled", "Unknown"}
CANONICAL_LABEL_TYPES = {"Brand", "Back", "Other", "Signatures"}
BATCH_LABEL_TYPES = {"Brand", "Back", "Other"}

CSV_HEADER = [
    "record_id",
    "image_filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler_producer",
    "country_of_origin",
    "government_warning",
]


@dataclass(frozen=True)
class BatchItem:
    ttbid: str
    product_type: str
    label_type: str
    actual_dimensions: str
    image_src_url: str
    image_relpath: str
    image_filename: str
    detail_url: str
    html_path: str
    text_path: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class BuildContext:
    repo_root: Path
    input_root: Path
    output_root: Path


def normalize_space(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def safe_name(value: str) -> str:
    text = normalize_space(value)
    text = text.replace("/", "_").replace("\\", "_")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = text.strip("._")
    return text or "unknown"


def canonical_product_type(value: str) -> str:
    normalized = normalize_space(value).lower()
    if normalized == "wine":
        return "Wine"
    if normalized in {"beer", "malt beverage", "malt_beverage"}:
        return "Beer"
    if normalized in {"distilled", "distilled spirits", "distilled_spirits"}:
        return "Distilled"
    return "Unknown"


def canonical_label_type(value: str) -> str:
    normalized = normalize_space(value).lower()
    if normalized == "brand":
        return "Brand"
    if normalized == "back":
        return "Back"
    if normalized == "other":
        return "Other"
    if normalized == "signatures":
        return "Signatures"
    return "Other"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def default_output_root() -> Path:
    return repo_root_from_script() / "cola_batches" / BENCHMARK_VERSION


def repo_rel_posix(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    base = repo_root.resolve()
    try:
        rel = resolved.relative_to(base)
    except ValueError:
        rel = Path("..") / Path(resolved.as_posix().lstrip("/"))
    return PurePosixPath(rel).as_posix()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def infer_product_type_from_path(image_relpath: str) -> str:
    for part in Path(image_relpath).parts:
        if part in CANONICAL_PRODUCT_TYPES:
            return part
    return "Unknown"


def infer_label_type_from_path(image_relpath: str) -> str:
    for part in Path(image_relpath).parts:
        if part in CANONICAL_LABEL_TYPES:
            return part
    return "Other"


def pick_first_nonempty(values: Iterable[str]) -> str:
    for value in values:
        text = normalize_space(value)
        if text:
            return text
    return ""


def normalize_label_text(text: str) -> str:
    text = normalize_space(text)
    return re.sub(r"\s+", " ", text).strip()


def read_html_field_map(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists() or BeautifulSoup is None:
        return out

    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    for td in soup.find_all("td"):
        children = [child for child in td.children if isinstance(child, Tag)]
        idx = 0
        while idx < len(children):
            node = children[idx]
            classes = set(node.get("class") or [])
            if node.name == "div" and ("label" in classes or "boldlabel" in classes):
                label = normalize_label_text(node.get_text(" ", strip=True))
                data_parts: list[str] = []

                j = idx + 1
                while j < len(children):
                    nxt = children[j]
                    nxt_classes = set(nxt.get("class") or [])
                    if nxt.name == "div" and ("label" in nxt_classes or "boldlabel" in nxt_classes):
                        break
                    if (nxt.name == "div" and "data" in nxt_classes) or (nxt.name == "p" and "data" in nxt_classes):
                        value = normalize_space(nxt.get_text(" ", strip=True))
                        if value and value != "\xa0":
                            data_parts.append(value)
                    j += 1

                value = normalize_space(" ".join(data_parts))
                if label and label not in out:
                    out[label] = value
                idx = j
                continue
            idx += 1

    if not any("GOVERNMENT WARNING" in key.upper() for key in out):
        for tag in soup.find_all(["div", "p"], class_="data"):
            text = normalize_space(tag.get_text(" ", strip=True))
            if "GOVERNMENT WARNING" in text.upper():
                out["GOVERNMENT WARNING"] = text
                break

    return out


def find_html_value_by_patterns(html_fields: dict[str, str], patterns: Sequence[str]) -> str:
    regexes = [re.compile(pattern, flags=re.I) for pattern in patterns]
    for label, value in html_fields.items():
        if not value:
            continue
        if any(regex.search(label) for regex in regexes):
            return value
    return ""


def derive_brand_name(html_fields: dict[str, str]) -> str:
    return find_html_value_by_patterns(html_fields, [r"\bBRAND NAME\b", r"^\d+[a-z]?\.\s*BRAND NAME\b"])


def derive_class_type(html_fields: dict[str, str]) -> str:
    return find_html_value_by_patterns(html_fields, [r"\bCLASS/TYPE DESCRIPTION\b", r"\bCLASS/?TYPE\b", r"\bCLASS TYPE\b"])


def derive_alcohol_content(html_fields: dict[str, str]) -> str:
    return find_html_value_by_patterns(html_fields, [r"\bALCOHOL CONTENT\b"])


def derive_net_contents(html_fields: dict[str, str]) -> str:
    return find_html_value_by_patterns(html_fields, [r"\bNET CONTENTS\b", r"\bNET CONTENT\b"])


def derive_bottler_producer(html_fields: dict[str, str]) -> str:
    return find_html_value_by_patterns(
        html_fields,
        [
            r"\bNAME AND ADDRESS OF APPLICANT\b",
            r"\bNAME AND ADDRESS OF BOTTLER\b",
            r"\bBOTTLER\b",
            r"\bPRODUCER\b",
            r"\bBOTTLED BY\b",
            r"\bIMPORTED BY\b",
            r"\bSOURCE OF PRODUCT\b",
        ],
    )


def derive_country_of_origin(html_fields: dict[str, str]) -> str:
    return find_html_value_by_patterns(html_fields, [r"\bCOUNTRY OF ORIGIN\b", r"^\d+[a-z]?\.\s*COUNTRY\b", r"\bCOUNTRY\b"])


def derive_government_warning(html_fields: dict[str, str]) -> str:
    direct = find_html_value_by_patterns(html_fields, [r"\bGOVERNMENT WARNING\b"])
    if direct:
        return direct
    for value in html_fields.values():
        if "GOVERNMENT WARNING" in value.upper():
            return value
    return ""


def build_compare_row(record_id: str, image_filename: str, html_fields: dict[str, str]) -> dict[str, str]:
    return {
        "record_id": record_id,
        "image_filename": image_filename,
        "brand_name": derive_brand_name(html_fields),
        "class_type": derive_class_type(html_fields),
        "alcohol_content": derive_alcohol_content(html_fields),
        "net_contents": derive_net_contents(html_fields),
        "bottler_producer": derive_bottler_producer(html_fields),
        "country_of_origin": derive_country_of_origin(html_fields),
        "government_warning": derive_government_warning(html_fields),
    }


def make_zip_filename(ttbid: str, label_type: str, actual_dimensions: str, ordinal: int, suffix: str) -> str:
    dim = safe_name(actual_dimensions) if normalize_space(actual_dimensions) else "unknown"
    label = safe_name(label_type)
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{safe_name(ttbid)}__{label}__{dim}__{ordinal}{ext}"


def find_records_jsonl(input_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    candidates = [input_root / "json" / "records.jsonl", input_root / "records.jsonl"]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("Could not find records.jsonl. Use --records-jsonl.")


def parse_csv_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [normalize_space(piece) for piece in value.split(",")]
    parts = [piece for piece in parts if piece]
    return parts or None


def parse_items(input_root: Path, records_jsonl: Path) -> list[BatchItem]:
    raw_records = read_jsonl(records_jsonl)
    items: list[BatchItem] = []

    for record in raw_records:
        ttbid = normalize_space(record.get("ttbid")) or "unknown"
        detail_url = normalize_space(record.get("detail_url"))
        html_path = normalize_space(record.get("html_path"))
        text_path = normalize_space(record.get("text_path"))
        fields = record.get("fields") or {}
        images = record.get("images") or []

        for idx, img in enumerate(images, 1):
            image_relpath = normalize_space(img.get("local_path"))
            if not image_relpath:
                continue

            product_type = canonical_product_type(
                pick_first_nonempty(
                    [
                        normalize_space(img.get("product_type")),
                        normalize_space(fields.get("TYPE OF PRODUCT")),
                        infer_product_type_from_path(image_relpath),
                    ]
                )
            )
            label_type = canonical_label_type(
                pick_first_nonempty([normalize_space(img.get("image_type")), infer_label_type_from_path(image_relpath)])
            )

            src_path = input_root / image_relpath
            suffix = src_path.suffix.lower() or ".bin"
            image_filename = make_zip_filename(
                ttbid=ttbid,
                label_type=label_type,
                actual_dimensions=normalize_space(img.get("actual_dimensions")),
                ordinal=idx,
                suffix=suffix,
            )

            items.append(
                BatchItem(
                    ttbid=ttbid,
                    product_type=product_type,
                    label_type=label_type,
                    actual_dimensions=normalize_space(img.get("actual_dimensions")),
                    image_src_url=normalize_space(img.get("src_url")),
                    image_relpath=image_relpath,
                    image_filename=image_filename,
                    detail_url=detail_url,
                    html_path=html_path,
                    text_path=text_path,
                    fields=fields,
                )
            )

    items.sort(key=lambda item: (item.product_type, item.label_type, item.ttbid, item.image_relpath, item.image_filename))
    return items


def apply_filters(
    items: Sequence[BatchItem],
    *,
    product_types: Sequence[str] | None,
    label_types: Sequence[str] | None,
    include_signatures: bool,
) -> tuple[list[BatchItem], Counter[str]]:
    wanted_products = {canonical_product_type(value) for value in product_types} if product_types else None
    wanted_labels = {canonical_label_type(value) for value in label_types} if label_types else None

    included: list[BatchItem] = []
    excluded = Counter()

    for item in items:
        if not include_signatures and item.label_type == "Signatures":
            excluded["signatures_excluded"] += 1
            continue
        if wanted_products is not None and item.product_type not in wanted_products:
            excluded["product_type_filtered"] += 1
            continue
        if wanted_labels is not None and item.label_type not in wanted_labels:
            excluded["label_type_filtered"] += 1
            continue
        if item.label_type not in BATCH_LABEL_TYPES and not include_signatures:
            excluded["non_batch_label_type"] += 1
            continue
        included.append(item)

    return included, excluded


def apply_sampling(items: Sequence[BatchItem], random_count: int | None, seed: int) -> tuple[list[BatchItem], int]:
    ordered = list(items)
    if random_count is None or random_count <= 0 or random_count >= len(ordered):
        return ordered, 0
    rng = random.Random(seed)
    sampled = rng.sample(ordered, random_count)
    sampled.sort(key=lambda item: (item.product_type, item.label_type, item.ttbid, item.image_relpath, item.image_filename))
    return sampled, len(ordered) - len(sampled)


def partition_batches(items: Sequence[BatchItem], batch_size: int) -> list[tuple[str, str, list[BatchItem]]]:
    grouped: dict[tuple[str, str], list[BatchItem]] = defaultdict(list)
    for item in items:
        grouped[(item.product_type, item.label_type)].append(item)

    partitions: list[tuple[str, str, list[BatchItem]]] = []
    for key in sorted(grouped.keys()):
        product_type, label_type = key
        rows = grouped[key]
        if batch_size <= 0:
            partitions.append((product_type, label_type, rows))
            continue
        for idx in range(0, len(rows), batch_size):
            partitions.append((product_type, label_type, rows[idx : idx + batch_size]))
    return partitions


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)


def write_csv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: normalize_space(row.get(key, "")) for key in CSV_HEADER})


def build_record_id(item: BatchItem, local_counter: int) -> str:
    return f"cola-{safe_name(item.ttbid).lower()}-{item.label_type.lower()}-{local_counter:03d}"


def write_batch_outputs(
    context: BuildContext,
    *,
    batch_id: str,
    batch_name: str,
    product_type: str,
    label_type: str,
    items: Sequence[BatchItem],
    mode: str,
    emit_compare_json: bool,
    emit_compare_in_label_only: bool,
    html_field_cache: dict[str, dict[str, str]],
) -> dict[str, Any]:
    batch_dir = context.output_root / batch_name
    ensure_dir(batch_dir)

    zip_name = f"{batch_name}_images.zip"
    zip_path = batch_dir / zip_name

    compare_rows: list[dict[str, str]] = []
    manifest_records: list[dict[str, Any]] = []

    seen_filenames: set[str] = set()
    local_seq = 1

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in items:
            src_image = context.input_root / item.image_relpath
            if not src_image.exists():
                raise FileNotFoundError(f"Missing image: {src_image}")

            image_filename = item.image_filename
            if image_filename in seen_filenames:
                stem = Path(image_filename).stem
                suffix = Path(image_filename).suffix
                disambig = 2
                while f"{stem}__dup{disambig}{suffix}" in seen_filenames:
                    disambig += 1
                image_filename = f"{stem}__dup{disambig}{suffix}"
            seen_filenames.add(image_filename)
            archive.write(src_image, arcname=image_filename)

            record_id = build_record_id(item, local_counter=local_seq)
            local_seq += 1

            html_fields: dict[str, str] = {}
            html_key = normalize_space(item.html_path)
            if html_key:
                if html_key not in html_field_cache:
                    html_field_cache[html_key] = read_html_field_map(context.input_root / html_key)
                html_fields = html_field_cache[html_key]

            compare_row = build_compare_row(record_id=record_id, image_filename=image_filename, html_fields=html_fields)
            compare_rows.append(compare_row)

            manifest_records.append(
                {
                    "record_id": record_id,
                    "ttbid": item.ttbid,
                    "image_filename": image_filename,
                    "image_relpath": item.image_relpath,
                    "detail_url": item.detail_url,
                    "image_src_url": item.image_src_url,
                    "html_path": item.html_path,
                    "text_path": item.text_path,
                    "actual_dimensions": item.actual_dimensions,
                    "product_type": item.product_type,
                    "label_type": item.label_type,
                    "compare_fields": compare_row,
                }
            )

    write_compare = mode == "compare" or (mode == "label-only" and emit_compare_in_label_only and len(compare_rows) > 0)

    csv_name: str | None = None
    json_name: str | None = None
    if write_compare:
        csv_name = f"{batch_name}.csv"
        write_csv(batch_dir / csv_name, compare_rows)
        if emit_compare_json:
            json_name = f"{batch_name}.json"
            write_json(batch_dir / json_name, compare_rows)

    manifest_name = f"{batch_name}_manifest.json"
    manifest_payload = {
        "batch_id": batch_id,
        "batch_name": batch_name,
        "benchmark_version": BENCHMARK_VERSION,
        "product_type": product_type,
        "label_type": label_type,
        "record_count": len(manifest_records),
        "image_count": len(manifest_records),
        "compare_csv": csv_name,
        "compare_json": json_name,
        "images_zip": zip_name,
        "records": manifest_records,
    }
    write_json(batch_dir / manifest_name, manifest_payload)

    return {
        "batch_id": batch_id,
        "batch_name": batch_name,
        "product_type": product_type,
        "label_type": label_type,
        "record_count": len(manifest_records),
        "image_count": len(manifest_records),
        "directory": repo_rel_posix(batch_dir, context.repo_root),
        "images_zip": repo_rel_posix(batch_dir / zip_name, context.repo_root),
        "compare_csv": repo_rel_posix(batch_dir / csv_name, context.repo_root) if csv_name else None,
        "compare_json": repo_rel_posix(batch_dir / json_name, context.repo_root) if json_name else None,
        "manifest_json": repo_rel_posix(batch_dir / manifest_name, context.repo_root),
        "has_compare_csv": bool(csv_name),
        "has_compare_json": bool(json_name),
    }


def build_benchmark_pack(
    context: BuildContext,
    *,
    records_jsonl: Path,
    product_types: Sequence[str] | None,
    label_types: Sequence[str] | None,
    include_signatures: bool,
    random_count: int | None,
    seed: int,
    batch_size: int,
    mode: str,
    emit_compare_json: bool,
    emit_compare_in_label_only: bool,
    overwrite: bool,
    dry_run: bool,
) -> dict[str, Any]:
    all_items = parse_items(context.input_root, records_jsonl)
    included, excluded_reasons = apply_filters(
        all_items,
        product_types=product_types,
        label_types=label_types,
        include_signatures=include_signatures,
    )
    sampled, sampled_out = apply_sampling(included, random_count=random_count, seed=seed)
    if sampled_out:
        excluded_reasons["random_sampled_out"] += sampled_out

    category_counts = {
        "product_type": dict(sorted(Counter(item.product_type for item in sampled).items())),
        "label_type": dict(sorted(Counter(item.label_type for item in sampled).items())),
    }

    partitions = partition_batches(sampled, batch_size=batch_size)

    if dry_run:
        return {
            "total_records": len(all_items),
            "included_records": len(sampled),
            "excluded_records": len(all_items) - len(sampled),
            "excluded_reason_counts": dict(excluded_reasons),
            "batch_count": len(partitions),
            "category_counts": category_counts,
            "output_root": str(context.output_root),
        }

    if context.output_root.exists() and any(context.output_root.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"Output root already exists and is non-empty: {context.output_root}. Use --overwrite to replace."
            )
        shutil.rmtree(context.output_root)
    ensure_dir(context.output_root)
    html_field_cache: dict[str, dict[str, str]] = {}

    index_rows: list[dict[str, Any]] = []
    for batch_number, (product_type, label_type, batch_items) in enumerate(partitions, start=1):
        batch_id = f"batch_{batch_number:04d}"
        batch_name = f"{batch_id}__{product_type}__{label_type}"
        index_entry = write_batch_outputs(
            context,
            batch_id=batch_id,
            batch_name=batch_name,
            product_type=product_type,
            label_type=label_type,
            items=batch_items,
            mode=mode,
            emit_compare_json=emit_compare_json,
            emit_compare_in_label_only=emit_compare_in_label_only,
            html_field_cache=html_field_cache,
        )
        index_rows.append(index_entry)

    benchmark_meta = {
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "builder_script": repo_rel_posix(Path(__file__).resolve(), context.repo_root),
        "source_input_path": repo_rel_posix(context.input_root, context.repo_root),
        "source_runs": [repo_rel_posix(context.input_root, context.repo_root)],
        "category_axes": {
            "product_type": ["Beer", "Wine", "Distilled"],
            "label_type": ["Brand", "Back", "Other"],
        },
        "total_records": len(all_items),
        "included_records": len(sampled),
        "excluded_records": len(all_items) - len(sampled),
        "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
        "category_counts": category_counts,
        "batch_count": len(index_rows),
        "notes": "Benchmark pack built from COLA scrape outputs.",
    }

    batch_index = {
        "benchmark_version": BENCHMARK_VERSION,
        "batches": index_rows,
    }

    write_json(context.output_root / "benchmark_meta.json", benchmark_meta)
    write_json(context.output_root / "batch_index.json", batch_index)

    return {
        "total_records": len(all_items),
        "included_records": len(sampled),
        "excluded_records": len(all_items) - len(sampled),
        "batch_count": len(index_rows),
        "output_root": str(context.output_root),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build benchmark-pack-compatible batch artifacts from COLA scrape output.")
    parser.add_argument("--input-root", required=True, help="Root of cola_registry_scraper output")
    parser.add_argument("--records-jsonl", help="Optional explicit path to records.jsonl")
    parser.add_argument("--output-root", help="Benchmark output root (default: repo-root cola_batches/benchmark_v1)")

    parser.add_argument("--product-types", help="Comma-separated subset of Wine,Beer,Distilled,Unknown")
    parser.add_argument("--label-types", help="Comma-separated subset of Brand,Back,Other,Signatures")
    parser.add_argument("--include-signatures", action="store_true", help="Include Signatures in emitted benchmark batches")
    parser.add_argument("--random-count", type=int, help="Random sample size after filtering")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=100)

    parser.add_argument(
        "--mode",
        choices=["label-only", "compare"],
        default="compare",
        help="label-only -> ZIP + manifest only by default; compare -> ZIP + CSV (+ JSON by default)",
    )
    parser.add_argument("--no-compare-json", action="store_true", help="Suppress JSON compare file emission when compare is emitted")
    parser.add_argument(
        "--emit-compare-in-label-only",
        action="store_true",
        help="In label-only mode, emit compare CSV/JSON when compare rows are available",
    )
    parser.add_argument("--overwrite", action="store_true", help="Allow writing into an existing non-empty output root")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing files")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    repo_root = repo_root_from_script()
    input_root = Path(args.input_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else default_output_root().resolve()
    records_jsonl = find_records_jsonl(input_root, Path(args.records_jsonl).resolve() if args.records_jsonl else None)

    context = BuildContext(repo_root=repo_root, input_root=input_root, output_root=output_root)

    product_types = parse_csv_list(args.product_types)
    label_types = parse_csv_list(args.label_types)

    summary = build_benchmark_pack(
        context,
        records_jsonl=records_jsonl,
        product_types=product_types,
        label_types=label_types,
        include_signatures=args.include_signatures,
        random_count=args.random_count,
        seed=args.seed,
        batch_size=args.batch_size,
        mode=args.mode,
        emit_compare_json=not args.no_compare_json,
        emit_compare_in_label_only=args.emit_compare_in_label_only,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Done. Benchmark pack written to: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
