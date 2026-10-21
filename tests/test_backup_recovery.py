from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.api.app.migrations import upgrade_database
from services.api.app.models import ScanPage, ScanProject, User
from services.api.app.restore_verification import RestoreVerificationError, verify_restore
from tools.backup_evidence import EvidenceError, atomic_write_json, load_successful_backup
from tools.run_backup import build_plan
from tools.validate_backup_config import BackupConfigError, validate_backup_config
from tools.validate_staging_config import load_env_file

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "staging"


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


def _config_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    deploy = load_env_file(FIXTURE_ROOT / "deploy.env")
    backup = load_env_file(FIXTURE_ROOT / "backup.env")
    deploy_path = tmp_path / "deploy.env"
    backup_path = tmp_path / "backup.env"
    password_path = tmp_path / "restic-password"
    _write_env(deploy_path, deploy)
    _write_env(backup_path, backup)
    password_path.write_text("ci-restic-password-32-characters-minimum", encoding="utf-8")
    password_path.chmod(0o600)
    return deploy_path, backup_path, password_path


def test_backup_config_and_plan_contain_no_secret(tmp_path: Path) -> None:
    deploy_path, backup_path, password_path = _config_files(tmp_path)
    config = validate_backup_config(deploy_path, backup_path, password_path, ci_fixture=True)
    run_id = "20261022T120000Z-123456789abc"
    commands = build_plan(deploy_path, run_id, config)
    rendered = json.dumps(commands)

    assert len(commands) == 8
    assert rendered.count("backup-restic") == 7
    assert "ci-restic-password" not in rendered
    assert "AWS_SECRET_ACCESS_KEY" not in rendered
    assert config.retention_daily == 7
    assert config.retention_weekly == 4


@pytest.mark.parametrize(
    ("repository", "message"),
    [
        ("s3:http://backup.company/bucket", "HTTPS"),
        ("s3:https://user:secret@backup.company/bucket", "禁止凭据"),
        ("rest:https://staging.ci.smartscan.test/repo", "主机分离"),
        ("local:/srv/backup", "只允许"),
    ],
)
def test_backup_repository_boundary_fails_closed(
    tmp_path: Path, repository: str, message: str
) -> None:
    deploy_path, backup_path, password_path = _config_files(tmp_path)
    values = load_env_file(backup_path)
    values["RESTIC_REPOSITORY"] = repository
    _write_env(backup_path, values)
    with pytest.raises(BackupConfigError, match=message):
        validate_backup_config(deploy_path, backup_path, password_path, ci_fixture=True)


def test_strict_backup_rejects_template_credentials(tmp_path: Path) -> None:
    deploy_path, backup_path, password_path = _config_files(tmp_path)
    deploy = load_env_file(deploy_path)
    deploy["SMARTSCAN_STAGING_HOST"] = "staging.smartscan.company"
    deploy["SMARTSCAN_STAGING_RESTIC_IMAGE"] = (
        "registry.smartscan.company/restic@sha256:"
        + hashlib.sha256(b"restic-production-image").hexdigest()
    )
    backup = load_env_file(backup_path)
    backup["RESTIC_REPOSITORY"] = "s3:https://backup.smartscan.company/smartscan-staging"
    _write_env(deploy_path, deploy)
    _write_env(backup_path, backup)

    with pytest.raises(BackupConfigError, match="模板凭据"):
        validate_backup_config(deploy_path, backup_path, password_path)

    backup["AWS_ACCESS_KEY_ID"] = "realistic-access-identifier"
    backup["AWS_SECRET_ACCESS_KEY"] = "realistic-secret-value-with-sufficient-entropy"
    _write_env(backup_path, backup)
    password_path.write_text("replace-with-a-real-restic-password-value", encoding="utf-8")
    with pytest.raises(BackupConfigError, match="密码仍是模板值"):
        validate_backup_config(deploy_path, backup_path, password_path)


def test_backup_evidence_requires_all_full_snapshot_ids(tmp_path: Path) -> None:
    snapshots = {
        kind: hashlib.sha256(kind.encode()).hexdigest() for kind in ("database", "files", "wal")
    }
    path = tmp_path / "evidence.json"
    payload = {
        "schema_version": 1,
        "status": "success",
        "run_id": "20261022T120000Z-123456789abc",
        "git_commit": "1" * 40,
        "snapshots": snapshots,
    }
    atomic_write_json(path, payload)
    assert load_successful_backup(path)["snapshots"] == snapshots
    payload["snapshots"]["wal"] = "short"
    atomic_write_json(path, payload)
    with pytest.raises(EvidenceError, match="快照 ID"):
        load_successful_backup(path)


def test_restore_verification_rejects_schema_without_super_admin(tmp_path: Path) -> None:
    database = tmp_path / "restored.db"
    url = f"sqlite:///{database.as_posix()}"
    upgrade_database(url)
    storage = tmp_path / "files"
    storage.mkdir()

    with pytest.raises(RestoreVerificationError, match="超级管理员"):
        verify_restore(url, storage)


def test_restore_verification_rejects_missing_storage_root(tmp_path: Path) -> None:
    database = tmp_path / "restored.db"
    url = f"sqlite:///{database.as_posix()}"
    upgrade_database(url)
    with pytest.raises(RestoreVerificationError, match="根目录"):
        verify_restore(url, tmp_path / "missing")


def test_restore_verification_checks_owned_file_hash(tmp_path: Path) -> None:
    database = tmp_path / "restored.db"
    url = f"sqlite:///{database.as_posix()}"
    upgrade_database(url)
    storage = tmp_path / "files"
    source = storage / "users" / "user-1" / "originals" / "page.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"trusted-original")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            session.add(
                User(
                    id="admin-1",
                    username="restore-admin",
                    password_hash="not-a-real-password",
                    phone_hmac="0" * 64,
                    phone_masked="***0000",
                    role="super_admin",
                )
            )
            session.add(
                User(
                    id="user-1",
                    username="restore-user",
                    password_hash="not-a-real-password",
                    phone_hmac="1" * 64,
                    phone_masked="***0001",
                )
            )
            session.add(ScanProject(id="project-1", owner_user_id="user-1", title="恢复验证"))
            session.add(
                ScanPage(
                    id="page-1",
                    project_id="project-1",
                    owner_user_id="user-1",
                    page_number=1,
                    original_path="users/user-1/originals/page.jpg",
                    sha256=digest,
                    size_bytes=source.stat().st_size,
                    mime_type="image/jpeg",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    result = verify_restore(url, storage)
    assert result["verified_file_count"] == 1
    assert result["super_admin_count"] == 1

    source.write_bytes(b"tampered")
    with pytest.raises(RestoreVerificationError, match="大小不一致|哈希不一致"):
        verify_restore(url, storage)
