import json

from conftest import build_test_image_bytes


def test_analyze_artifacts_include_rule_trace_for_core_fields(client):
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
    data = {"application_json": json.dumps(payload), "product_profile": "unknown", "label_type": "unknown"}

    response = client.post("/api/v1/analyze", files=files, data=data)

    assert response.status_code == 200
    body = response.json()
    rule_trace = body["artifacts"]["rule_trace"]
    assert "brand_name" in rule_trace
    assert "class_type" in rule_trace
    assert "government_warning" in rule_trace
    assert any(entry.get("rule_id") == "WARN-SHARED" for entry in rule_trace["government_warning"])


def test_analyze_artifacts_include_inference_rule_trace_keys(client):
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
    data = {"application_json": json.dumps(payload), "product_profile": "unknown", "label_type": "unknown"}

    response = client.post("/api/v1/analyze", files=files, data=data)

    assert response.status_code == 200
    body = response.json()
    rule_trace = body["artifacts"]["rule_trace"]
    assert "profile_inference" in rule_trace
