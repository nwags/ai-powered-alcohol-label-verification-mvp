import csv
import io
import zipfile


def test_batch_analyze_csv_with_images_archive(client):
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
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("label1.jpg", b"fake-image-content")
    zip_bytes = zip_buffer.getvalue()

    response = client.post(
        "/api/v1/batch/analyze",
        data={"label_type": "other_label"},
        files={
            "batch_file": ("batch.csv", csv_bytes, "text/csv"),
            "images_archive": ("images.zip", zip_bytes, "application/zip"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] == 1
    assert len(body["results"]) == 1
    assert body["results"][0]["record_id"] == "001"
    assert body["results"][0]["image_filename"] == "label1.jpg"
    assert body["results"][0]["overall_status"] in {"match", "normalized_match", "mismatch", "review"}
    assert "summary_json_url" in body["artifacts"]
    assert "summary_csv_url" in body["artifacts"]


def test_batch_analyze_rejects_unknown_file_type(client):
    response = client.post(
        "/api/v1/batch/analyze",
        files={
            "batch_file": ("batch.txt", b"unsupported", "text/plain"),
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "invalid_request"


def test_batch_analyze_rejects_invalid_zip_payload(client):
    csv_bytes = b"record_id,image_filename\n001,label1.jpg\n"
    response = client.post(
        "/api/v1/batch/analyze",
        files={
            "batch_file": ("batch.csv", csv_bytes, "text/csv"),
            "images_archive": ("images.zip", b"not-a-zip", "application/zip"),
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "invalid_request"
