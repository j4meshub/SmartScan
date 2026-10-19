import hashlib
import uuid

from fastapi.testclient import TestClient

from services.api.app import main


def register(client: TestClient, prefix: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    phone_suffix = str(uuid.uuid4().int % 10_000_000).zfill(7)
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{phone_suffix}",
            "sms_code": main.settings.dev_sms_code,
            "username": f"{prefix}_{suffix}",
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_chunk_upload_resumes_is_isolated_and_completes_idempotently():
    original_chunk_size = main.settings.upload_chunk_bytes
    main.settings.upload_chunk_bytes = 1024
    try:
        with TestClient(main.app) as client:
            owner_headers = register(client, "owner")
            other_headers = register(client, "other")
            project = client.post(
                "/v1/projects",
                json={"title": "断点续传", "mode": "document", "reading_order": "ltr"},
                headers=owner_headers,
            )
            assert project.status_code == 201, project.text

            payload = b"\x89PNG\r\n\x1a\n" + b"smartscan" * 300
            digest = hashlib.sha256(payload).hexdigest()
            create_body = {
                "project_id": project.json()["id"],
                "file_name": "../page.png",
                "mime_type": "image/png",
                "size_bytes": len(payload),
                "sha256": digest,
                "idempotency_key": f"test-{uuid.uuid4().hex}",
            }
            initiated = client.post("/v1/uploads", json=create_body, headers=owner_headers)
            assert initiated.status_code == 201, initiated.text
            upload = initiated.json()
            assert upload["file_name"] == "page.png"
            assert upload["total_chunks"] == 3

            repeated = client.post("/v1/uploads", json=create_body, headers=owner_headers)
            assert repeated.status_code == 201
            assert repeated.json()["id"] == upload["id"]

            conflicting = client.post(
                "/v1/uploads",
                json={**create_body, "sha256": "0" * 64},
                headers=owner_headers,
            )
            assert conflicting.status_code == 409
            renamed = client.post(
                "/v1/uploads",
                json={**create_body, "file_name": "other-page.png"},
                headers=owner_headers,
            )
            assert renamed.status_code == 409

            first = payload[: upload["chunk_size"]]
            first_hash = hashlib.sha256(first).hexdigest()
            accepted = client.put(
                f"/v1/uploads/{upload['id']}/chunks/0",
                content=first,
                headers={**owner_headers, "X-Chunk-Sha256": first_hash},
            )
            assert accepted.status_code == 200, accepted.text

            status = client.get(f"/v1/uploads/{upload['id']}", headers=owner_headers)
            assert status.status_code == 200
            assert status.json()["received_chunks"] == [0]
            hidden = client.get(f"/v1/uploads/{upload['id']}", headers=other_headers)
            assert hidden.status_code == 404

            second = payload[upload["chunk_size"] : upload["chunk_size"] * 2]
            rejected = client.put(
                f"/v1/uploads/{upload['id']}/chunks/1",
                content=second,
                headers={**owner_headers, "X-Chunk-Sha256": "0" * 64},
            )
            assert rejected.status_code == 422

            for index in range(1, upload["total_chunks"]):
                start = index * upload["chunk_size"]
                chunk = payload[start : start + upload["chunk_size"]]
                response = client.put(
                    f"/v1/uploads/{upload['id']}/chunks/{index}",
                    content=chunk,
                    headers={
                        **owner_headers,
                        "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest(),
                    },
                )
                assert response.status_code == 200, response.text

            completed = client.post(f"/v1/uploads/{upload['id']}/complete", headers=owner_headers)
            assert completed.status_code == 202, completed.text
            completed_again = client.post(
                f"/v1/uploads/{upload['id']}/complete", headers=owner_headers
            )
            assert completed_again.status_code == 202
            assert completed_again.json()["id"] == completed.json()["id"]

            jobs = client.get("/v1/jobs", headers=owner_headers)
            matching_jobs = [job for job in jobs.json() if job["page_id"] == completed.json()["id"]]
            assert len(matching_jobs) == 1
    finally:
        main.settings.upload_chunk_bytes = original_chunk_size
