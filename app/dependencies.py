from functools import lru_cache

from app.config import get_settings
from app.services.batch_service import BatchService
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.ocr_service import OCRService


@lru_cache(maxsize=1)
def get_ocr_service() -> "OCRService":
    from app.services.ocr_service import OCRService

    settings = get_settings()
    return OCRService(
        enabled=settings.enable_ocr,
        use_gpu=settings.ocr_use_gpu,
        max_dimension=settings.ocr_max_dimension,
        max_variants=settings.ocr_max_variants,
        enable_deskew=settings.ocr_enable_deskew,
    )


@lru_cache(maxsize=1)
def get_batch_service() -> BatchService:
    settings = get_settings()
    return BatchService(
        storage_dir=settings.storage_dir,
        max_records=settings.batch_max_records,
        max_images=settings.batch_max_images,
    )
