from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.config import Settings
from tools.validate_staging_config import (
    DEFAULT_COMPOSE_FILE,
    StagingConfigError,
    load_env_file,
    validate_compose_contract,
    validate_staging_config,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "staging"


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8"
    )


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, str], dict[str, str]]:
    deploy = load_env_file(FIXTURE_ROOT / "deploy.env")
    runtime = load_env_file(FIXTURE_ROOT / "runtime.env")
    deploy_path = tmp_path / "deploy.env"
    runtime_path = tmp_path / "runtime.env"
    _write_env(deploy_path, deploy)
    _write_env(runtime_path, runtime)
    return deploy_path, runtime_path, deploy, runtime


def _make_strict(tmp_path: Path) -> tuple[Path, Path, dict[str, str], dict[str, str]]:
    deploy_path, runtime_path, deploy, runtime = _copy_fixture(tmp_path)
    deploy["SMARTSCAN_STAGING_HOST"] = "staging.smartscan.company"
    deploy["SMARTSCAN_STAGING_RUNTIME_ENV_FILE"] = str(runtime_path.resolve())
    deploy["POSTGRES_PASSWORD"] = "staging-database-password-8Jf6n2Qp"
    for key in (
        "SMARTSCAN_STAGING_POSTGRES_IMAGE",
        "SMARTSCAN_STAGING_API_IMAGE",
        "SMARTSCAN_STAGING_WORKER_IMAGE",
        "SMARTSCAN_STAGING_AI_GATEWAY_IMAGE",
        "SMARTSCAN_STAGING_WEB_IMAGE",
    ):
        name = key.removeprefix("SMARTSCAN_STAGING_").removesuffix("_IMAGE").lower()
        digest = hashlib.sha256(name.encode()).hexdigest()
        deploy[key] = f"registry.smartscan.company/smartscan/{name}@sha256:{digest}"
    runtime["SMARTSCAN_DATABASE_URL"] = (
        "postgresql+psycopg://smartscan:staging-database-password-8Jf6n2Qp@postgres:5432/smartscan"
    )
    runtime["SMARTSCAN_CORS_ORIGINS"] = '["https://staging.smartscan.company"]'
    runtime["SMARTSCAN_SECRET_KEY"] = "7yQ4zC9mN2xK8vB5pR1sT6wL3dF0hJ4a"
    runtime["SMARTSCAN_PHONE_HMAC_PEPPERS"] = json.dumps(
        {"ci-v1": "6mP2cX9vN4qR7tY1kL8bD5sF3wH0jA6z"}, separators=(",", ":")
    )
    runtime["SMARTSCAN_SUPERADMIN_PASSWORD"] = "8uV3mQ7xT2nK9pL5rD1s"
    _write_env(deploy_path, deploy)
    _write_env(runtime_path, runtime)
    return deploy_path, runtime_path, deploy, runtime


def test_ci_fixture_validates_and_summary_never_contains_secrets() -> None:
    config = validate_staging_config(
        FIXTURE_ROOT / "deploy.env",
        runtime_env_path=FIXTURE_ROOT / "runtime.env",
        ci_fixture=True,
    )

    rendered = json.dumps(config.safe_summary(), ensure_ascii=False)
    assert config.project_name == "smartscan-ci-staging"
    assert config.http_port == 18080
    assert "ci-only-staging-database-password" not in rendered
    assert "ci-only-secret-key" not in rendered
    assert config.safe_summary()["secrets_included"] is False


def test_realistic_strict_configuration_passes_without_contacting_server(tmp_path: Path) -> None:
    deploy_path, runtime_path, _, _ = _make_strict(tmp_path)

    config = validate_staging_config(deploy_path, runtime_env_path=runtime_path)

    assert config.host == "staging.smartscan.company"
    assert len(config.image_digests) == 5
    assert all(len(digest) == 64 for digest in config.image_digests)


def test_runtime_fixture_is_accepted_by_real_application_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in load_env_file(FIXTURE_ROOT / "runtime.env"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=FIXTURE_ROOT / "runtime.env")

    settings.validate_production()
    assert settings.env == "production"
    assert settings.cors_origins == ["https://staging.ci.smartscan.test"]
    assert settings.sms_mode == "disabled"
    assert settings.wecom_mode == "disabled"
    assert settings.ocr_enabled is True


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("COMPOSE_PROJECT_NAME", "smartscan", "项目名"),
        ("SMARTSCAN_STAGING_HOST", "api.smartscan.company", "staging 标签"),
        ("SMARTSCAN_STAGING_HTTP_PORT", "443", "独立端口"),
        ("SMARTSCAN_STAGING_DATA_ROOT", "/srv/smartscan/data", "独立 staging 根目录"),
        ("SMARTSCAN_STAGING_MODEL_ROOT", "/srv/smartscan/staging/data/models", "不得重叠或嵌套"),
        ("SMARTSCAN_STAGING_ISOLATION_ACK", "yes", "隔离确认"),
    ],
)
def test_isolation_boundaries_fail_closed(
    tmp_path: Path, key: str, value: str, message: str
) -> None:
    deploy_path, runtime_path, deploy, _ = _copy_fixture(tmp_path)
    deploy[key] = value
    _write_env(deploy_path, deploy)

    with pytest.raises(StagingConfigError, match=message):
        validate_staging_config(
            deploy_path,
            runtime_env_path=runtime_path,
            ci_fixture=True,
        )


def test_mutable_or_template_images_are_rejected_in_strict_mode(tmp_path: Path) -> None:
    deploy_path, runtime_path, deploy, _ = _make_strict(tmp_path)
    deploy["SMARTSCAN_STAGING_API_IMAGE"] = "registry.smartscan.company/smartscan/api:latest"
    _write_env(deploy_path, deploy)
    with pytest.raises(StagingConfigError, match="固定 sha256"):
        validate_staging_config(deploy_path, runtime_env_path=runtime_path)

    deploy["SMARTSCAN_STAGING_API_IMAGE"] = (
        "registry.smartscan.company/smartscan/api@sha256:" + "0" * 64
    )
    _write_env(deploy_path, deploy)
    with pytest.raises(StagingConfigError, match="模板 digest"):
        validate_staging_config(deploy_path, runtime_env_path=runtime_path)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("SMARTSCAN_AUTO_MIGRATE", "true", "自动迁移"),
        ("SMARTSCAN_SMS_MODE", "mock", "短信供应商"),
        ("SMARTSCAN_AI_PROVIDERS", '[{"id":"unsafe"}]', "关闭外部 AI"),
        ("SMARTSCAN_DEV_SMS_CODE", "246810", "开发验证码"),
        (
            "SMARTSCAN_CORS_ORIGINS",
            '["https://production.smartscan.company"]',
            "CORS",
        ),
    ],
)
def test_runtime_safety_settings_fail_closed(
    tmp_path: Path, key: str, value: str, message: str
) -> None:
    deploy_path, runtime_path, _, runtime = _copy_fixture(tmp_path)
    runtime[key] = value
    _write_env(runtime_path, runtime)

    with pytest.raises(StagingConfigError, match=message):
        validate_staging_config(
            deploy_path,
            runtime_env_path=runtime_path,
            ci_fixture=True,
        )


def test_database_password_must_match_runtime_url(tmp_path: Path) -> None:
    deploy_path, runtime_path, _, runtime = _copy_fixture(tmp_path)
    runtime["SMARTSCAN_DATABASE_URL"] = (
        "postgresql+psycopg://smartscan:different-password@postgres:5432/smartscan"
    )
    _write_env(runtime_path, runtime)

    with pytest.raises(StagingConfigError, match="密码不一致"):
        validate_staging_config(
            deploy_path,
            runtime_env_path=runtime_path,
            ci_fixture=True,
        )


def test_database_password_rejects_url_unsafe_characters(tmp_path: Path) -> None:
    deploy_path, runtime_path, deploy, _ = _copy_fixture(tmp_path)
    deploy["POSTGRES_PASSWORD"] = "ci-only-password-with-unsafe-#"
    _write_env(deploy_path, deploy)

    with pytest.raises(StagingConfigError, match="安全字符"):
        validate_staging_config(
            deploy_path,
            runtime_env_path=runtime_path,
            ci_fixture=True,
        )


def test_duplicate_environment_key_is_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / "duplicate.env"
    env_path.write_text("KEY=one\nKEY=two\n", encoding="utf-8")

    with pytest.raises(StagingConfigError, match="重复"):
        load_env_file(env_path)


def test_staging_compose_has_no_server_build_or_direct_database_port() -> None:
    validate_compose_contract(DEFAULT_COMPOSE_FILE)
    document = DEFAULT_COMPOSE_FILE.read_text(encoding="utf-8")

    assert "build:" not in document
    assert "127.0.0.1:${SMARTSCAN_STAGING_HTTP_PORT" in document
    assert "com.smartscan.environment: staging" in document
