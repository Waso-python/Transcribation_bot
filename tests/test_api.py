import time

from conftest import build_wav_bytes


def test_job_lifecycle(client):
    wav_data = build_wav_bytes(seconds=1)
    response = client.post(
        "/v1/transcriptions",
        headers={"X-API-Key": "test-key"},
        files={"file": ("sample.wav", wav_data, "audio/wav")},
    )
    assert response.status_code == 202
    payload = response.json()
    job_id = payload["job_id"]

    status_payload = {}
    for _ in range(40):
        status_response = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"})
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] == "done":
            break
        time.sleep(0.05)

    assert status_payload["status"] == "done"
    result_response = client.get(f"/v1/jobs/{job_id}/result", headers={"X-API-Key": "test-key"})
    assert result_response.status_code == 200
    result = result_response.json()
    assert result["text"]
    assert len(result["segments"]) >= 1

    download_response = client.get(
        f"/v1/jobs/{job_id}/download.txt",
        headers={"X-API-Key": "test-key"},
    )
    assert download_response.status_code == 200
    assert "attachment;" in download_response.headers["content-disposition"]
    assert "sample.txt" in download_response.headers["content-disposition"]
    assert download_response.text.strip()


def test_download_txt_with_unicode_filename(client):
    wav_data = build_wav_bytes(seconds=1)
    response = client.post(
        "/v1/transcriptions",
        headers={"X-API-Key": "test-key"},
        files={"file": ("привет-мир.wav", wav_data, "audio/wav")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    for _ in range(40):
        status_response = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"})
        assert status_response.status_code == 200
        if status_response.json()["status"] == "done":
            break
        time.sleep(0.05)

    download_response = client.get(
        f"/v1/jobs/{job_id}/download.txt",
        headers={"X-API-Key": "test-key"},
    )
    assert download_response.status_code == 200
    content_disposition = download_response.headers["content-disposition"]
    assert "filename*=" in content_disposition
    assert "attachment;" in content_disposition


def test_auth_required(client):
    wav_data = build_wav_bytes(seconds=1)
    response = client.post(
        "/v1/transcriptions",
        files={"file": ("sample.wav", wav_data, "audio/wav")},
    )
    assert response.status_code == 401


def test_unsupported_format(client):
    response = client.post(
        "/v1/transcriptions",
        headers={"X-API-Key": "test-key"},
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
