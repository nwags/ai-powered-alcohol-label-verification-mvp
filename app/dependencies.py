from functools import lru_cache

from app.config import get_settings
from app.services.dev_diagnostics_service import DevDiagnosticsService
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
        require_local_models=settings.ocr_require_local_models,
        model_source=settings.ocr_model_source,
        model_root=settings.ocr_model_root,
        det_model_dir=settings.ocr_det_model_dir,
        rec_model_dir=settings.ocr_rec_model_dir,
        cls_model_dir=settings.ocr_cls_model_dir,
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


@lru_cache(maxsize=1)
def get_dev_diagnostics_service() -> DevDiagnosticsService:
    settings = get_settings()
    return DevDiagnosticsService(coverage_dir=settings.coverage_dir)
