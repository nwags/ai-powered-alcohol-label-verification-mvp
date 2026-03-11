from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageVariant:
    name: str
    image: np.ndarray


def read_image(image_path: str) -> np.ndarray:
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Unable to read image from path: {image_path}")
    return image


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode image bytes")
    return image


def resize_if_too_large(image: np.ndarray, max_dimension: int = 2200) -> np.ndarray:
    height, width = image.shape[:2]
    largest_dimension = max(height, width)
    if largest_dimension <= max_dimension:
        return image
    scale = max_dimension / float(largest_dimension)
    resized = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return resized


def to_grayscale(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def denoise(grayscale_image: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(grayscale_image, h=9, templateWindowSize=7, searchWindowSize=21)


def deskew_hook(image: np.ndarray) -> np.ndarray:
    # Hook for later: this prototype currently skips deskew to keep runtime predictable.
    return image


def build_ocr_variants(
    image: np.ndarray,
    max_dimension: int = 2200,
    enable_deskew: bool = False,
    max_variants: int = 3,
) -> list[ImageVariant]:
    prepared = resize_if_too_large(image, max_dimension=max_dimension)
    if enable_deskew:
        prepared = deskew_hook(prepared)

    gray = to_grayscale(prepared)
    cleaned = denoise(gray)

    variants: list[ImageVariant] = [ImageVariant(name="color_resized", image=prepared)]

    if max_variants >= 2:
        variants.append(ImageVariant(name="gray_clean", image=cleaned))

    if max_variants >= 3:
        threshold = cv2.adaptiveThreshold(
            cleaned,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            12,
        )
        variants.append(ImageVariant(name="gray_threshold", image=threshold))

    return variants[:max(1, min(max_variants, 3))]
