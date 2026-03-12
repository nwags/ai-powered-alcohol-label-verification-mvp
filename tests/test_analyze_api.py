import json

from conftest import build_test_image_bytes


def test_analyze_returns_contract_shape(client):
    payload = {
        "brand_name": "Stone's Throw Whiskey",
        "class_type": "Whiskey",
        "alcohol_content": "45% Alc./Vol.",
        "net_contents": "750 mL",
        "bottler_producer": "Bottled by Example Spirits Co.",
        "country_of_origin": "United States",
        "government_warning": "GOVERNMENT WARNING: sample",
    }
    files = {"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")}
    data = {"application_json": json.dumps(payload)}

    response = client.post("/api/v1/analyze", files=files, data=data)

    assert response.status_code == 200
    body = response.json()
    assert {"request_id", "overall_status", "timing_ms", "ocr", "parsed", "field_results", "artifacts", "errors"} <= body.keys()
    assert body["overall_status"] in {"match", "normalized_match", "mismatch", "review"}
    assert body["field_results"]["government_warning"]["status"] in {"match", "normalized_match", "mismatch", "review"}
    assert isinstance(body["ocr"]["full_text"], str)
    assert "inference" in body["artifacts"]
    assert "rule_trace" in body["artifacts"]
    assert "profile_inference" in body["artifacts"]["rule_trace"]


def test_analyze_rejects_unsupported_media_type(client):
    payload = {"brand_name": "Example"}
    files = {"image": ("label.txt", b"not-an-image", "text/plain")}
    data = {"application_json": json.dumps(payload)}

    response = client.post("/api/v1/analyze", files=files, data=data)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_image"


def test_analyze_accepts_label_type_hint(client):
    payload = {
        "brand_name": "Stone's Throw Whiskey",
        "class_type": "Whiskey",
        "alcohol_content": "45% Alc./Vol.",
        "net_contents": "750 mL",
        "bottler_producer": "Bottled by Example Spirits Co.",
        "country_of_origin": "United States",
        "government_warning": "GOVERNMENT WARNING: sample",
    }
    files = {"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")}
    data = {"application_json": json.dumps(payload), "label_type": "brand_label"}

    response = client.post("/api/v1/analyze", files=files, data=data)

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] in {"match", "normalized_match", "mismatch", "review"}


def test_analyze_accepts_product_profile_hint(client):
    payload = {"brand_name": "Stone's Throw Whiskey"}
    files = {"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")}
    data = {"application_json": json.dumps(payload), "product_profile": "wine"}

    response = client.post("/api/v1/analyze", files=files, data=data)

    assert response.status_code == 200
    body = response.json()
    assert body["artifacts"]["inference"]["product_profile"]["selected_hint"] == "wine"
