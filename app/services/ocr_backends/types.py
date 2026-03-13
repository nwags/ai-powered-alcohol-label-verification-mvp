from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OCREvidenceLinePayload:
    id: str
    text: str
    confidence: float
    bbox: list[list[float]]
    bbox_space: str
    image_variant_id: str
    source_backend: str


@dataclass(frozen=True)
class OCRExtraction:
    full_text: str
    lines: list[OCREvidenceLinePayload] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
