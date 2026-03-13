from pathlib import Path

from conftest import build_test_image_bytes

from app.domain.models import OCREvidenceLine, OCRLine, OCRResult, ParsedFields
from app.services.visualization_service import (
    _resolve_coordinate_space,
    _transform_bbox_points,
    create_annotated_ocr_artifact,
)


def test_create_annotated_artifact_without_canonical_evidence_returns_no_annotation(tmp_path: Path):
    ocr = OCRResult(
        full_text="Blue Ridge Estate Vineyard & Winery\nNet cont. 750 mi",
        lines=[
            OCRLine(text="Blue Ridge Estate Vineyard & Winery", confidence=0.95, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="Net cont. 750 mi", confidence=0.91, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        return_metadata=True,
    )

    assert artifact_path is None
    assert annotation["bbox"] == []
    assert "no_canonical_evidence_lines" in debug["skip_reasons"]


def test_bbox_native_pixels_are_not_scaled():
    bbox = [[10, 20], [110, 20], [110, 80], [10, 80]]
    space = _resolve_coordinate_space(bbox=bbox, render_shape=(200, 300), source_shape=None)
    assert space == "native_pixels"
    points = _transform_bbox_points(bbox=bbox, render_shape=(200, 300), source_shape=None)
    assert points.tolist()[0] == [10, 20]


def test_bbox_normalized_are_scaled_to_render_shape():
    bbox = [[0.1, 0.2], [0.5, 0.2], [0.5, 0.6], [0.1, 0.6]]
    space = _resolve_coordinate_space(bbox=bbox, render_shape=(100, 200), source_shape=None)
    assert space == "normalized"
    points = _transform_bbox_points(bbox=bbox, render_shape=(100, 200), source_shape=None)
    assert points.tolist()[0] == [20, 20]


def test_placeholder_bbox_is_skipped():
    bbox = [[0, 0], [1, 0], [1, 1], [0, 1]]
    space = _resolve_coordinate_space(bbox=bbox, render_shape=(100, 100), source_shape=None)
    assert space == "placeholder"
    points = _transform_bbox_points(bbox=bbox, render_shape=(100, 100), source_shape=None)
    assert points.size == 0


def test_source_pixel_bbox_scales_deterministically_to_render_shape():
    bbox = [[100, 200], [300, 200], [300, 260], [100, 260]]
    space = _resolve_coordinate_space(bbox=bbox, render_shape=(500, 400), source_shape=(1000, 800))
    assert space == "scaled_from_source"
    points = _transform_bbox_points(bbox=bbox, render_shape=(500, 400), source_shape=(1000, 800))
    assert points.tolist()[0] == [50, 100]


def test_render_pixel_hint_prefers_native_pixels_when_bbox_fits_both_spaces():
    bbox = [[100, 200], [300, 200], [300, 260], [100, 260]]
    space = _resolve_coordinate_space(
        bbox=bbox,
        render_shape=(500, 400),
        source_shape=(1000, 800),
        bbox_space_hint="render_pixels",
    )
    assert space == "native_pixels"
    points = _transform_bbox_points(
        bbox=bbox,
        render_shape=(500, 400),
        source_shape=(1000, 800),
        bbox_space_hint="render_pixels",
    )
    assert points.tolist()[0] == [100, 200]


def test_create_annotated_artifact_returns_annotation_contract_with_metadata(tmp_path: Path):
    ocr = OCRResult(
        full_text="STONE'S THROW WHISKEY",
        lines=[
            OCRLine(
                text="STONE'S THROW WHISKEY",
                confidence=0.95,
                bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
            )
        ],
    )

    evidence_lines = [
        OCREvidenceLine(
            id="color_resized:line-0001",
            text="STONE'S THROW WHISKEY",
            confidence=0.95,
            bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
            bbox_space="render_pixels",
            image_variant_id="color_resized",
            source_backend="paddleocr",
        )
    ]

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        evidence_lines=evidence_lines,
        source_variant_id="color_resized",
        bbox_space_hint="render_pixels",
        return_metadata=True,
    )

    assert artifact_path is not None
    assert (tmp_path / artifact_path).exists()
    assert annotation["source_variant_id"] == "color_resized"
    assert annotation["bbox_space"] == "native_pixels"
    assert isinstance(annotation["image_width"], int)
    assert isinstance(annotation["image_height"], int)
    assert isinstance(annotation["bbox"], list) and len(annotation["bbox"]) == 1
    assert "field_links" in annotation
    assert debug["rendered_count"] == 1
    assert debug["used_fallback_evidence"] is False


def test_create_annotated_artifact_uses_variant_matched_canonical_evidence_only(tmp_path: Path):
    ocr = OCRResult(
        full_text="ONE\nTWO",
        lines=[
            OCRLine(text="ONE", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="TWO", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )
    evidence_lines = [
        OCREvidenceLine(
            id="color_resized:line-0001",
            text="ONE",
            confidence=0.95,
            bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
            bbox_space="render_pixels",
            image_variant_id="color_resized",
            source_backend="paddleocr",
        ),
        OCREvidenceLine(
            id="gray_clean_bgr:line-0001",
            text="TWO",
            confidence=0.92,
            bbox=[[3, 3], [8, 3], [8, 8], [3, 8]],
            bbox_space="render_pixels",
            image_variant_id="gray_clean_bgr",
            source_backend="paddleocr",
        ),
    ]

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        evidence_lines=evidence_lines,
        source_variant_id="color_resized",
        bbox_space_hint="render_pixels",
        return_metadata=True,
    )

    assert artifact_path is not None
    assert debug["active_evidence_count"] == 1
    assert len(annotation["bbox"]) == 1
    assert annotation["bbox"][0]["evidence_id"] == "color_resized:line-0001"


def test_create_annotated_artifact_skips_when_selected_variant_has_no_matching_evidence(tmp_path: Path):
    ocr = OCRResult(
        full_text="ONE",
        lines=[OCRLine(text="ONE", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]])],
    )
    evidence_lines = [
        OCREvidenceLine(
            id="gray_clean_bgr:line-0001",
            text="ONE",
            confidence=0.95,
            bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
            bbox_space="render_pixels",
            image_variant_id="gray_clean_bgr",
            source_backend="paddleocr",
        )
    ]

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        evidence_lines=evidence_lines,
        source_variant_id="color_resized",
        bbox_space_hint="render_pixels",
        return_metadata=True,
    )

    assert artifact_path is not None
    assert debug["active_evidence_count"] == 0
    assert "no_evidence_for_selected_variant" in debug["skip_reasons"]
    assert debug["annotation_available"] is False
    assert annotation["bbox"] == []


def test_create_annotated_artifact_skips_when_source_variant_missing(tmp_path: Path):
    ocr = OCRResult(
        full_text="ONE",
        lines=[OCRLine(text="ONE", confidence=0.9, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]])],
    )
    evidence_lines = [
        OCREvidenceLine(
            id="color_resized:line-0001",
            text="ONE",
            confidence=0.95,
            bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
            bbox_space="render_pixels",
            image_variant_id="color_resized",
            source_backend="paddleocr",
        )
    ]

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        evidence_lines=evidence_lines,
        source_variant_id=None,
        bbox_space_hint="render_pixels",
        return_metadata=True,
    )

    assert artifact_path is not None
    assert annotation["bbox"] == []
    assert "missing_source_variant_id" in debug["skip_reasons"]
    assert debug["active_evidence_count"] == 0


def test_create_annotated_artifact_fallback_is_opt_in_and_filtered(tmp_path: Path):
    ocr = OCRResult(
        full_text="STONE'S THROW WHISKEY",
        lines=[
            OCRLine(
                text="STONE'S THROW WHISKEY",
                confidence=0.92,
                bbox=[[6, 6], [24, 6], [24, 20], [6, 20]],
            )
        ],
    )

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        source_variant_id="color_resized",
        bbox_space_hint="render_pixels",
        allow_legacy_fallback=True,
        return_metadata=True,
    )

    assert artifact_path is not None
    assert debug["used_fallback_evidence"] is True
    assert debug["rendered_count"] == 1
    assert len(annotation["bbox"]) == 1


def test_create_annotated_artifact_fallback_filter_skips_noisy_lines(tmp_path: Path):
    ocr = OCRResult(
        full_text="A\nB",
        lines=[
            OCRLine(text="A", confidence=0.4, bbox=[[6, 6], [8, 6], [8, 8], [6, 8]]),
            OCRLine(text="B", confidence=0.5, bbox=[[10, 10], [12, 10], [12, 12], [10, 12]]),
        ],
    )

    artifact_path, annotation, debug = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
        source_variant_id="color_resized",
        bbox_space_hint="render_pixels",
        allow_legacy_fallback=True,
        return_metadata=True,
    )

    assert artifact_path is None
    assert annotation["bbox"] == []
    assert "no_canonical_evidence_lines" in debug["skip_reasons"]
