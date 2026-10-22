from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from test_account_deletion import (
    register as register_deletion_user,
)
from test_account_deletion import (
    request_deletion,
    unique_phone,
)
from test_ai_business import (
    create_enhancement,
    create_processed_page,
    enable_ai,
    register,
)

from services.api.app import main
from services.api.app.account_deletion import process_account_deletion
from services.api.app.ai_media import AiMediaError, IssuedMediaGrant, issue_media_grant
from services.api.app.config import Settings
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_ai_job_by_id, claim_job_by_id
from services.api.app.models import (
    AccountDeletionRequest,
    AiEnhancementTask,
    AiMediaGrant,
    JobStatus,
    ProcessingJob,
)
from services.worker.app.ai_gateway import AiGatewayClient

ROOT = Path(__file__).parents[1]


def test_media_grant_is_hashed_scoped_revocable_and_not_exposed() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_media")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-secure-media-0001")

        with SessionLocal() as db:
            job_id = str(task_view["processing_job_id"])
            assert claim_job_by_id(db, job_id, worker_id="base-worker") is None
            claim = claim_ai_job_by_id(db, job_id, worker_id="ai-worker")
            assert claim is not None
            job = db.get(ProcessingJob, claim.job_id)
            assert job is not None and job.status == JobStatus.optional_enhancing
            issued = issue_media_grant(db, enhancement_task_id=str(task_view["id"]))
            raw_token = issued.access_token
            grant_id = issued.grant.id
            assert len(raw_token) >= 43
            assert issued.grant.token_hash == hashlib.sha256(raw_token.encode("ascii")).hexdigest()
            assert raw_token != issued.grant.token_hash
            db.commit()

        listing = client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=headers)
        assert listing.status_code == 200
        assert raw_token not in listing.text
        assert client.get("/v1/ai-media").status_code == 404
        media = client.get(
            "/v1/ai-media",
            headers={"X-SmartScan-AI-Media-Token": raw_token},
        )
        assert media.status_code == 200
        assert media.headers["cache-control"] == "private, no-store, max-age=0"
        assert media.headers["content-type"].startswith("image/jpeg")
        assert len(media.content) > 0
        with SessionLocal() as db:
            grant = db.get(AiMediaGrant, grant_id)
            assert grant is not None and grant.access_count == 1
            assert grant.last_accessed_at is not None

        disabled = client.put(
            f"/v1/projects/{project_id}/ai-settings",
            json={"enabled": False},
            headers=headers,
        )
        assert disabled.status_code == 200
        assert (
            client.get(
                "/v1/ai-media",
                headers={"X-SmartScan-AI-Media-Token": raw_token},
            ).status_code
            == 404
        )
        with SessionLocal() as db:
            grant = db.get(AiMediaGrant, grant_id)
            assert grant is not None and grant.revoked_at is not None
            try:
                issue_media_grant(db, enhancement_task_id=str(task_view["id"]))
            except AiMediaError as exc:
                assert exc.code == "project_ai_not_enabled"
            else:
                raise AssertionError("未授权项目不得签发媒体令牌")
        deleted = client.delete(f"/v1/projects/{project_id}", headers=headers)
        assert deleted.status_code == 202
        with SessionLocal() as db:
            assert db.get(AiMediaGrant, grant_id) is None


def test_media_grant_expires_and_source_version_change_revokes_access() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_media_stale")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-secure-media-0002")
        now = datetime.now(UTC)
        with SessionLocal() as db:
            claim = claim_ai_job_by_id(
                db,
                str(task_view["processing_job_id"]),
                worker_id="ai-worker-stale",
                now=now,
            )
            assert claim is not None
            short_settings = Settings(_env_file=None, ai_media_grant_ttl_seconds=60)
            issued = issue_media_grant(
                db,
                enhancement_task_id=str(task_view["id"]),
                settings=short_settings,
                now=now,
            )
            raw_token = issued.access_token
            issued.grant.expires_at = now - timedelta(seconds=1)
            db.commit()
        assert (
            client.get(
                "/v1/ai-media",
                headers={"X-SmartScan-AI-Media-Token": raw_token},
            ).status_code
            == 404
        )

        with SessionLocal() as db:
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            assert task is not None
            task.status = "processing"
            renewed = issue_media_grant(db, enhancement_task_id=task.id, now=now)
            renewed_token = renewed.access_token
            db.commit()
        rotated = client.post(
            f"/v1/pages/{page_id}/rotations",
            json={"degrees": 90},
            headers=headers,
        )
        assert rotated.status_code == 200
        assert (
            client.get(
                "/v1/ai-media",
                headers={"X-SmartScan-AI-Media-Token": renewed_token},
            ).status_code
            == 404
        )
        with SessionLocal() as db:
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            assert task is not None and task.status == "stale"


def test_worker_gateway_client_uses_internal_token_without_redirects() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "evidence": {"disposition": "candidate"},
                "network": {"network_ready": True},
            },
        )

    settings = Settings(
        _env_file=None,
        ai_gateway_url="http://ai-gateway:8010",
        ai_internal_token="i" * 32,
        ai_provider_id="vision-main",
        ai_media_base_url="https://media.example/v1/ai-media/",
    )
    grant = AiMediaGrant(
        id="grant-1",
        enhancement_task_id="10000000-0000-4000-8000-000000000001",
        owner_user_id="owner-1",
        project_id="project-1",
        page_id="page-1",
        page_result_id="result-1",
        source_result_version=1,
        token_hash="a" * 64,
        mime_type="image/jpeg",
        sha256="b" * 64,
        byte_size=123,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        access_count=0,
    )
    issued = IssuedMediaGrant(grant=grant, access_token="T" * 43)
    result = AiGatewayClient(
        settings,
        transport=httpx.MockTransport(handler),
    ).execute(
        enhancement_task_id=grant.enhancement_task_id,
        task={"schema_version": "1.0"},
        media=issued,
    )

    assert result.evidence["disposition"] == "candidate"
    assert captured["url"] == "http://ai-gateway:8010/v1/tasks/vision-main/execute"
    assert captured["authorization"] == f"Bearer {'i' * 32}"
    assert '"access_token":"' + "T" * 43 + '"' in str(captured["body"])


def test_account_deletion_removes_media_grants() -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        _, _, headers = register_deletion_user(client, phone)
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-account-delete-0001")
        with SessionLocal() as db:
            claim = claim_ai_job_by_id(
                db,
                str(task_view["processing_job_id"]),
                worker_id="ai-account-delete",
            )
            assert claim is not None
            issued = issue_media_grant(db, enhancement_task_id=str(task_view["id"]))
            grant_id = issued.grant.id
            db.commit()
        canceled = client.post(
            f"/v1/jobs/{task_view['processing_job_id']}/cancel",
            headers=headers,
        )
        assert canceled.status_code == 200
        deletion = request_deletion(client, phone=phone, headers=headers)
        due = datetime.now(UTC) - timedelta(seconds=1)
        with SessionLocal() as db:
            request = db.get(AccountDeletionRequest, str(deletion["id"]))
            assert request is not None
            request.execute_after = due
            db.commit()
            result = process_account_deletion(db, request.id, now=due + timedelta(seconds=1))
            assert result.status.value == "completed"
        with SessionLocal() as db:
            assert db.get(AiMediaGrant, grant_id) is None


def test_nginx_only_exposes_redacted_media_bridge_not_ai_gateway() -> None:
    nginx = (ROOT / "deploy" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "compose" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "location ^~ /api/v1/ai-media/" in nginx
    assert "~^/api/v1/ai-media/([A-Za-z0-9_-]{22,128})$ $1;" in nginx
    assert "access_log off;" in nginx
    assert "proxy_set_header X-SmartScan-AI-Media-Token $ai_media_token;" in nginx
    assert "rewrite ^ /v1/ai-media break;" in nginx
    assert "proxy_pass http://api;" in nginx
    assert "proxy_pass http://ai-gateway" not in nginx
    ai_gateway_section = compose.split("  ai-gateway:", 1)[1].split("  nginx:", 1)[0]
    assert 'expose: ["8010"]' in ai_gateway_section
    assert "ports:" not in ai_gateway_section
