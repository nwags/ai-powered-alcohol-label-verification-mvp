from pathlib import Path

from conftest import build_test_image_bytes

from app.domain.models import OCRLine, OCRResult, ParsedFields
from app.services.visualization_service import (
    _resolve_coordinate_space,
    _transform_bbox_points,
    create_annotated_ocr_artifact,
)


def test_create_annotated_artifact_falls_back_when_bboxes_are_placeholders(tmp_path: Path):
    ocr = OCRResult(
        full_text="Blue Ridge Estate Vineyard & Winery\nNet cont. 750 mi",
        lines=[
            OCRLine(text="Blue Ridge Estate Vineyard & Winery", confidence=0.95, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
            OCRLine(text="Net cont. 750 mi", confidence=0.91, bbox=[[0, 0], [1, 0], [1, 1], [0, 1]]),
        ],
    )

    relative_path = create_annotated_ocr_artifact(
        image_bytes=build_test_image_bytes(),
        ocr=ocr,
        storage_dir=tmp_path,
        parsed=ParsedFields(),
    )

    assert relative_path is not None
    assert (tmp_path / relative_path).exists()


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
