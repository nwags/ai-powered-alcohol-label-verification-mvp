import csv
import io
import zipfile


def _build_images_zip_bytes() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label1.jpg", b"fake-image-content")
    return zip_buffer.getvalue()


def test_batch_ui_label_only_mode_accepts_images_zip_only(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_label_only", "label_type": "brand_label"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    assert "Batch Summary" in response.text
    assert 'name="label_type" value="brand_label" checked' in response.text


def test_batch_ui_compare_mode_requires_batch_file(client):
    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_compare_application"},
        files={"images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip")},
    )

    assert response.status_code == 422
    assert "Batch file is required in Compare to Application Data mode." in response.text


def test_batch_ui_compare_mode_preserves_existing_compare_flow(client):
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=[
            "record_id",
            "image_filename",
            "brand_name",
            "class_type",
            "alcohol_content",
            "net_contents",
            "bottler_producer",
            "country_of_origin",
            "government_warning",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "record_id": "001",
            "image_filename": "label1.jpg",
            "brand_name": "Stone's Throw Whiskey",
            "class_type": "Whiskey",
            "alcohol_content": "45% Alc./Vol.",
            "net_contents": "750 mL",
            "bottler_producer": "Bottled by Example Spirits Co.",
            "country_of_origin": "United States",
            "government_warning": "GOVERNMENT WARNING: SAMPLE",
        }
    )

    response = client.post(
        "/ui/batch",
        data={"batch_review_mode": "batch_compare_application"},
        files={
            "batch_file": ("batch.csv", csv_buffer.getvalue().encode("utf-8"), "text/csv"),
            "images_archive": ("images.zip", _build_images_zip_bytes(), "application/zip"),
        },
    )

    assert response.status_code == 200
    assert "Batch Summary" in response.text
