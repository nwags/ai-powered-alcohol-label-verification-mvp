from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_title: str = "AI-Powered Alcohol Label Verification"
    log_level: str = "INFO"

    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("HOST", "host"))
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT", "WEBSITES_PORT", "port"))

    enable_preprocessing: bool = True
    enable_visualization: bool = True
    enable_diagnostics_ui: bool = False
    enable_batch_ui: bool = True
    allowed_review_modes: str = "label_only,compare_application"
    allowed_label_types: str = "unknown,brand_label,other_label"
    allowed_product_profiles: str = "unknown,distilled_spirits,malt_beverage,wine"
    enable_ocr: bool = True
    ocr_use_gpu: bool = False
    ocr_require_local_models: bool = True
    ocr_model_source: str = "local"
    ocr_model_root: Path = Path("data/models/paddleocr")
    ocr_det_model_dir: Path | None = None
    ocr_rec_model_dir: Path | None = None
    ocr_cls_model_dir: Path | None = None
    ocr_max_dimension: int = 2200
    ocr_max_variants: int = 3
    ocr_enable_deskew: bool = False

    storage_dir: Path = Path("runtime")
    sample_data_dir: Path = Path("data")
    coverage_dir: Path = Path("runtime/coverage")
    db_path: Path = Path("data/app.db")
    max_upload_bytes: int = 10 * 1024 * 1024
    batch_max_records: int = 200
    batch_max_images: int = 500


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
