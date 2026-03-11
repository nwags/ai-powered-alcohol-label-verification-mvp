from types import SimpleNamespace

from app.api import routes_ui


def test_ui_diagnostics_returns_404_when_disabled(client):
    response = client.get("/ui/diagnostics")
    assert response.status_code == 404


def test_ui_diagnostics_returns_page_when_enabled(client, monkeypatch, tmp_path):
    fake_settings = SimpleNamespace(
        enable_diagnostics_ui=True,
        app_env="development",
        log_level="INFO",
        enable_ocr=True,
        ocr_use_gpu=False,
        ocr_max_dimension=2200,
        ocr_max_variants=3,
        ocr_enable_deskew=False,
        enable_preprocessing=True,
        enable_visualization=True,
        storage_dir=tmp_path / "runtime",
        sample_data_dir=tmp_path / "data",
        max_upload_bytes=1024,
    )
    monkeypatch.setattr(routes_ui, "get_settings", lambda: fake_settings)

    response = client.get("/ui/diagnostics")
    assert response.status_code == 200
    assert "Developer Diagnostics" in response.text
    assert str(fake_settings.storage_dir) in response.text
    assert "OCR Status" in response.text
