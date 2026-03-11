from app.dependencies import get_ocr_service
from app.main import app


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_ready(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["ocr_loaded"] is True
    assert payload["storage_ok"] is True
    assert payload["db_ok"] is True


def test_readyz_returns_not_ready_when_ocr_not_loaded(client):
    class NotReadyOCRService:
        def get_status(self) -> dict[str, object]:
            return {"state": "warming", "ready": False, "error": None}

    original_override = app.dependency_overrides.get(get_ocr_service)
    app.dependency_overrides[get_ocr_service] = lambda: NotReadyOCRService()
    try:
        response = client.get("/readyz")
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_ocr_service, None)
        else:
            app.dependency_overrides[get_ocr_service] = original_override

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["ocr_loaded"] is False
    assert payload["ocr_state"] == "warming"
    assert payload["storage_ok"] is True
    assert payload["db_ok"] is True


def test_ocr_status_endpoint_returns_ui_status_payload(client):
    response = client.get("/api/v1/ocr/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "ready"
    assert payload["ready"] is True
    assert isinstance(payload["message"], str)
    assert payload["error"] is None
