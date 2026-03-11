from types import SimpleNamespace
from pathlib import Path

from app.dependencies import get_dev_diagnostics_service
from app.main import app
from app.api import routes_ui


def test_ui_diagnostics_returns_404_when_disabled(client, monkeypatch):
    fake_settings = SimpleNamespace(enable_diagnostics_ui=False, coverage_dir=Path("runtime/coverage"))
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)
    response = client.get("/ui/diagnostics")
    assert response.status_code == 404


def test_ui_diagnostics_returns_page_when_enabled(client, monkeypatch, tmp_path):
    class FakeDiagnosticsService:
        def coverage_status(self) -> dict[str, object]:
            return {"state": "idle", "message": "No coverage run has been started.", "last_exit_code": None}

        def recent_logs(self, limit: int = 150) -> list[str]:
            _ = limit
            return ["2026-03-11 INFO app.test diagnostics test log"]

        def trigger_coverage(self) -> bool:
            return True

    coverage_dir = tmp_path / "runtime" / "coverage"
    fake_settings = SimpleNamespace(
        enable_diagnostics_ui=True,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_require_local_models=True,
        ocr_model_source="local",
        ocr_model_root=tmp_path / "models" / "paddleocr",
        ocr_det_model_dir=None,
        ocr_rec_model_dir=None,
        ocr_cls_model_dir=None,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        coverage_dir=coverage_dir,
        max_upload_bytes=1024,
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)
    app.dependency_overrides[get_dev_diagnostics_service] = lambda: FakeDiagnosticsService()

    try:
        response = client.get("/ui/diagnostics")
        assert response.status_code == 200
        assert "Developer Diagnostics" in response.text
        assert str(fake_settings.storage_dir) in response.text
        assert "OCR Status" in response.text
        assert "Coverage is not available yet." in response.text
        assert "Recent Logs" in response.text
        assert "diagnostics test log" in response.text
    finally:
        app.dependency_overrides.pop(get_dev_diagnostics_service, None)


def test_ui_diagnostics_shows_coverage_when_summary_exists(client, monkeypatch, tmp_path):
    class FakeDiagnosticsService:
        def coverage_status(self) -> dict[str, object]:
            return {"state": "success", "message": "Coverage generation completed successfully.", "last_exit_code": 0}

        def recent_logs(self, limit: int = 150) -> list[str]:
            _ = limit
            return ["2026-03-11 INFO app.diagnostics Coverage generation completed successfully."]

        def trigger_coverage(self) -> bool:
            return True

    coverage_dir = tmp_path / "runtime" / "coverage"
    html_dir = coverage_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    (coverage_dir / "coverage.json").write_text(
        '{"totals":{"percent_covered_display":"88.12","covered_lines":112,"num_statements":127}}',
        encoding="utf-8",
    )
    (html_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    fake_settings = SimpleNamespace(
        enable_diagnostics_ui=True,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_require_local_models=True,
        ocr_model_source="local",
        ocr_model_root=tmp_path / "models" / "paddleocr",
        ocr_det_model_dir=None,
        ocr_rec_model_dir=None,
        ocr_cls_model_dir=None,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        coverage_dir=coverage_dir,
        max_upload_bytes=1024,
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)
    app.dependency_overrides[get_dev_diagnostics_service] = lambda: FakeDiagnosticsService()

    try:
        response = client.get("/ui/diagnostics")
        assert response.status_code == 200
        assert "Total Coverage" in response.text
        assert "88.12" in response.text
        assert "/storage/coverage/html/index.html" in response.text
        assert "Run State" in response.text
        assert "success" in response.text
    finally:
        app.dependency_overrides.pop(get_dev_diagnostics_service, None)


def test_ui_diagnostics_coverage_trigger_redirects(client, monkeypatch, tmp_path):
    class FakeDiagnosticsService:
        def __init__(self) -> None:
            self.triggered = False

        def coverage_status(self) -> dict[str, object]:
            return {"state": "idle", "message": "No coverage run has been started.", "last_exit_code": None}

        def recent_logs(self, limit: int = 150) -> list[str]:
            _ = limit
            return []

        def trigger_coverage(self) -> bool:
            self.triggered = True
            return True

    fake_service = FakeDiagnosticsService()
    fake_settings = SimpleNamespace(
        enable_diagnostics_ui=True,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_require_local_models=True,
        ocr_model_source="local",
        ocr_model_root=tmp_path / "models" / "paddleocr",
        ocr_det_model_dir=None,
        ocr_rec_model_dir=None,
        ocr_cls_model_dir=None,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        coverage_dir=tmp_path / "runtime" / "coverage",
        max_upload_bytes=1024,
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)
    app.dependency_overrides[get_dev_diagnostics_service] = lambda: fake_service

    try:
        response = client.post("/ui/diagnostics/coverage", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/diagnostics"
        assert fake_service.triggered is True
    finally:
        app.dependency_overrides.pop(get_dev_diagnostics_service, None)


def test_ui_diagnostics_coverage_trigger_returns_404_when_disabled(client, monkeypatch):
    fake_settings = SimpleNamespace(enable_diagnostics_ui=False, coverage_dir=Path("runtime/coverage"))
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)

    response = client.post("/ui/diagnostics/coverage", follow_redirects=False)
    assert response.status_code == 404


def test_ui_diagnostics_coverage_status_returns_json(client, monkeypatch, tmp_path):
    class FakeDiagnosticsService:
        def coverage_status(self) -> dict[str, object]:
            return {"state": "running", "message": "Coverage generation is running.", "last_exit_code": None}

        def recent_logs(self, limit: int = 150) -> list[str]:
            _ = limit
            return []

        def trigger_coverage(self) -> bool:
            return True

    fake_settings = SimpleNamespace(
        enable_diagnostics_ui=True,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_require_local_models=True,
        ocr_model_source="local",
        ocr_model_root=tmp_path / "models" / "paddleocr",
        ocr_det_model_dir=None,
        ocr_rec_model_dir=None,
        ocr_cls_model_dir=None,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        coverage_dir=tmp_path / "runtime" / "coverage",
        max_upload_bytes=1024,
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)
    app.dependency_overrides[get_dev_diagnostics_service] = lambda: FakeDiagnosticsService()

    try:
        response = client.get("/ui/diagnostics/coverage/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["coverage_run"]["state"] == "running"
        assert payload["coverage_run"]["last_exit_code"] is None
        assert payload["coverage"]["available"] is False
    finally:
        app.dependency_overrides.pop(get_dev_diagnostics_service, None)


def test_ui_diagnostics_coverage_status_returns_404_when_disabled(client, monkeypatch):
    fake_settings = SimpleNamespace(enable_diagnostics_ui=False, coverage_dir=Path("runtime/coverage"))
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)

    response = client.get("/ui/diagnostics/coverage/status")
    assert response.status_code == 404
