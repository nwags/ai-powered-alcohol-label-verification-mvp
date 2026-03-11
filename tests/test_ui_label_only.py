from conftest import build_test_image_bytes


def test_ui_label_only_uses_mode_aware_field_rationales_and_shows_annotation(client):
    response = client.post(
        "/ui/analyze",
        data={"review_mode": "label_only", "label_type": "unknown"},
        files={"image": ("label.jpg", build_test_image_bytes(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert "Analysis Result" in response.text
    assert "missing submitted or OCR value" not in response.text
    assert "Annotated OCR Evidence" in response.text
    assert "/storage/outputs/annotated/" in response.text
