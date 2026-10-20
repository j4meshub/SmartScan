from __future__ import annotations

import io
import json
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id
from services.api.app.models import AuditLog, ExportArtifact, ProcessingJob, ScanPage
from services.worker.app.main import process


def register(client: TestClient, prefix: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}",
            "sms_code": main.settings.dev_sms_code,
            "username": f"{prefix}_{suffix}",
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def jpeg_bytes(width: int, height: int, color: str) -> bytes:
    image = Image.new("RGB", (width, height), color)
    output = io.BytesIO()
    image.save(output, "JPEG", quality=96)
    return output.getvalue()


def add_processed_page(
    client: TestClient,
    *,
    headers: dict[str, str],
    project_id: str,
    width: int,
    height: int,
    color: str,
) -> str:
    response = client.post(
        f"/v1/projects/{project_id}/pages",
        files={"file": ("page.jpg", jpeg_bytes(width, height, color), "image/jpeg")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    page_id = response.json()["id"]
    with SessionLocal() as db:
        job_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.page_id == page_id))
        assert job_id is not None
        claim = claim_job_by_id(db, job_id, worker_id="export-test")
        assert claim is not None
        db.commit()
    process(claim)
    return page_id


def test_multi_page_jpg_quality_and_pdf_current_ocr_layer() -> None:
    with TestClient(main.app) as client:
        headers = register(client, "export_owner")
        project = client.post(
            "/v1/projects",
            json={"title": "季度：报告.pdf", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]
        first_id = add_processed_page(
            client,
            headers=headers,
            project_id=project_id,
            width=2600,
            height=1800,
            color="white",
        )
        add_processed_page(
            client,
            headers=headers,
            project_id=project_id,
            width=1800,
            height=2600,
            color="ivory",
        )
        with SessionLocal() as db:
            first = db.get(ScanPage, first_id)
            assert first is not None
            first.ocr_status = "ready"
            first.ocr_result_version = first.active_result_version
            first.ocr_text = "季度报告"
            first.ocr_details = json.dumps(
                {
                    "schema_version": 1,
                    "lines": [{"text": "季度报告", "confidence": 0.98, "box": [50, 60, 450, 150]}],
                },
                ensure_ascii=False,
            )
            db.commit()

        jpg = client.post(
            f"/v1/projects/{project_id}/exports",
            json={"format": "jpg", "quality": "small", "include_ocr_text": False},
            headers=headers,
        )
        assert jpg.status_code == 201, jpg.text
        assert jpg.json()["status"] == "ready"
        assert jpg.json()["page_count"] == 2
        assert len(jpg.json()["artifacts"]) == 2
        assert [item["sequence"] for item in jpg.json()["artifacts"]] == [1, 2]
        assert all("：" not in item["file_name"] for item in jpg.json()["artifacts"])
        with SessionLocal() as db:
            artifacts = list(
                db.scalars(
                    select(ExportArtifact)
                    .where(ExportArtifact.export_id == jpg.json()["id"])
                    .order_by(ExportArtifact.sequence)
                )
            )
            for artifact in artifacts:
                path = main.settings.storage_root / artifact.file_path
                assert path.is_file()
                with Image.open(path) as rendered:
                    assert max(rendered.size) <= 1600

        pdf = client.post(
            f"/v1/projects/{project_id}/exports",
            json={"format": "pdf", "quality": "balanced", "include_ocr_text": True},
            headers=headers,
        )
        assert pdf.status_code == 201, pdf.text
        assert pdf.json()["page_count"] == 2
        assert pdf.json()["ocr_pages_used"] == 1
        assert len(pdf.json()["artifacts"]) == 1
        with SessionLocal() as db:
            artifact = db.get(ExportArtifact, pdf.json()["artifacts"][0]["id"])
            assert artifact is not None
            assert (
                (main.settings.storage_root / artifact.file_path).read_bytes().startswith(b"%PDF")
            )


def test_export_stale_ocr_falls_back_and_cross_user_is_hidden_and_audited() -> None:
    with TestClient(main.app) as client:
        owner_headers = register(client, "export_owner2")
        attacker_headers = register(client, "export_attacker")
        project = client.post(
            "/v1/projects",
            json={"title": "私有扫描", "mode": "document", "reading_order": "ltr"},
            headers=owner_headers,
        )
        project_id = project.json()["id"]
        page_id = add_processed_page(
            client,
            headers=owner_headers,
            project_id=project_id,
            width=800,
            height=1000,
            color="white",
        )
        with SessionLocal() as db:
            page = db.get(ScanPage, page_id)
            assert page is not None
            page.ocr_status = "ready"
            page.ocr_result_version = page.active_result_version - 1
            page.ocr_text = "过期内容"
            page.ocr_details = json.dumps(
                {"schema_version": 1, "lines": [{"text": "过期内容", "box": [1, 1, 20, 20]}]}
            )
            db.commit()
        exported = client.post(
            f"/v1/projects/{project_id}/exports",
            json={"format": "pdf", "quality": "clear", "include_ocr_text": True},
            headers=owner_headers,
        )
        assert exported.status_code == 201, exported.text
        assert exported.json()["ocr_pages_used"] == 0
        export_id = exported.json()["id"]
        assert client.get(f"/v1/exports/{export_id}", headers=attacker_headers).status_code == 404
        assert (
            client.post(
                f"/v1/projects/{project_id}/exports",
                json={"format": "jpg", "quality": "balanced"},
                headers=attacker_headers,
            ).status_code
            == 404
        )
        with SessionLocal() as db:
            denied = list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.object_type.in_(("export", "project")),
                        AuditLog.result == "denied",
                    )
                )
            )
            assert {item.action for item in denied} >= {"view_export", "create_export"}
