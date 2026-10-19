import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image

from services.api.app import main


def test_register_create_project_and_upload_page():
    suffix = uuid.uuid4().hex[:10]
    phone_suffix = str(uuid.uuid4().int % 10_000_000).zfill(7)
    with TestClient(main.app) as client:
        registered = client.post(
            "/v1/auth/register",
            json={
                "phone": f"+1555{phone_suffix}",
                "sms_code": main.settings.dev_sms_code,
                "username": f"user_{suffix}",
                "password": "correct-horse-battery-staple",
                "locale": "en",
            },
        )
        assert registered.status_code == 201, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        project = client.post(
            "/v1/projects",
            json={"title": "Contract sample", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        )
        assert project.status_code == 201, project.text

        image = Image.new("RGB", (1200, 1600), "white")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG")
        upload = client.post(
            f"/v1/projects/{project.json()['id']}/pages",
            files={"file": ("page.jpg", buffer.getvalue(), "image/jpeg")},
            headers=headers,
        )
        assert upload.status_code == 202, upload.text
        jobs = client.get("/v1/jobs", headers=headers)
        assert jobs.status_code == 200
        assert jobs.json()[0]["status"] == "pending"
