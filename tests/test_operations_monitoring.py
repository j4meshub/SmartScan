from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from services.api.app import main, ops_metrics, ops_routes, scan_routes
from services.api.app.capacity import (
    CapacityError,
    ensure_new_upload_capacity,
    ensure_queue_capacity,
    pending_upload_bytes,
    storage_capacity,
)
from services.api.app.config import Settings
from services.api.app.database import Base, SessionLocal
from services.api.app.job_service import claim_next_job
from services.api.app.migrations import upgrade_database
from services.api.app.models import (
    ProcessingJob,
    ScanProject,
    UploadChunk,
    UploadSession,
    User,
    WorkerHeartbeat,
)
from services.api.app.worker_status import record_worker_heartbeat
from tools.render_monitoring_config import MonitoringConfigError, render_monitoring_config


def isolated_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'ops.db').as_posix()}")
    Base.metadata.create_all(engine)
    return Session(engine)


def add_user_project(db: Session, suffix: str) -> tuple[User, ScanProject]:
    user = User(
        username=f"ops_{suffix}",
        password_hash="hash",
        phone_hmac=hashlib.sha256(suffix.encode()).hexdigest(),
        phone_masked="+86******0003",
    )
    db.add(user)
    db.flush()
    project = ScanProject(owner_user_id=user.id, title="运维保护")
    db.add(project)
    db.flush()
    return user, project


def add_pending_upload(
    db: Session,
    user: User,
    project: ScanProject,
    *,
    size_bytes: int,
    received_bytes: int = 0,
) -> UploadSession:
    upload = UploadSession(
        owner_user_id=user.id,
        project_id=project.id,
        idempotency_key=str(uuid.uuid4()),
        file_name="page.jpg",
        mime_type="image/jpeg",
        size_bytes=size_bytes,
        expected_sha256="a" * 64,
        chunk_size=size_bytes,
        total_chunks=1,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(upload)
    db.flush()
    if received_bytes:
        db.add(
            UploadChunk(
                upload_id=upload.id,
                chunk_index=0,
                size_bytes=received_bytes,
                sha256="b" * 64,
                relative_path=f"users/{user.id}/temp/{upload.id}/00000000.part",
            )
        )
        db.flush()
    return upload


def test_storage_capacity_counts_only_remaining_upload_reservations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with isolated_session(tmp_path) as db:
        user, project = add_user_project(db, "capacity")
        add_pending_upload(db, user, project, size_bytes=80, received_bytes=30)
        db.commit()
        monkeypatch.setattr(
            "services.api.app.capacity.shutil.disk_usage",
            lambda _: SimpleNamespace(
                total=1_000_000_000,
                used=800_000_000,
                free=200_000_000,
            ),
        )
        settings = Settings(
            _env_file=None,
            storage_root=tmp_path / "storage",
            storage_min_free_bytes=64 * 1024**2,
            storage_min_free_percent=5,
        )
        assert pending_upload_bytes(db) == 50
        capacity = storage_capacity(db, settings, additional_bytes=25)
        assert capacity.reserved_upload_bytes == 50
        assert not capacity.protected


def test_new_upload_fails_closed_for_disk_and_user_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    with isolated_session(tmp_path) as db:
        user, project = add_user_project(db, "quota")
        add_pending_upload(db, user, project, size_bytes=50)
        db.commit()
        monkeypatch.setattr(
            "services.api.app.capacity.shutil.disk_usage",
            lambda _: SimpleNamespace(
                total=200_000_000,
                used=100_000_000,
                free=100_000_000,
            ),
        )
        disk_settings = Settings(
            _env_file=None,
            storage_root=storage,
            storage_min_free_bytes=64 * 1024**2,
            storage_min_free_percent=5,
        )
        with pytest.raises(CapacityError, match="storage_capacity_reached") as disk_error:
            ensure_new_upload_capacity(
                db,
                disk_settings,
                owner_user_id=user.id,
                size_bytes=40_000_000,
            )
        assert disk_error.value.status_code == 507

        monkeypatch.setattr(
            "services.api.app.capacity.shutil.disk_usage",
            lambda _: SimpleNamespace(
                total=1_000_000_000,
                used=100_000_000,
                free=900_000_000,
            ),
        )
        quota_settings = Settings(
            _env_file=None,
            storage_root=storage,
            storage_min_free_bytes=64 * 1024**2,
            storage_min_free_percent=5,
            user_storage_quota_bytes=75,
        )
        with pytest.raises(CapacityError, match="user_storage_quota_reached") as quota_error:
            ensure_new_upload_capacity(
                db,
                quota_settings,
                owner_user_id=user.id,
                size_bytes=30,
            )
        assert quota_error.value.status_code == 413


def test_queue_high_water_and_per_user_processing_fairness(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        queue_high_water_jobs=3,
        max_active_jobs_per_user=1,
    )
    with isolated_session(tmp_path) as db:
        first_user, first_project = add_user_project(db, "fair_a")
        second_user, second_project = add_user_project(db, "fair_b")
        jobs: list[ProcessingJob] = []
        for user, project in (
            (first_user, first_project),
            (first_user, first_project),
            (second_user, second_project),
        ):
            job = ProcessingJob(
                owner_user_id=user.id,
                project_id=project.id,
                kind="document",
            )
            db.add(job)
            jobs.append(job)
        db.commit()

        with pytest.raises(CapacityError, match="queue_capacity_reached") as error:
            ensure_queue_capacity(db, settings)
        assert error.value.status_code == 429

        settings = Settings(
            _env_file=None,
            queue_high_water_jobs=4,
            max_active_jobs_per_user=1,
        )
        first = claim_next_job(db, worker_id="worker-a", settings=settings)
        assert first is not None
        db.commit()
        second = claim_next_job(db, worker_id="worker-b", settings=settings)
        assert second is not None
        db.commit()
        claimed = {first.job_id, second.job_id}
        owners = {
            db.get(ProcessingJob, job_id).owner_user_id  # type: ignore[union-attr]
            for job_id in claimed
        }
        assert owners == {first_user.id, second_user.id}
        assert claim_next_job(db, worker_id="worker-c", settings=settings) is None


def test_worker_heartbeat_updates_busy_state_without_resetting_start(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    with isolated_session(tmp_path) as db:
        heartbeat = record_worker_heartbeat(
            db,
            worker_id="worker:1",
            busy_job_id=None,
            now=now,
        )
        db.commit()
        started_at = heartbeat.started_at
        record_worker_heartbeat(
            db,
            worker_id="worker:1",
            busy_job_id="job-1",
            now=now + timedelta(seconds=10),
        )
        db.commit()
        current = db.get(WorkerHeartbeat, "worker:1")
        assert current is not None
        assert current.started_at == started_at
        heartbeat_at = current.heartbeat_at
        if heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
        assert heartbeat_at == now + timedelta(seconds=10)
        assert current.busy_job_id == "job-1"


def register(client: TestClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}",
            "sms_code": main.settings.dev_sms_code,
            "username": f"ops_api_{suffix}",
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_upload_capacity_error_is_stable_and_metrics_are_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upgrade_database(main.settings.database_url)
    token = "m" * 40
    monkeypatch.setattr(
        ops_routes,
        "settings",
        Settings(
            _env_file=None,
            storage_root=main.settings.storage_root,
            storage_min_free_bytes=64 * 1024**2,
            ops_metrics_enabled=True,
            ops_metrics_token=token,
        ),
    )
    with TestClient(main.app) as client:
        headers = register(client)
        project = client.post(
            "/v1/projects",
            json={"title": "容量拒绝", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        )
        assert project.status_code == 201
        upload_payload = {
            "project_id": project.json()["id"],
            "idempotency_key": str(uuid.uuid4()),
            "file_name": "page.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 100,
            "sha256": "a" * 64,
        }
        created = client.post("/v1/uploads", json=upload_payload, headers=headers)
        assert created.status_code == 201

        def reject_capacity(*_: object, **__: object) -> None:
            raise CapacityError("storage_capacity_reached", 507)

        monkeypatch.setattr(scan_routes, "ensure_new_upload_capacity", reject_capacity)
        replay = client.post("/v1/uploads", json=upload_payload, headers=headers)
        assert replay.status_code == 201
        assert replay.json()["id"] == created.json()["id"]
        rejected_payload = dict(upload_payload)
        rejected_payload["idempotency_key"] = str(uuid.uuid4())
        rejected = client.post(
            "/v1/uploads",
            json=rejected_payload,
            headers=headers,
        )
        assert rejected.status_code == 507
        assert rejected.json()["detail"] == "storage_capacity_reached"

        assert client.get("/internal/metrics").status_code == 404
        assert (
            client.get("/internal/metrics", headers={"Authorization": "Bearer wrong"}).status_code
            == 404
        )
        metrics = client.get(
            "/internal/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert metrics.status_code == 200
        assert "text/plain" in metrics.headers["content-type"]
        assert "smartscan_database_up 1" in metrics.text
        assert "smartscan_storage_protection_active" in metrics.text
        assert "smartscan_queue_oldest_age_seconds" in metrics.text
        assert "smartscan_workers" in metrics.text
        assert 'route="/v1/projects"' in metrics.text
        assert project.json()["id"] not in metrics.text
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username.like("ops_api_%")))
            assert user is not None
            assert user.id not in metrics.text
        assert str(main.settings.storage_root) not in metrics.text


def test_legacy_direct_upload_uses_capacity_protection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upgrade_database(main.settings.database_url)
    with TestClient(main.app) as client:
        headers = register(client)
        project = client.post(
            "/v1/projects",
            json={"title": "兼容上传保护", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        )
        assert project.status_code == 201

        def reject_capacity(*_: object, **__: object) -> None:
            raise CapacityError("storage_capacity_reached", 507)

        monkeypatch.setattr(scan_routes, "ensure_new_upload_capacity", reject_capacity)
        response = client.post(
            f"/v1/projects/{project.json()['id']}/pages",
            files={"file": ("page.jpg", b"\xff\xd8\xff" + b"a" * 32, "image/jpeg")},
            headers=headers,
        )
        assert response.status_code == 507
        assert response.json()["detail"] == "storage_capacity_reached"


def test_metrics_remain_scrapeable_when_database_and_storage_snapshot_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_: object, **__: object) -> list[str]:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(ops_metrics, "_database_snapshot", unavailable)
    monkeypatch.setattr(ops_metrics, "storage_capacity", unavailable)
    with isolated_session(tmp_path) as db:
        rendered = ops_metrics.render_operational_metrics(
            db,
            Settings(_env_file=None, storage_root=tmp_path / "storage"),
        ).decode("utf-8")

    assert "smartscan_database_up 0" in rendered
    assert "smartscan_storage_protection_active 1" in rendered


def test_monitoring_renderer_requires_matching_secret_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    token = "R7mN2xK8vB5pT6wL3dF0hJ4aQ9sC1zY8"
    runtime = tmp_path / "runtime.env"
    token_file = tmp_path / "ops-metrics.token"
    runtime.write_text(
        f"SMARTSCAN_OPS_METRICS_ENABLED=true\nSMARTSCAN_OPS_METRICS_TOKEN={token}\n",
        encoding="utf-8",
    )
    token_file.write_text(token + "\n", encoding="utf-8")
    target = tmp_path / "rendered"
    result = render_monitoring_config(
        runtime_env_path=runtime,
        metrics_token_path=token_file,
        alert_webhook_url="https://alerts.ci.smartscan.test/hooks/staging-token",
        target_dir=target,
        ci_fixture=True,
    )

    summary = result.safe_summary()
    assert summary["secrets_included"] is False
    assert token not in str(summary)
    assert "staging-token" not in str(summary)
    assert yaml.safe_load((target / "prometheus.yml").read_text(encoding="utf-8"))
    assert yaml.safe_load((target / "rules.yml").read_text(encoding="utf-8"))
    alertmanager = yaml.safe_load((target / "alertmanager.yml").read_text(encoding="utf-8"))
    assert alertmanager["receivers"][0]["webhook_configs"][0]["send_resolved"] is True

    with pytest.raises(MonitoringConfigError, match="拒绝覆盖"):
        render_monitoring_config(
            runtime_env_path=runtime,
            metrics_token_path=token_file,
            alert_webhook_url="https://alerts.ci.smartscan.test/hooks/staging-token",
            target_dir=target,
            ci_fixture=True,
        )

    token_file.write_text("different-monitoring-token-value-123456\n", encoding="utf-8")
    with pytest.raises(MonitoringConfigError, match="不一致"):
        render_monitoring_config(
            runtime_env_path=runtime,
            metrics_token_path=token_file,
            alert_webhook_url="https://alerts.ci.smartscan.test/hooks/staging-token",
            target_dir=tmp_path / "mismatch",
            ci_fixture=True,
        )


@pytest.mark.parametrize(
    "webhook",
    (
        "http://alerts.smartscan.company/hook",
        "https://user:password@alerts.smartscan.company/hook",
        "https://alerts.smartscan.company:8443/hook",
        "https://alerts.smartscan.company/hook#fragment",
    ),
)
def test_monitoring_renderer_rejects_unsafe_webhooks(tmp_path: Path, webhook: str) -> None:
    token = "A7mN2xK8vB5pT6wL3dF0hJ4aQ9sC1zY8"
    runtime = tmp_path / "runtime.env"
    token_file = tmp_path / "ops-metrics.token"
    runtime.write_text(
        f"SMARTSCAN_OPS_METRICS_ENABLED=true\nSMARTSCAN_OPS_METRICS_TOKEN={token}\n",
        encoding="utf-8",
    )
    token_file.write_text(token + "\n", encoding="utf-8")
    with pytest.raises(MonitoringConfigError):
        render_monitoring_config(
            runtime_env_path=runtime,
            metrics_token_path=token_file,
            alert_webhook_url=webhook,
            target_dir=tmp_path / "unsafe",
            ci_fixture=True,
        )
