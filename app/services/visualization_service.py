from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np

from app.domain.models import OCRResult, ParsedFields


def create_annotated_ocr_artifact(
    image_bytes: bytes,
    ocr: OCRResult,
    storage_dir: Path,
    parsed: ParsedFields | None = None,
    base_image: np.ndarray | None = None,
    bbox_space_hint: str = "auto",
) -> str | None:
    """Render OCR evidence overlays and return storage-relative artifact path."""
    if not ocr.lines:
        return None

    image: np.ndarray | None
    if base_image is not None:
        image = base_image.copy()
    else:
        np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return None

    height, width = image.shape[:2]
    source_shape = _decode_image_shape(image_bytes)
    annotated = image.copy()
    highlighted_keywords = _field_keywords(parsed)
    warning_keywords = {"government warning", "surgeon general", "pregnancy", "health problems"}

    occupied_labels: list[tuple[int, int, int, int]] = []
    rendered_count = 0

    for index, line in enumerate(ocr.lines, start=1):
        points = _transform_bbox_points(
            bbox=line.bbox,
            render_shape=(height, width),
            source_shape=source_shape,
            bbox_space_hint=bbox_space_hint,
        )
        if points.shape[0] < 4 or not _has_drawable_area(points):
            continue

        lowered = line.text.lower()
        is_warning_like = any(token in lowered for token in warning_keywords)
        is_field_linked = any(token in lowered for token in highlighted_keywords)

        if is_warning_like:
            color = (0, 165, 255)  # orange
            thickness = 3
        elif is_field_linked:
            color = (255, 153, 0)  # blue-ish
            thickness = 3
        else:
            color = (0, 220, 80)  # green
            thickness = 2

        cv2.polylines(annotated, [points], isClosed=True, color=color, thickness=thickness)
        rendered_count += 1

        line_preview = " ".join(line.text.split())
        if len(line_preview) > 20:
            line_preview = f"{line_preview[:17]}..."
        label = f"#{index} {line.confidence:.2f} {line_preview}"
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        origin = _pick_label_origin(points, text_size=text_size, baseline=baseline, occupied=occupied_labels, width=width, height=height)

        box_x1 = max(0, origin[0] - 2)
        box_y1 = max(0, origin[1] - text_size[1] - 4)
        box_x2 = min(width - 1, origin[0] + text_size[0] + 2)
        box_y2 = min(height - 1, origin[1] + baseline + 2)
        cv2.rectangle(annotated, (box_x1, box_y1), (box_x2, box_y2), (18, 18, 18), -1)
        cv2.putText(annotated, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    if rendered_count == 0:
        _draw_fallback_line_legend(annotated, ocr)

    output_dir = Path(storage_dir) / "outputs" / "annotated"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"
    output_path = output_dir / filename
    if not cv2.imwrite(str(output_path), annotated):
        return None
    return f"outputs/annotated/{filename}"


def _decode_image_shape(image_bytes: bytes) -> tuple[int, int] | None:
    np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    return (height, width)


def _transform_bbox_points(
    *,
    bbox: list[list[float]],
    render_shape: tuple[int, int],
    source_shape: tuple[int, int] | None,
    bbox_space_hint: str = "auto",
) -> np.ndarray:
    coordinate_space = _resolve_coordinate_space(
        bbox=bbox,
        render_shape=render_shape,
        source_shape=source_shape,
        bbox_space_hint=bbox_space_hint,
    )
    if coordinate_space in {"placeholder", "unknown"}:
        return np.array([], dtype=np.int32)

    render_height, render_width = render_shape
    scaled: list[list[int]] = []
    if coordinate_space == "native_pixels":
        for point in bbox:
            if len(point) != 2:
                continue
            x = min(max(int(round(float(point[0]))), 0), render_width - 1)
            y = min(max(int(round(float(point[1]))), 0), render_height - 1)
            scaled.append([x, y])
    elif coordinate_space == "normalized":
        for point in bbox:
            if len(point) != 2:
                continue
            x = min(max(int(round(float(point[0]) * (render_width - 1))), 0), render_width - 1)
            y = min(max(int(round(float(point[1]) * (render_height - 1))), 0), render_height - 1)
            scaled.append([x, y])
    else:  # scaled_from_source
        if source_shape is None:
            return np.array([], dtype=np.int32)
        source_height, source_width = source_shape
        scale_x = render_width / max(1.0, float(source_width))
        scale_y = render_height / max(1.0, float(source_height))
        for point in bbox:
            if len(point) != 2:
                continue
            x = min(max(int(round(float(point[0]) * scale_x)), 0), render_width - 1)
            y = min(max(int(round(float(point[1]) * scale_y)), 0), render_height - 1)
            scaled.append([x, y])
    return np.array(scaled, dtype=np.int32)


def _resolve_coordinate_space(
    *,
    bbox: list[list[float]],
    render_shape: tuple[int, int],
    source_shape: tuple[int, int] | None,
    bbox_space_hint: str = "auto",
) -> str:
    normalized_hint = str(bbox_space_hint or "auto").strip().lower()
    if _is_placeholder_bbox(bbox):
        return "placeholder"
    if not bbox:
        return "unknown"

    xs: list[float] = []
    ys: list[float] = []
    for point in bbox:
        if len(point) != 2:
            return "unknown"
        try:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
        except (TypeError, ValueError):
            return "unknown"

    if not xs or not ys:
        return "unknown"

    is_normalized = min(xs) >= -0.001 and max(xs) <= 1.001 and min(ys) >= -0.001 and max(ys) <= 1.001
    render_height, render_width = render_shape
    fits_render = _fits_shape(xs=xs, ys=ys, width=render_width, height=render_height)
    source_height = None
    source_width = None
    fits_source = False
    if source_shape is not None:
        source_height, source_width = source_shape
        fits_source = _fits_shape(xs=xs, ys=ys, width=source_width, height=source_height)

    if normalized_hint == "normalized":
        return "normalized" if is_normalized else "unknown"
    if normalized_hint == "render_pixels":
        return "native_pixels" if fits_render else "unknown"
    if normalized_hint == "source_pixels":
        if source_shape is not None and fits_source and (source_height, source_width) != (render_height, render_width):
            return "scaled_from_source"
        return "unknown"

    # auto (deterministic): placeholder -> normalized -> scaled_from_source -> native_pixels
    if is_normalized:
        return "normalized"

    if source_shape is not None:
        if (source_height, source_width) != (render_height, render_width) and fits_source:
            return "scaled_from_source"

    if fits_render:
        return "native_pixels"
    return "unknown"


def _fits_shape(*, xs: list[float], ys: list[float], width: int, height: int) -> bool:
    tolerance = 1.0
    return min(xs) >= -tolerance and min(ys) >= -tolerance and max(xs) <= (width + tolerance) and max(ys) <= (height + tolerance)


def _is_placeholder_bbox(bbox: list[list[float]]) -> bool:
    if len(bbox) < 4:
        return True
    placeholder = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for idx, expected in enumerate(placeholder):
        point = bbox[idx]
        if len(point) != 2:
            return True
        if abs(float(point[0]) - expected[0]) > 0.001 or abs(float(point[1]) - expected[1]) > 0.001:
            return False
    return True


def _has_drawable_area(points: np.ndarray) -> bool:
    min_x = int(np.min(points[:, 0]))
    max_x = int(np.max(points[:, 0]))
    min_y = int(np.min(points[:, 1]))
    max_y = int(np.max(points[:, 1]))
    return (max_x - min_x) >= 3 and (max_y - min_y) >= 3


def _pick_label_origin(
    points: np.ndarray,
    *,
    text_size: tuple[int, int],
    baseline: int,
    occupied: list[tuple[int, int, int, int]],
    width: int,
    height: int,
) -> tuple[int, int]:
    min_x = int(np.min(points[:, 0]))
    min_y = int(np.min(points[:, 1]))
    max_x = int(np.max(points[:, 0]))
    max_y = int(np.max(points[:, 1]))

    candidates = [
        (max(2, min_x), max(14, min_y - 6)),
        (max(2, min_x), min(height - 4, max_y + text_size[1] + 6)),
        (max(2, min(width - text_size[0] - 4, max_x - text_size[0])), max(14, min_y - 6)),
    ]

    for origin in candidates:
        rect = _label_rect(origin, text_size=text_size, baseline=baseline)
        if _inside(rect, width=width, height=height) and not _overlaps(rect, occupied):
            occupied.append(rect)
            return origin

    fallback = (max(2, min_x), min(height - 4, max_y + text_size[1] + 6))
    occupied.append(_label_rect(fallback, text_size=text_size, baseline=baseline))
    return fallback


def _label_rect(origin: tuple[int, int], *, text_size: tuple[int, int], baseline: int) -> tuple[int, int, int, int]:
    x1 = origin[0] - 2
    y1 = origin[1] - text_size[1] - 4
    x2 = origin[0] + text_size[0] + 2
    y2 = origin[1] + baseline + 2
    return (x1, y1, x2, y2)


def _inside(rect: tuple[int, int, int, int], *, width: int, height: int) -> bool:
    return rect[0] >= 0 and rect[1] >= 0 and rect[2] < width and rect[3] < height


def _overlaps(rect: tuple[int, int, int, int], occupied: list[tuple[int, int, int, int]]) -> bool:
    for other in occupied:
        if rect[0] <= other[2] and rect[2] >= other[0] and rect[1] <= other[3] and rect[3] >= other[1]:
            return True
    return False


def _field_keywords(parsed: ParsedFields | None) -> set[str]:
    if parsed is None:
        return set()
    values: list[str] = []
    for value in (
        parsed.brand_name.value,
        parsed.class_type.value,
        parsed.bottler_producer.value,
        parsed.country_of_origin.value,
        parsed.government_warning.value,
        parsed.alcohol_content.raw,
        parsed.net_contents.raw,
    ):
        if value:
            values.append(value)

    keywords: set[str] = set()
    for value in values:
        normalized = " ".join(value.lower().split())
        for token in normalized.split(" "):
            if len(token) >= 5:
                keywords.add(token)
    return keywords


def _draw_fallback_line_legend(image: np.ndarray, ocr: OCRResult) -> None:
    height, width = image.shape[:2]
    legend_height = min(height - 8, 26 + (min(len(ocr.lines), 12) * 18))
    cv2.rectangle(image, (4, 4), (min(width - 4, 560), legend_height), (12, 12, 12), -1)
    cv2.putText(
        image,
        "OCR evidence (bbox unavailable):",
        (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    for idx, line in enumerate(ocr.lines[:12], start=1):
        preview = " ".join(line.text.split())
        if len(preview) > 44:
            preview = f"{preview[:41]}..."
        label = f"#{idx} {line.confidence:.2f} {preview}"
        y = 20 + (idx * 18)
        if y > legend_height - 4:
            break
        cv2.putText(image, label, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)
