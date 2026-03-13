from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.domain.enums import FieldStatus, OverallStatus


class ApiError(BaseModel):
    code: str
    message: str


class ApplicationData(BaseModel):
    brand_name: str | None = None
    class_type: str | None = None
    alcohol_content: str | None = None
    net_contents: str | None = None
    bottler_producer: str | None = None
    country_of_origin: str | None = None
    government_warning: str | None = Field(
        default=None,
        validation_alias=AliasChoices("government_warning", "warning_statement"),
    )


class OCRLine(BaseModel):
    text: str
    confidence: float
    bbox: list[list[float]]


class OCREvidenceLine(BaseModel):
    id: str
    text: str
    confidence: float
    bbox: list[list[float]]
    bbox_space: str
    image_variant_id: str
    source_backend: str


class OCRResult(BaseModel):
    full_text: str
    lines: list[OCRLine] = Field(default_factory=list)


class ParsedTextValue(BaseModel):
    value: str | None = None


class ParsedAlcoholContent(BaseModel):
    raw: str | None = None
    abv_percent: float | None = None
    proof: float | None = None


class ParsedNetContents(BaseModel):
    raw: str | None = None
    milliliters: int | None = None


class ParsedWarning(BaseModel):
    value: str | None = None
    detected: bool = False
    has_uppercase_prefix: bool = False
    confidence: float | None = None


class ParsedFields(BaseModel):
    brand_name: ParsedTextValue = ParsedTextValue()
    class_type: ParsedTextValue = ParsedTextValue()
    alcohol_content: ParsedAlcoholContent = ParsedAlcoholContent()
    net_contents: ParsedNetContents = ParsedNetContents()
    bottler_producer: ParsedTextValue = ParsedTextValue()
    country_of_origin: ParsedTextValue = ParsedTextValue()
    government_warning: ParsedWarning = ParsedWarning()


class FieldResult(BaseModel):
    status: FieldStatus
    submitted_value: str | None = None
    detected_value: str | None = None
    notes: str | None = None


class AnalyzeResponse(BaseModel):
    request_id: str
    overall_status: OverallStatus
    timing_ms: int
    ocr: OCRResult
    parsed: ParsedFields
    field_results: dict[str, FieldResult]
    review_reasons: list[str] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class BatchResult(BaseModel):
    record_id: str
    request_id: str
    overall_status: OverallStatus
    image_filename: str | None = None
    image_url: str | None = None
    main_reason: str | None = None
    timing_ms: int = 0


class BatchSummary(BaseModel):
    total: int
    match: int
    normalized_match: int
    mismatch: int
    review: int


class BatchResponse(BaseModel):
    batch_id: str
    summary: BatchSummary
    results: list[BatchResult] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class OCRSmokeResponse(BaseModel):
    sample_name: str
    image_path: str
    timing_ms: int
    ocr: OCRResult
    errors: list[str] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ApiError
