from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.dependencies import get_ocr_service
from app.domain.models import OCRLine, OCRResult
from app.main import app


class FakeOCRService:
    def __init__(self, ready: bool = True, state: str = "ready", error: str | None = None) -> None:
        self._ready = ready
        self._state = state
        self._error = error

    def is_ready(self) -> bool:
        return self._ready

    def get_status(self) -> dict[str, object]:
        return {
            "state": self._state,
            "ready": self._ready,
            "error": self._error,
        }

    def run_ocr(self, image_path: str) -> OCRResult:
        _ = image_path
        return self._build_result()

    def run_ocr_bytes(self, image_bytes: bytes, source_label: str = "upload") -> tuple[OCRResult, list[str]]:
        _ = image_bytes, source_label
        return self._build_result(), []

    def extract_text(self, image_bytes: bytes) -> tuple[OCRResult, list[str]]:
        return self.run_ocr_bytes(image_bytes)

    def _build_result(self) -> OCRResult:
        return OCRResult(
            full_text=(
                "STONE'S THROW WHISKEY\n"
                "45% Alc./Vol.\n"
                "750ML\n"
                "Bottled by Example Spirits Co.\n"
                "GOVERNMENT WARNING: SAMPLE"
            ),
            lines=[
                OCRLine(text="STONE'S THROW WHISKEY", confidence=0.99, bbox=[[0, 0], [10, 0], [10, 10], [0, 10]]),
                OCRLine(text="45% Alc./Vol.", confidence=0.95, bbox=[[0, 0], [10, 0], [10, 10], [0, 10]]),
                OCRLine(text="750ML", confidence=0.96, bbox=[[0, 0], [10, 0], [10, 10], [0, 10]]),
                OCRLine(text="Bottled by Example Spirits Co.", confidence=0.92, bbox=[[0, 0], [10, 0], [10, 10], [0, 10]]),
                OCRLine(text="GOVERNMENT WARNING: SAMPLE", confidence=0.88, bbox=[[0, 0], [10, 0], [10, 10], [0, 10]]),
            ],
        )


def build_test_image_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def pytest_configure() -> None:
    app.dependency_overrides[get_ocr_service] = lambda: FakeOCRService()


def pytest_unconfigure() -> None:
    app.dependency_overrides.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
