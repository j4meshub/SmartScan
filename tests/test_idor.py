from __future__ import annotations

import hashlib
import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.models import AuditLog, Role, User


def register(client: TestClient, prefix: str) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:10]
    phone_suffix = str(uuid.uuid4().int % 10_000_000).zfill(7)
    username = f"{prefix}_{suffix}"
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{phone_suffix}",
            "sms_code": main.settings.dev_sms_code,
            "username": username,
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, username


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (64, 96), "white")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def create_project(client: TestClient, headers: dict[str, str], title: str) -> dict[str, object]:
    response = client.post(
        "/v1/projects",
        json={"title": title, "mode": "document", "reading_order": "ltr"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_cross_user_project_page_and_upload_ids_are_hidden() -> None:
    with TestClient(main.app) as client:
        owner_headers, _ = register(client, "idor_owner")
        attacker_headers, _ = register(client, "idor_attacker")
        project = create_project(client, owner_headers, "私有项目")
        project_id = str(project["id"])
        image = jpeg_bytes()

        uploaded_page = client.post(
            f"/v1/projects/{project_id}/pages",
            files={"file": ("private.jpg", image, "image/jpeg")},
            headers=owner_headers,
        )
        assert uploaded_page.status_code == 202, uploaded_page.text
        page_id = uploaded_page.json()["id"]

        for path in (
            f"/v1/projects/{project_id}",
            f"/v1/projects/{project_id}/pages",
            f"/v1/pages/{page_id}/content",
        ):
            response = client.get(path, headers=attacker_headers)
            assert response.status_code == 404, (path, response.text)

        foreign_direct_upload = client.post(
            f"/v1/projects/{project_id}/pages",
            files={"file": ("stolen.jpg", image, "image/jpeg")},
            headers=attacker_headers,
        )
        assert foreign_direct_upload.status_code == 404

        digest = hashlib.sha256(image).hexdigest()
        create_body = {
            "project_id": project_id,
            "file_name": "private.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": len(image),
            "sha256": digest,
            "idempotency_key": f"idor-{uuid.uuid4().hex}",
        }
        foreign_session = client.post("/v1/uploads", json=create_body, headers=attacker_headers)
        assert foreign_session.status_code == 404

        initiated = client.post("/v1/uploads", json=create_body, headers=owner_headers)
        assert initiated.status_code == 201, initiated.text
        upload_id = initiated.json()["id"]
        chunk_hash = hashlib.sha256(image).hexdigest()

        hidden = client.get(f"/v1/uploads/{upload_id}", headers=attacker_headers)
        assert hidden.status_code == 404
        unauthenticated = client.get(f"/v1/uploads/{upload_id}")
        assert unauthenticated.status_code == 401
        assert unauthenticated.json() == {"detail": "authentication required"}
        hidden_chunk = client.put(
            f"/v1/uploads/{upload_id}/chunks/0",
            content=image,
            headers={**attacker_headers, "X-Chunk-Sha256": chunk_hash},
        )
        assert hidden_chunk.status_code == 404
        hidden_complete = client.post(f"/v1/uploads/{upload_id}/complete", headers=attacker_headers)
        assert hidden_complete.status_code == 404

        missing_project = client.get(f"/v1/projects/{uuid.uuid4()}", headers=attacker_headers)
        assert missing_project.status_code == 404
        assert missing_project.json() == {"detail": "project not found"}


def test_regular_user_cannot_enter_admin_endpoints() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "idor_regular")
        response = client.get("/v1/admin/users", headers=headers)
        assert response.status_code == 403
        assert response.json() == {"detail": "admin access required"}


def test_admin_cross_user_reads_are_allowed_and_audited() -> None:
    with TestClient(main.app) as client:
        owner_headers, owner_name = register(client, "audit_owner")
        admin_headers, admin_name = register(client, "audit_admin")
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == admin_name))
            owner = db.scalar(select(User).where(User.username == owner_name))
            assert admin is not None and owner is not None
            admin.role = Role.admin
            owner_id = owner.id
            db.commit()

        project = create_project(client, owner_headers, "管理员审计项目")
        project_id = str(project["id"])
        image = jpeg_bytes()
        page = client.post(
            f"/v1/projects/{project_id}/pages",
            files={"file": ("audit.jpg", image, "image/jpeg")},
            headers=owner_headers,
        )
        assert page.status_code == 202

        assert client.get(f"/v1/projects/{project_id}", headers=admin_headers).status_code == 200
        listed_pages = client.get(f"/v1/projects/{project_id}/pages", headers=admin_headers)
        assert listed_pages.status_code == 200
        assert [item["id"] for item in listed_pages.json()] == [page.json()["id"]]
        assert (
            client.get(f"/v1/pages/{page.json()['id']}/content", headers=admin_headers).status_code
            == 200
        )
        listed = client.get(f"/v1/admin/users/{owner_id}/projects", headers=admin_headers)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [project_id]

        with SessionLocal() as db:
            actions = set(
                db.scalars(select(AuditLog.action).where(AuditLog.target_user_id == owner_id)).all()
            )
        assert {"view_project", "view_pages", "download_page", "view_user_projects"}.issubset(
            actions
        )


def test_role_matrix_hides_admin_and_super_admin_resources() -> None:
    with TestClient(main.app) as client:
        regular_headers, _ = register(client, "matrix_regular")
        admin_headers, admin_name = register(client, "matrix_admin")
        other_admin_headers, other_admin_name = register(client, "matrix_other_admin")
        super_headers, super_name = register(client, "matrix_super")
        with SessionLocal() as db:
            role_by_name = {
                admin_name: Role.admin,
                other_admin_name: Role.admin,
                super_name: Role.super_admin,
            }
            users = db.scalars(select(User).where(User.username.in_(role_by_name))).all()
            for user in users:
                user.role = role_by_name[user.username]
            db.commit()

        regular_project = create_project(client, regular_headers, "普通用户项目")
        other_admin_project = create_project(client, other_admin_headers, "其他管理员项目")
        super_project = create_project(client, super_headers, "超级管理员项目")

        assert (
            client.get(f"/v1/projects/{regular_project['id']}", headers=admin_headers).status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/projects/{other_admin_project['id']}", headers=admin_headers
            ).status_code
            == 404
        )
        assert (
            client.get(f"/v1/projects/{super_project['id']}", headers=admin_headers).status_code
            == 404
        )
        assert (
            client.get(
                f"/v1/projects/{other_admin_project['id']}", headers=super_headers
            ).status_code
            == 200
        )
