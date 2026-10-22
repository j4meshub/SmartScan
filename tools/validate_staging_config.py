"""验证 SmartScan 隔离 staging 的部署配置，不连接或修改服务器。"""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_FILE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.staging.yml"
DEFAULT_MONITORING_COMPOSE_FILE = (
    PROJECT_ROOT / "deploy" / "compose" / "docker-compose.monitoring.yml"
)
STAGING_ROOT = PurePosixPath("/srv/smartscan/staging")
MONITORING_CONFIG_ROOT = PurePosixPath("/etc/smartscan/staging/monitoring")
ISOLATION_ACK = "staging-only-no-production-data"
SAFE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
SAFE_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
IMAGE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_WORDS = ("replace", "example", "change-me", "development", "placeholder")
IMAGE_KEYS = (
    "SMARTSCAN_STAGING_POSTGRES_IMAGE",
    "SMARTSCAN_STAGING_API_IMAGE",
    "SMARTSCAN_STAGING_WORKER_IMAGE",
    "SMARTSCAN_STAGING_AI_GATEWAY_IMAGE",
    "SMARTSCAN_STAGING_WEB_IMAGE",
    "SMARTSCAN_STAGING_PROMETHEUS_IMAGE",
    "SMARTSCAN_STAGING_ALERTMANAGER_IMAGE",
    "SMARTSCAN_STAGING_NODE_EXPORTER_IMAGE",
    "SMARTSCAN_STAGING_RESTIC_IMAGE",
)
PATH_KEYS = (
    "SMARTSCAN_STAGING_POSTGRES_ROOT",
    "SMARTSCAN_STAGING_DATA_ROOT",
    "SMARTSCAN_STAGING_MODEL_ROOT",
    "SMARTSCAN_STAGING_MONITORING_DATA_ROOT",
    "SMARTSCAN_STAGING_WAL_ROOT",
    "SMARTSCAN_STAGING_BACKUP_WORK_ROOT",
    "SMARTSCAN_STAGING_BACKUP_EVIDENCE_ROOT",
    "SMARTSCAN_STAGING_RESTORE_ROOT",
)
DEPLOY_KEYS = {
    "SMARTSCAN_DEPLOYMENT_TIER",
    "SMARTSCAN_STAGING_ISOLATION_ACK",
    "COMPOSE_PROJECT_NAME",
    "SMARTSCAN_STAGING_HOST",
    "SMARTSCAN_STAGING_HTTP_PORT",
    "SMARTSCAN_STAGING_RUNTIME_ENV_FILE",
    "SMARTSCAN_STAGING_MONITORING_CONFIG_ROOT",
    "SMARTSCAN_STAGING_METRICS_TOKEN_FILE",
    "SMARTSCAN_STAGING_BACKUP_ENV_FILE",
    "SMARTSCAN_STAGING_RESTIC_PASSWORD_FILE",
    "POSTGRES_PASSWORD",
    *IMAGE_KEYS,
    *PATH_KEYS,
}
RUNTIME_KEYS = {
    "SMARTSCAN_ENV",
    "SMARTSCAN_DATABASE_URL",
    "SMARTSCAN_AUTO_MIGRATE",
    "SMARTSCAN_STORAGE_ROOT",
    "SMARTSCAN_INTERNAL_FILE_SEND_PREFIX",
    "SMARTSCAN_SECRET_KEY",
    "SMARTSCAN_PHONE_HMAC_ACTIVE_KEY_ID",
    "SMARTSCAN_PHONE_HMAC_PEPPERS",
    "SMARTSCAN_PHONE_ENCRYPTION_ACTIVE_KEY_ID",
    "SMARTSCAN_PHONE_ENCRYPTION_KEYS",
    "SMARTSCAN_SUPERADMIN_PASSWORD",
    "SMARTSCAN_CORS_ORIGINS",
    "SMARTSCAN_SMS_MODE",
    "SMARTSCAN_WECOM_MODE",
    "SMARTSCAN_OCR_ENABLED",
    "SMARTSCAN_OCR_MODEL_ROOT",
    "SMARTSCAN_AI_PROVIDERS",
    "SMARTSCAN_QUEUE_HIGH_WATER_JOBS",
    "SMARTSCAN_MAX_ACTIVE_JOBS_PER_USER",
    "SMARTSCAN_STORAGE_MIN_FREE_BYTES",
    "SMARTSCAN_STORAGE_MIN_FREE_PERCENT",
    "SMARTSCAN_USER_STORAGE_QUOTA_BYTES",
    "SMARTSCAN_WORKER_HEARTBEAT_INTERVAL_SECONDS",
    "SMARTSCAN_WORKER_STALE_SECONDS",
    "SMARTSCAN_OPS_METRICS_ENABLED",
    "SMARTSCAN_OPS_METRICS_TOKEN",
}


class StagingConfigError(ValueError):
    """staging 配置未满足隔离或安全要求。"""


@dataclass(frozen=True)
class ValidatedStagingConfig:
    project_name: str
    host: str
    http_port: int
    runtime_env_file: Path
    storage_roots: tuple[str, ...]
    image_digests: tuple[str, ...]
    ci_fixture: bool

    def safe_summary(self) -> dict[str, Any]:
        return {
            "deployment_tier": "staging",
            "project_name": self.project_name,
            "host": self.host,
            "http_bind": f"127.0.0.1:{self.http_port}",
            "runtime_env_file": str(self.runtime_env_file),
            "storage_roots": list(self.storage_roots),
            "image_digests": list(self.image_digests),
            "ci_fixture": self.ci_fixture,
            "secrets_included": False,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StagingConfigError(message)


def load_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StagingConfigError(f"无法读取环境文件：{path}") from exc
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        _require("=" in line, f"环境文件第 {line_number} 行缺少等号")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        _require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None, f"环境变量名无效：{key}")
        _require(key not in values, f"环境变量重复：{key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        _require("\x00" not in value and "\n" not in value, f"环境变量值无效：{key}")
        values[key] = value
    return values


def _require_keys(values: dict[str, str], required: set[str], label: str) -> None:
    missing = sorted(key for key in required if key not in values)
    _require(not missing, f"{label}缺少变量：{', '.join(missing)}")


def _is_placeholder(value: str) -> bool:
    lowered = value.casefold()
    return any(word in lowered for word in PLACEHOLDER_WORDS)


def _validate_permissions(path: Path, *, ci_fixture: bool) -> None:
    if ci_fixture or os.name == "nt":
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    _require(mode & 0o077 == 0, f"Secret 环境文件权限必须为 0600 或更严格：{path}")


def _validate_image(value: str, key: str, *, ci_fixture: bool) -> str:
    _require("@sha256:" in value, f"{key} 必须固定 sha256 digest")
    reference, digest = value.rsplit("@sha256:", 1)
    _require(
        bool(reference) and not any(character.isspace() for character in reference),
        f"{key} 镜像引用无效",
    )
    _require(IMAGE_DIGEST.fullmatch(digest) is not None, f"{key} digest 无效")
    _require(":latest" not in reference.casefold(), f"{key} 禁止使用 latest")
    if not ci_fixture:
        _require(len(set(digest)) >= 8, f"{key} 仍是模板 digest")
        _require(not _is_placeholder(reference), f"{key} 仍是模板仓库地址")
    return digest


def _validate_staging_path(value: str, key: str) -> PurePosixPath:
    path = PurePosixPath(value)
    _require(path.is_absolute(), f"{key} 必须是主机绝对路径")
    _require(".." not in path.parts, f"{key} 禁止包含上级路径")
    _require(
        path != STAGING_ROOT and STAGING_ROOT in path.parents, f"{key} 必须位于独立 staging 根目录"
    )
    return path


def _validate_host(host: str, *, ci_fixture: bool) -> str:
    host = host.casefold().rstrip(".")
    _require(SAFE_HOST.fullmatch(host) is not None, "staging 域名格式无效")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise StagingConfigError("staging 必须使用域名，不能使用 IP 字面量")
    _require(
        host.startswith("staging.") or ".staging." in host, "staging 域名必须明确包含 staging 标签"
    )
    if not ci_fixture:
        _require(
            not host.endswith((".invalid", ".example", ".test")), "staging 域名仍是保留占位域名"
        )
    return host


def _strong_secret(value: str, key: str, *, minimum: int = 32, ci_fixture: bool) -> None:
    _require(len(value) >= minimum, f"{key} 长度不足")
    if not ci_fixture:
        _require(not _is_placeholder(value), f"{key} 仍是模板值")


def _json_object(value: str, key: str) -> dict[str, str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StagingConfigError(f"{key} 不是有效 JSON") from exc
    _require(isinstance(decoded, dict) and decoded, f"{key} 必须是非空对象")
    _require(
        all(
            isinstance(item_key, str) and isinstance(item_value, str)
            for item_key, item_value in decoded.items()
        ),
        f"{key} 必须是字符串到字符串的对象",
    )
    return decoded


def _validate_runtime(
    runtime: dict[str, str], deploy: dict[str, str], host: str, *, ci_fixture: bool
) -> None:
    _require_keys(runtime, RUNTIME_KEYS, "运行配置")
    _require(runtime["SMARTSCAN_ENV"] == "production", "staging 必须启用 production 安全校验")
    _require(
        runtime["SMARTSCAN_AUTO_MIGRATE"].casefold() == "false", "staging 禁止应用启动时自动迁移"
    )
    _require(runtime["SMARTSCAN_STORAGE_ROOT"] == "/srv/smartscan/data", "容器数据目录不匹配")
    _require(
        runtime["SMARTSCAN_INTERNAL_FILE_SEND_PREFIX"] == "/_smartscan_files",
        "内部文件发送前缀不匹配",
    )
    _require(runtime["SMARTSCAN_OCR_ENABLED"].casefold() == "true", "staging 必须启用基础 OCR")
    _require(
        runtime["SMARTSCAN_OCR_MODEL_ROOT"] == "/opt/smartscan/models/ocr",
        "OCR 模型目录不匹配",
    )
    _require(runtime["SMARTSCAN_AI_PROVIDERS"].strip() == "[]", "staging 基线必须关闭外部 AI")
    _require(runtime["SMARTSCAN_SMS_MODE"] == "disabled", "OPS-001 基线必须关闭短信供应商")
    _require(runtime["SMARTSCAN_WECOM_MODE"] == "disabled", "OPS-001 基线必须关闭企业微信")
    _require(not runtime.get("SMARTSCAN_DEV_SMS_CODE", ""), "staging 禁止设置开发验证码")
    _require(
        runtime["SMARTSCAN_OPS_METRICS_ENABLED"].casefold() == "true", "staging 必须启用指标端点"
    )
    _strong_secret(
        runtime["SMARTSCAN_OPS_METRICS_TOKEN"],
        "SMARTSCAN_OPS_METRICS_TOKEN",
        ci_fixture=ci_fixture,
    )
    try:
        queue_high_water = int(runtime["SMARTSCAN_QUEUE_HIGH_WATER_JOBS"])
        per_user_jobs = int(runtime["SMARTSCAN_MAX_ACTIVE_JOBS_PER_USER"])
        reserve_bytes = int(runtime["SMARTSCAN_STORAGE_MIN_FREE_BYTES"])
        free_percent = float(runtime["SMARTSCAN_STORAGE_MIN_FREE_PERCENT"])
        user_quota = int(runtime["SMARTSCAN_USER_STORAGE_QUOTA_BYTES"])
        heartbeat_interval = int(runtime["SMARTSCAN_WORKER_HEARTBEAT_INTERVAL_SECONDS"])
        stale_seconds = int(runtime["SMARTSCAN_WORKER_STALE_SECONDS"])
    except ValueError as exc:
        raise StagingConfigError("容量与 Worker 阈值必须是有效数字") from exc
    _require(1 <= queue_high_water <= 100_000, "任务队列高水位无效")
    _require(1 <= per_user_jobs <= 4, "每用户活跃任务限制无效")
    _require(reserve_bytes >= 2 * 25 * 1024**2, "磁盘预留不足以完成上传临时副本")
    _require(1 <= free_percent <= 50, "磁盘最小可用比例无效")
    _require(user_quota >= 25 * 1024**2, "用户存储配额不足以容纳单次最大上传")
    _require(2 <= heartbeat_interval <= 60, "Worker 心跳间隔无效")
    _require(stale_seconds > heartbeat_interval * 2, "Worker 失联阈值必须超过两个心跳间隔")
    try:
        cors_origins = json.loads(runtime["SMARTSCAN_CORS_ORIGINS"])
    except json.JSONDecodeError as exc:
        raise StagingConfigError("CORS 来源必须是 JSON 数组") from exc
    _require(
        cors_origins == [f"https://{host}"],
        "CORS 来源必须是仅包含 staging HTTPS 域名的 JSON 数组",
    )

    parsed = urlparse(runtime["SMARTSCAN_DATABASE_URL"])
    _require(parsed.scheme == "postgresql+psycopg", "数据库 URL 必须使用 postgresql+psycopg")
    _require(
        parsed.hostname == "postgres" and parsed.port == 5432,
        "数据库 URL 必须指向 Compose postgres",
    )
    _require(parsed.username == "smartscan", "数据库用户名必须为 smartscan")
    _require(
        parsed.path == "/smartscan" and not parsed.query and not parsed.fragment,
        "数据库名称或 URL 附加字段无效",
    )
    _require(
        unquote(parsed.password or "") == deploy["POSTGRES_PASSWORD"],
        "运行配置与 PostgreSQL 密码不一致",
    )

    _strong_secret(runtime["SMARTSCAN_SECRET_KEY"], "SMARTSCAN_SECRET_KEY", ci_fixture=ci_fixture)
    _strong_secret(
        runtime["SMARTSCAN_SUPERADMIN_PASSWORD"],
        "SMARTSCAN_SUPERADMIN_PASSWORD",
        minimum=16,
        ci_fixture=ci_fixture,
    )
    hmac_keys = _json_object(
        runtime["SMARTSCAN_PHONE_HMAC_PEPPERS"], "SMARTSCAN_PHONE_HMAC_PEPPERS"
    )
    hmac_active = runtime["SMARTSCAN_PHONE_HMAC_ACTIVE_KEY_ID"]
    _require(hmac_active in hmac_keys, "活动手机号 HMAC Key 不在 Keyring 中")
    for value in hmac_keys.values():
        _strong_secret(value, "手机号 HMAC Pepper", ci_fixture=ci_fixture)

    encryption_keys = _json_object(
        runtime["SMARTSCAN_PHONE_ENCRYPTION_KEYS"], "SMARTSCAN_PHONE_ENCRYPTION_KEYS"
    )
    encryption_active = runtime["SMARTSCAN_PHONE_ENCRYPTION_ACTIVE_KEY_ID"]
    _require(encryption_active in encryption_keys, "活动手机号加密 Key 不在 Keyring 中")
    for encoded in encryption_keys.values():
        try:
            decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise StagingConfigError("手机号加密 Key 必须是 URL-safe Base64") from exc
        _require(len(decoded) == 32, "手机号加密 Key 解码后必须为 32 字节")


def validate_compose_contract(path: Path = DEFAULT_COMPOSE_FILE) -> None:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StagingConfigError("无法读取 staging Compose 文件") from exc
    _require(isinstance(document, dict), "staging Compose 根节点无效")
    services = document.get("services")
    _require(isinstance(services, dict), "staging Compose 缺少 services")
    required_services = {
        "postgres",
        "migrate",
        "api",
        "worker-cpu-1",
        "worker-cpu-2",
        "worker-ai",
        "ai-gateway",
        "nginx",
    }
    _require(set(services) == required_services, "staging Compose 服务集合不完整")
    expected_images = {
        "postgres": "${SMARTSCAN_STAGING_POSTGRES_IMAGE:",
        "migrate": "${SMARTSCAN_STAGING_API_IMAGE:",
        "api": "${SMARTSCAN_STAGING_API_IMAGE:",
        "worker-cpu-1": "${SMARTSCAN_STAGING_WORKER_IMAGE:",
        "worker-cpu-2": "${SMARTSCAN_STAGING_WORKER_IMAGE:",
        "worker-ai": "${SMARTSCAN_STAGING_WORKER_IMAGE:",
        "ai-gateway": "${SMARTSCAN_STAGING_AI_GATEWAY_IMAGE:",
        "nginx": "${SMARTSCAN_STAGING_WEB_IMAGE:",
    }
    for name, service in services.items():
        _require("build" not in service, f"staging 禁止在服务器现场构建镜像：{name}")
        _require(
            str(service.get("image", "")).startswith(expected_images[name]),
            f"{name} 必须通过指定环境变量注入固定镜像",
        )
    _require(
        "ports" not in services["postgres"] and "ports" not in services["api"],
        "数据库和 API 禁止直接暴露主机端口",
    )
    ports = services["nginx"].get("ports", [])
    _require(
        len(ports) == 1 and str(ports[0]).startswith("127.0.0.1:"), "Nginx 只能绑定主机回环地址"
    )
    _require(services["ai-gateway"].get("profiles") == ["ai"], "AI 网关必须保持显式 Profile")
    _require(services["worker-ai"].get("profiles") == ["ai"], "AI Worker 必须保持显式 Profile")
    _require("ports" not in services["worker-ai"], "AI Worker 禁止暴露主机端口")
    _require(
        services["worker-ai"].get("command") == ["python", "-m", "services.worker.app.ai_main"],
        "AI Worker 必须使用独立执行入口",
    )
    _require(services["postgres"].get("networks") == ["data"], "PostgreSQL 只能连接数据网络")
    socket_mounts = [
        volume
        for volume in services["postgres"].get("volumes", [])
        if volume.get("target") == "/var/run/postgresql"
    ]
    _require(
        len(socket_mounts) == 1
        and socket_mounts[0].get("type") == "volume"
        and socket_mounts[0].get("source") == "postgres-socket",
        "PostgreSQL 必须使用受控 Unix Socket 卷供本机备份",
    )
    _require(services["nginx"].get("networks") == ["edge"], "Nginx 只能连接入口网络")
    for worker_name in ("worker-cpu-1", "worker-cpu-2"):
        _require(services[worker_name].get("networks") == ["data"], "CPU Worker 只能连接数据网络")
    _require(services["worker-ai"].get("networks") == ["data"], "AI Worker 只能连接数据网络")
    ai_worker_mounts = services["worker-ai"].get("volumes", [])
    _require(
        len(ai_worker_mounts) == 1
        and ai_worker_mounts[0].get("target") == "/srv/smartscan/data"
        and ai_worker_mounts[0].get("read_only") is True,
        "AI Worker 扫描数据挂载必须只读",
    )
    _require(
        set(services["api"].get("networks", [])) == {"data", "edge", "egress"}, "API 网络边界不完整"
    )
    _require(
        set(services["ai-gateway"].get("networks", [])) == {"data", "egress"},
        "AI 网关网络边界不完整",
    )
    networks = document.get("networks", {})
    _require(networks.get("data", {}).get("internal") is True, "数据网络必须隔离")
    _require(networks.get("edge", {}).get("internal") is True, "入口网络必须隔离")
    _require(
        set(document.get("volumes", {})) == {"postgres-socket"},
        "staging 只能声明受控 PostgreSQL Unix Socket 卷",
    )


def validate_monitoring_compose_contract(
    path: Path = DEFAULT_MONITORING_COMPOSE_FILE,
) -> None:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StagingConfigError("无法读取 monitoring Compose 文件") from exc
    _require(isinstance(document, dict), "monitoring Compose 根节点无效")
    services = document.get("services")
    _require(isinstance(services, dict), "monitoring Compose 缺少 services")
    expected_images = {
        "prometheus": "${SMARTSCAN_STAGING_PROMETHEUS_IMAGE:",
        "alertmanager": "${SMARTSCAN_STAGING_ALERTMANAGER_IMAGE:",
        "node-exporter": "${SMARTSCAN_STAGING_NODE_EXPORTER_IMAGE:",
    }
    _require(set(services) == set(expected_images), "monitoring Compose 服务集合不完整")
    for name, image_prefix in expected_images.items():
        service = services[name]
        _require(
            "build" not in service and "ports" not in service,
            f"监控服务禁止现场构建或暴露端口：{name}",
        )
        _require(str(service.get("image", "")).startswith(image_prefix), f"{name} 必须固定镜像")
        _require(service.get("profiles") == ["monitoring"], f"{name} 必须使用 monitoring Profile")
        _require(service.get("networks") == ["data"], f"{name} 只能连接数据网络")
        _require(service.get("read_only") is True, f"{name} 根文件系统必须只读")
        _require(service.get("cap_drop") == ["ALL"], f"{name} 必须删除全部 capabilities")
        _require(
            service.get("security_opt") == ["no-new-privileges:true"],
            f"{name} 必须禁止提权",
        )
    for volume in services["node-exporter"].get("volumes", []):
        _require(volume.get("read_only") is True, "Node Exporter 主机挂载必须只读")


def _resolve_runtime_path(deploy: dict[str, str], *, ci_fixture: bool) -> Path:
    configured = Path(deploy["SMARTSCAN_STAGING_RUNTIME_ENV_FILE"])
    if configured.is_absolute():
        return configured
    _require(ci_fixture, "真实 staging 运行配置文件必须使用绝对路径")
    return (DEFAULT_COMPOSE_FILE.parent / configured).resolve()


def validate_staging_config(
    deploy_env_path: Path,
    *,
    runtime_env_path: Path | None = None,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    monitoring_compose_file: Path = DEFAULT_MONITORING_COMPOSE_FILE,
    ci_fixture: bool = False,
    require_host_paths: bool = False,
) -> ValidatedStagingConfig:
    deploy_env_path = deploy_env_path.resolve()
    if not ci_fixture:
        try:
            deploy_env_path.relative_to(PROJECT_ROOT)
        except ValueError:
            pass
        else:
            raise StagingConfigError("真实 staging 部署配置必须位于仓库外")
    deploy = load_env_file(deploy_env_path)
    _require_keys(deploy, DEPLOY_KEYS, "部署配置")
    _validate_permissions(deploy_env_path, ci_fixture=ci_fixture)
    _require(deploy["SMARTSCAN_DEPLOYMENT_TIER"] == "staging", "部署层级必须明确为 staging")
    _require(
        deploy["SMARTSCAN_STAGING_ISOLATION_ACK"] == ISOLATION_ACK,
        "缺少 staging 隔离确认",
    )
    project_name = deploy["COMPOSE_PROJECT_NAME"]
    _require(SAFE_PROJECT.fullmatch(project_name) is not None, "Compose 项目名无效")
    _require(
        project_name.endswith("-staging") and project_name != "smartscan",
        "Compose 项目名必须明确隔离 staging",
    )
    host = _validate_host(deploy["SMARTSCAN_STAGING_HOST"], ci_fixture=ci_fixture)
    try:
        http_port = int(deploy["SMARTSCAN_STAGING_HTTP_PORT"])
    except ValueError as exc:
        raise StagingConfigError("staging HTTP 端口必须是整数") from exc
    _require(
        1024 <= http_port <= 65535 and http_port not in {80, 443},
        "staging 端口必须是非特权独立端口",
    )

    password = deploy["POSTGRES_PASSWORD"]
    _strong_secret(password, "POSTGRES_PASSWORD", minimum=20, ci_fixture=ci_fixture)
    _require(
        re.fullmatch(r"[A-Za-z0-9._~-]{20,128}", password) is not None,
        "POSTGRES_PASSWORD 只能使用 URL 与 Compose 安全字符",
    )
    digests = tuple(_validate_image(deploy[key], key, ci_fixture=ci_fixture) for key in IMAGE_KEYS)
    roots = tuple(str(_validate_staging_path(deploy[key], key)) for key in PATH_KEYS)
    _require(
        PurePosixPath(deploy["SMARTSCAN_STAGING_MONITORING_CONFIG_ROOT"]) == MONITORING_CONFIG_ROOT,
        "监控配置目录必须使用固定 staging 路径",
    )
    _require(
        PurePosixPath(deploy["SMARTSCAN_STAGING_METRICS_TOKEN_FILE"])
        == MONITORING_CONFIG_ROOT / "ops-metrics.token",
        "指标令牌文件路径不匹配",
    )
    root_paths = [PurePosixPath(root) for root in roots]
    for index, left in enumerate(root_paths):
        for right in root_paths[index + 1 :]:
            _require(
                left != right and left not in right.parents and right not in left.parents,
                "PostgreSQL、数据和模型目录不得重叠或嵌套",
            )

    configured_runtime = _resolve_runtime_path(deploy, ci_fixture=ci_fixture)
    runtime_path = runtime_env_path.resolve() if runtime_env_path else configured_runtime
    if not ci_fixture:
        _require(runtime_path == configured_runtime, "运行配置路径与部署配置不一致")
        try:
            runtime_path.relative_to(PROJECT_ROOT)
        except ValueError:
            pass
        else:
            raise StagingConfigError("真实 staging 运行 Secret 必须位于仓库外")
    runtime = load_env_file(runtime_path)
    _validate_permissions(runtime_path, ci_fixture=ci_fixture)
    _validate_runtime(runtime, deploy, host, ci_fixture=ci_fixture)
    validate_compose_contract(compose_file.resolve())
    validate_monitoring_compose_contract(monitoring_compose_file.resolve())

    if require_host_paths:
        _require(os.name != "nt", "主机目录检查必须在目标 Linux staging 主机执行")
        staging_root = Path(str(STAGING_ROOT))
        _require(
            staging_root.is_dir() and not staging_root.is_symlink(),
            "staging 根目录不存在或是符号链接",
        )
        resolved_root = staging_root.resolve(strict=True)
        for root in roots:
            candidate = Path(root)
            _require(
                candidate.is_dir() and not candidate.is_symlink(),
                f"staging 目录不存在或是符号链接：{root}",
            )
            try:
                candidate.resolve(strict=True).relative_to(resolved_root)
            except ValueError as exc:
                raise StagingConfigError(f"staging 目录解析后越出隔离根：{root}") from exc

    return ValidatedStagingConfig(
        project_name=project_name,
        host=host,
        http_port=http_port,
        runtime_env_file=runtime_path,
        storage_roots=roots,
        image_digests=digests,
        ci_fixture=ci_fixture,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 SmartScan 隔离 staging 配置")
    parser.add_argument("--deploy-env", required=True, type=Path, help="部署插值环境文件")
    parser.add_argument(
        "--runtime-env", type=Path, help="运行 Secret 文件；真实环境必须与部署配置一致"
    )
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument(
        "--ci-fixture", action="store_true", help="仅允许仓库合成夹具中的保留域名和示例 digest"
    )
    parser.add_argument(
        "--require-host-paths", action="store_true", help="在目标 Linux 主机验证真实目录与符号链接"
    )
    args = parser.parse_args()
    config = validate_staging_config(
        args.deploy_env,
        runtime_env_path=args.runtime_env,
        compose_file=args.compose_file,
        ci_fixture=args.ci_fixture,
        require_host_paths=args.require_host_paths,
    )
    print("staging 配置校验通过；以下摘要不包含 Secret：")
    print(json.dumps(config.safe_summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
