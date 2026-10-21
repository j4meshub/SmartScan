"""校验 SmartScan staging 备份、恢复和异机仓库配置。"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import yaml

if __package__:
    from tools.validate_staging_config import PROJECT_ROOT, load_env_file
else:
    from validate_staging_config import PROJECT_ROOT, load_env_file

STAGING_ROOT = PurePosixPath("/srv/smartscan/staging")
BACKUP_ENV_PATH = PurePosixPath("/etc/smartscan/staging/backup.env")
PASSWORD_PATH = PurePosixPath("/etc/smartscan/staging/restic-password")
RESTIC_PASSWORD_PATH = PurePosixPath("/run/secrets/restic_password")
DEFAULT_COMPOSE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.backup.yml"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
DIGEST_IMAGE = re.compile(r"^[^\s@]+@sha256:[a-f0-9]{64}$")
PLACEHOLDER_DIGEST = "0" * 64

PATH_FIELDS = {
    "SMARTSCAN_STAGING_WAL_ROOT": STAGING_ROOT / "wal",
    "SMARTSCAN_STAGING_BACKUP_WORK_ROOT": STAGING_ROOT / "backup-work",
    "SMARTSCAN_STAGING_BACKUP_EVIDENCE_ROOT": STAGING_ROOT / "backup-evidence",
    "SMARTSCAN_STAGING_RESTORE_ROOT": STAGING_ROOT / "restore-drills",
}
BACKUP_FIELDS = {
    "SMARTSCAN_BACKUP_ENVIRONMENT",
    "SMARTSCAN_BACKUP_OFF_HOST_ACK",
    "SMARTSCAN_BACKUP_REPOSITORY_ID",
    "RESTIC_REPOSITORY",
    "RESTIC_PASSWORD_FILE",
    "SMARTSCAN_BACKUP_RETENTION_DAILY",
    "SMARTSCAN_BACKUP_RETENTION_WEEKLY",
    "SMARTSCAN_BACKUP_RPO_HOURS",
    "SMARTSCAN_BACKUP_RTO_HOURS",
}


class BackupConfigError(ValueError):
    """备份配置不满足失败关闭或异机边界。"""


@dataclass(frozen=True)
class ValidatedBackupConfig:
    repository_scheme: str
    repository_host: str
    repository_id: str
    retention_daily: int
    retention_weekly: int
    rpo_hours: int
    rto_hours: int
    paths: tuple[str, ...]

    def safe_summary(self) -> dict[str, object]:
        return {
            "repository_scheme": self.repository_scheme,
            "repository_host": self.repository_host,
            "repository_id": self.repository_id,
            "retention_daily": self.retention_daily,
            "retention_weekly": self.retention_weekly,
            "rpo_hours": self.rpo_hours,
            "rto_hours": self.rto_hours,
            "paths": list(self.paths),
            "secrets_included": False,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackupConfigError(message)


def _private_file(path: Path, *, ci_fixture: bool, label: str) -> None:
    _require(path.is_file() and not path.is_symlink(), f"{label}必须是普通文件且不能是符号链接")
    if not ci_fixture and os.name != "nt":
        _require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, f"{label}权限必须为 0600 或更严格")


def _validate_secret(path: Path, *, ci_fixture: bool) -> None:
    _private_file(path, ci_fixture=ci_fixture, label="Restic 密码文件")
    secret = path.read_text(encoding="utf-8").strip()
    _require(len(secret) >= 32, "Restic 密码必须至少 32 个字符")
    _require(not any(character.isspace() for character in secret), "Restic 密码禁止空白字符")
    if not ci_fixture:
        _require(
            not any(
                word in secret.casefold()
                for word in ("replace", "example", "change-me", "placeholder")
            ),
            "Restic 密码仍是模板值",
        )


def _repository_endpoint(value: str) -> tuple[str, str]:
    if value.startswith("s3:"):
        scheme = "s3"
        parsed = urlparse(value[3:])
    elif value.startswith("rest:"):
        scheme = "rest"
        parsed = urlparse(value[5:])
    elif value.startswith("sftp:"):
        scheme = "sftp"
        match = re.fullmatch(r"sftp:(?:[A-Za-z0-9._-]+@)?([^/:\s]+):(/[^\s]+)", value)
        _require(match is not None, "SFTP Restic 仓库格式无效")
        return scheme, match.group(1).casefold()
    else:
        raise BackupConfigError("只允许 s3、rest 或 sftp 异机 Restic 仓库")

    _require(parsed.scheme == "https", "Restic HTTP 仓库必须使用 HTTPS")
    _require(bool(parsed.hostname), "Restic 仓库缺少主机名")
    _require(parsed.username is None and parsed.password is None, "Restic 仓库 URL 禁止凭据")
    _require(parsed.port in (None, 443), "Restic 仓库只允许标准 HTTPS 端口")
    _require(not parsed.query and not parsed.fragment, "Restic 仓库禁止查询或片段")
    return scheme, parsed.hostname.casefold()


def _validate_compose(path: Path = DEFAULT_COMPOSE) -> None:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BackupConfigError("无法读取备份 Compose 文件") from exc
    services = document.get("services") if isinstance(document, dict) else None
    _require(isinstance(services, dict), "备份 Compose 缺少 services")
    expected = {
        "backup-database": ["backup"],
        "backup-restic": ["backup", "restore"],
        "restore-database": ["restore"],
        "restore-audit": ["restore"],
    }
    _require(set(services) == set(expected), "备份 Compose 服务集合不完整")
    for name, profiles in expected.items():
        service = services[name]
        _require(
            "build" not in service and "ports" not in service, f"备份服务禁止构建或开放端口：{name}"
        )
        _require(service.get("profiles") == profiles, f"备份服务 Profile 无效：{name}")
        _require(service.get("read_only") is True, f"备份服务根文件系统必须只读：{name}")
        _require(service.get("cap_drop") == ["ALL"], f"备份服务必须删除 capabilities：{name}")
        _require(
            service.get("security_opt") == ["no-new-privileges:true"],
            f"备份服务必须禁止提权：{name}",
        )
    for volume in services["backup-restic"].get("volumes", []):
        target = volume.get("target", "")
        if target.startswith(("/source/", "/run/secrets/")):
            _require(volume.get("read_only") is True, f"备份源挂载必须只读：{target}")
    _require(
        document.get("networks", {}).get("restore", {}).get("internal") is True, "恢复网络必须隔离"
    )


def validate_backup_config(
    deploy_env_path: Path,
    backup_env_path: Path | None = None,
    password_path: Path | None = None,
    *,
    ci_fixture: bool = False,
    require_host_paths: bool = False,
    compose_file: Path = DEFAULT_COMPOSE,
) -> ValidatedBackupConfig:
    deploy_path = deploy_env_path.resolve()
    if not ci_fixture:
        try:
            deploy_path.relative_to(PROJECT_ROOT)
        except ValueError:
            pass
        else:
            raise BackupConfigError("真实部署配置必须位于仓库外")
    deploy = load_env_file(deploy_path)
    configured_backup_env = PurePosixPath(deploy.get("SMARTSCAN_STAGING_BACKUP_ENV_FILE", ""))
    configured_password = PurePosixPath(deploy.get("SMARTSCAN_STAGING_RESTIC_PASSWORD_FILE", ""))
    _require(configured_backup_env == BACKUP_ENV_PATH, "备份环境文件必须使用固定 staging 路径")
    _require(configured_password == PASSWORD_PATH, "Restic 密码文件必须使用固定 staging 路径")

    if backup_env_path is None:
        backup_env_path = Path(str(configured_backup_env))
    if password_path is None:
        password_path = Path(str(configured_password))
    backup_env_path = backup_env_path.resolve()
    password_path = password_path.resolve()
    if not ci_fixture:
        for path, label in (
            (backup_env_path, "备份环境文件"),
            (password_path, "Restic 密码文件"),
        ):
            try:
                path.relative_to(PROJECT_ROOT)
            except ValueError:
                pass
            else:
                raise BackupConfigError(f"真实{label}必须位于仓库外")
    _private_file(backup_env_path, ci_fixture=ci_fixture, label="备份环境文件")
    _validate_secret(password_path, ci_fixture=ci_fixture)
    backup = load_env_file(backup_env_path)
    missing = sorted(BACKUP_FIELDS - backup.keys())
    _require(not missing, f"备份环境缺少字段：{', '.join(missing)}")
    _require(backup["SMARTSCAN_BACKUP_ENVIRONMENT"] == "staging", "备份环境必须是 staging")
    _require(
        backup["SMARTSCAN_BACKUP_OFF_HOST_ACK"] == "encrypted-off-host-repository",
        "缺少加密异机仓库确认",
    )
    repository_id = backup["SMARTSCAN_BACKUP_REPOSITORY_ID"]
    _require(SAFE_ID.fullmatch(repository_id) is not None, "备份仓库 ID 无效")
    _require(
        PurePosixPath(backup["RESTIC_PASSWORD_FILE"]) == RESTIC_PASSWORD_PATH,
        "容器内 Restic 密码路径无效",
    )
    scheme, host = _repository_endpoint(backup["RESTIC_REPOSITORY"])
    staging_host = deploy.get("SMARTSCAN_STAGING_HOST", "").casefold()
    _require(
        host not in {"localhost", "127.0.0.1", "::1", staging_host},
        "备份仓库必须与 staging 主机分离",
    )
    if not ci_fixture:
        _require(not host.endswith((".example", ".invalid", ".test")), "备份仓库仍是保留占位域名")
        for key, value in backup.items():
            if key not in BACKUP_FIELDS and any(
                marker in key for marker in ("KEY", "SECRET", "TOKEN")
            ):
                _require(
                    bool(value)
                    and not any(
                        word in value.casefold()
                        for word in ("replace", "example", "change-me", "placeholder")
                    ),
                    f"{key} 仍是模板凭据",
                )

    try:
        daily = int(backup["SMARTSCAN_BACKUP_RETENTION_DAILY"])
        weekly = int(backup["SMARTSCAN_BACKUP_RETENTION_WEEKLY"])
        rpo = int(backup["SMARTSCAN_BACKUP_RPO_HOURS"])
        rto = int(backup["SMARTSCAN_BACKUP_RTO_HOURS"])
    except ValueError as exc:
        raise BackupConfigError("备份保留与 RPO/RTO 必须是整数") from exc
    _require(daily >= 7, "日备份保留不得少于 7 个")
    _require(weekly >= 4, "周备份保留不得少于 4 个")
    _require(1 <= rpo <= 24, "RPO 目标不得超过 24 小时")
    _require(1 <= rto <= 8, "RTO 目标不得超过 8 小时")

    paths: list[str] = []
    for key, expected in PATH_FIELDS.items():
        value = PurePosixPath(deploy.get(key, ""))
        _require(value == expected, f"{key} 必须使用固定 staging 路径")
        paths.append(str(value))
    source_paths = {
        PurePosixPath(deploy.get("SMARTSCAN_STAGING_POSTGRES_ROOT", "")),
        PurePosixPath(deploy.get("SMARTSCAN_STAGING_DATA_ROOT", "")),
        *[PurePosixPath(item) for item in paths],
    }
    _require(len(source_paths) == 6, "数据库、业务数据、WAL、备份工作、证据和恢复目录必须互不重叠")

    restic_image = deploy.get("SMARTSCAN_STAGING_RESTIC_IMAGE", "")
    _require(DIGEST_IMAGE.fullmatch(restic_image) is not None, "Restic 镜像必须固定 sha256 digest")
    digest = restic_image.rsplit("@sha256:", 1)[1]
    _require(
        not restic_image.endswith(PLACEHOLDER_DIGEST) and (ci_fixture or len(set(digest)) >= 8),
        "Restic 镜像仍是占位 digest",
    )
    _validate_compose(compose_file.resolve())

    if require_host_paths:
        _require(os.name != "nt", "主机目录检查必须在目标 Linux staging 主机执行")
        for raw in paths:
            candidate = Path(raw)
            _require(candidate.is_dir() and not candidate.is_symlink(), f"主机目录不可用：{raw}")
            resolved = candidate.resolve(strict=True)
            _require(
                PurePosixPath(resolved.as_posix()).is_relative_to(STAGING_ROOT),
                f"主机目录解析后越界：{raw}",
            )

    return ValidatedBackupConfig(
        repository_scheme=scheme,
        repository_host=host,
        repository_id=repository_id,
        retention_daily=daily,
        retention_weekly=weekly,
        rpo_hours=rpo,
        rto_hours=rto,
        paths=tuple(paths),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 SmartScan staging 备份与恢复配置")
    parser.add_argument("--deploy-env", required=True, type=Path)
    parser.add_argument("--backup-env", type=Path)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--ci-fixture", action="store_true")
    parser.add_argument("--require-host-paths", action="store_true")
    args = parser.parse_args()
    result = validate_backup_config(
        args.deploy_env,
        args.backup_env,
        args.password_file,
        ci_fixture=args.ci_fixture,
        require_host_paths=args.require_host_paths,
        compose_file=args.compose_file,
    )
    print(json.dumps(result.safe_summary(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
