"""验证 SmartScan 共享宿主机 UAT 配置，不连接或修改服务器。"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import yaml

try:
    from tools.validate_uat_loop_storage import (
        LoopStorageError,
        validate_loop_storage_evidence,
    )
except ModuleNotFoundError:  # 直接执行 python tools/validate_uat_config.py
    from validate_uat_loop_storage import (  # type: ignore[no-redef]
        LoopStorageError,
        validate_loop_storage_evidence,
    )

try:
    from tools.validate_staging_config import (
        StagingConfigError,
        _validate_runtime,
        load_env_file,
    )
except ModuleNotFoundError:  # 直接执行 python tools/validate_uat_config.py
    from validate_staging_config import (  # type: ignore[no-redef]
        StagingConfigError,
        _validate_runtime,
        load_env_file,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_FILE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.uat.yml"
DEFAULT_MOUNT_UNIT_FILE = (
    PROJECT_ROOT / "deploy" / "systemd" / "mnt-data-smartscan-uat.mount.template"
)
UAT_ROOT = PurePosixPath("/mnt/data/smartscan/uat")
SECRET_ROOT = PurePosixPath("/etc/smartscan/uat")
ISOLATION_ACK = "uat-only-no-production-data"
IMAGE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDERS = ("replace", "example", "placeholder", "待填写", "待确认")
FORBIDDEN_HOST_PORTS = {80, 443}
GIB = 1024**3

IMAGE_REPOSITORIES = {
    "SMARTSCAN_UAT_API_IMAGE": "ghcr.io/j4meshub/smartscan-api",
    "SMARTSCAN_UAT_WORKER_IMAGE": "ghcr.io/j4meshub/smartscan-worker",
    "SMARTSCAN_UAT_AI_GATEWAY_IMAGE": "ghcr.io/j4meshub/smartscan-ai-gateway",
    "SMARTSCAN_UAT_WEB_IMAGE": "ghcr.io/j4meshub/smartscan-web",
    "SMARTSCAN_UAT_OPS_IMAGE": "ghcr.io/j4meshub/smartscan-ops",
}
BLOCKED_UAT_IMAGE_DIGESTS = {
    "SMARTSCAN_UAT_WEB_IMAGE": {"44a0faf547140844eb065a65034d442b66dd9f971ae5521b8a97400bd50df915"},
    "SMARTSCAN_UAT_OPS_IMAGE": {"ef4dd40c7b8a494e92540dc5bb476ab144903402142a0bbb0fdc4fd688138a5b"},
}
DEPLOY_KEYS = {
    "SMARTSCAN_DEPLOYMENT_TIER",
    "SMARTSCAN_UAT_ISOLATION_ACK",
    "COMPOSE_PROJECT_NAME",
    "SMARTSCAN_UAT_RUNTIME_ENV_FILE",
    "SMARTSCAN_UAT_ALLOCATION_FILE",
    "SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256",
    "SMARTSCAN_UAT_LOOP_EVIDENCE_FILE",
    "SMARTSCAN_UAT_LOOP_EVIDENCE_SHA256",
    "SMARTSCAN_UAT_BIND_ADDRESS",
    "SMARTSCAN_UAT_HTTP_PORT",
    "SMARTSCAN_UAT_DATA_SUBNET",
    "SMARTSCAN_UAT_DATA_GATEWAY",
    "SMARTSCAN_UAT_EDGE_SUBNET",
    "SMARTSCAN_UAT_EDGE_GATEWAY",
    "SMARTSCAN_UAT_EGRESS_SUBNET",
    "SMARTSCAN_UAT_EGRESS_GATEWAY",
    "SMARTSCAN_UAT_POSTGRES_ROOT",
    "SMARTSCAN_UAT_DATA_ROOT",
    "SMARTSCAN_UAT_MODEL_ROOT",
    "SMARTSCAN_UAT_POSTGRES_IMAGE",
    *IMAGE_REPOSITORIES,
    "POSTGRES_PASSWORD",
}
PATH_KEYS = {
    "SMARTSCAN_UAT_POSTGRES_ROOT",
    "SMARTSCAN_UAT_DATA_ROOT",
    "SMARTSCAN_UAT_MODEL_ROOT",
}


class UatConfigError(ValueError):
    """UAT 配置未满足共享宿主机的隔离与失败关闭要求。"""


@dataclass(frozen=True)
class ValidatedUatConfig:
    project_name: str
    bind_address: str
    http_port: int
    storage_roots: tuple[str, ...]
    image_digests: tuple[str, ...]
    allocation_sha256: str
    preflight_evidence_sha256: str
    loop_evidence_sha256: str
    ci_fixture: bool

    def safe_summary(self) -> dict[str, Any]:
        return {
            "deployment_tier": "uat",
            "project_name": self.project_name,
            "http_bind": f"{self.bind_address}:{self.http_port}",
            "storage_roots": list(self.storage_roots),
            "image_digests": list(self.image_digests),
            "allocation_sha256": self.allocation_sha256,
            "preflight_evidence_sha256": self.preflight_evidence_sha256,
            "loop_evidence_sha256": self.loop_evidence_sha256,
            "ci_fixture": self.ci_fixture,
            "secrets_included": False,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UatConfigError(message)


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise UatConfigError(f"无法读取{label}：{path}") from exc
    _require(isinstance(document, dict), f"{label}根节点必须是对象")
    return document, hashlib.sha256(raw).hexdigest()


def _has_placeholder(value: str) -> bool:
    lowered = value.casefold()
    return any(word in lowered for word in PLACEHOLDERS)


def _validate_file_permissions(path: Path, *, ci_fixture: bool) -> None:
    if ci_fixture or os.name == "nt":
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    _require(mode & 0o077 == 0, f"配置文件权限必须为 0600 或更严格：{path}")


def _validate_digest_image(
    value: str, key: str, *, repository: str | None = None, ci_fixture: bool
) -> str:
    _require("@sha256:" in value, f"{key} 必须固定 sha256 digest")
    reference, digest = value.rsplit("@sha256:", 1)
    _require(IMAGE_DIGEST.fullmatch(digest) is not None, f"{key} digest 无效")
    _require(":latest" not in reference.casefold(), f"{key} 禁止使用 latest")
    if repository:
        _require(reference == repository, f"{key} 必须使用批准的 GHCR 仓库 {repository}")
    _require(
        digest not in BLOCKED_UAT_IMAGE_DIGESTS.get(key, set()),
        f"{key} 是已知不兼容 /smartscan/ 或资源确认 1.2 的历史 digest",
    )
    if not ci_fixture:
        _require(len(set(digest)) >= 8, f"{key} 仍是模板 digest")
        _require(not _has_placeholder(reference), f"{key} 仍是模板仓库")
    return digest


def _validate_uat_path(value: str, key: str) -> PurePosixPath:
    path = PurePosixPath(value)
    _require(path.is_absolute() and ".." not in path.parts, f"{key} 必须是安全绝对路径")
    _require(path != UAT_ROOT and UAT_ROOT in path.parents, f"{key} 必须位于 {UAT_ROOT} 下")
    _require(PurePosixPath("/srv") not in path.parents, f"{key} 禁止使用旧 /srv 数据目录")
    return path


def _allocation_port(allocation: dict[str, Any]) -> tuple[str, int]:
    ports = allocation.get("host_ports")
    _require(isinstance(ports, list), "资源确认缺少 host_ports")
    _require(len(ports) == 1, "UAT 只能申请一个宿主机回环端口")
    matches = [
        item
        for item in ports
        if isinstance(item, dict) and "uat web" in str(item.get("purpose", "")).casefold()
    ]
    _require(len(matches) == 1, "资源确认必须且只能包含一个 UAT Web 端口")
    bind_address = str(matches[0].get("bind_address", ""))
    try:
        address = ipaddress.ip_address(bind_address)
        port = int(matches[0].get("port", 0))
    except ValueError as exc:
        raise UatConfigError("UAT Web 监听地址或端口无效") from exc
    _require(str(address) == "127.0.0.1", "UAT Web 必须只绑定 127.0.0.1")
    _require(port == 18082, "UAT Web 必须使用确认的 18082 端口")
    return bind_address, port


def _validate_allocation(
    allocation: dict[str, Any], deploy: dict[str, str], *, ci_fixture: bool
) -> tuple[str, int]:
    _require(allocation.get("schema_version") == "1.2", "资源确认版本无效")
    _require(allocation.get("environment") == "uat", "资源确认必须属于 UAT")
    _require(allocation.get("compose_project_name") == "smartscan-uat", "资源确认项目名无效")
    confirmation = allocation.get("confirmation")
    _require(isinstance(confirmation, dict), "资源确认缺少 confirmation")
    for key in (
        "confirmed_by",
        "confirmed_at",
        "change_record",
        "validation_record",
        "rollback_record",
    ):
        value = str(confirmation.get(key, ""))
        _require(bool(value), f"资源确认缺少 {key}")
        if not ci_fixture:
            _require(not _has_placeholder(value), f"资源确认 {key} 仍是占位值")

    storage = allocation.get("storage")
    _require(isinstance(storage, dict), "资源确认缺少 storage")
    _require(storage.get("root") == str(UAT_ROOT), "资源确认的 UAT 存储根目录无效")
    _require(int(storage.get("quota_bytes", 0)) == 50 * GIB, "UAT 存储配额必须为 50 GiB")
    _require(storage.get("hard_limit_confirmed") is True, "UAT 存储硬限制尚未确认")
    _require(storage.get("disposable_data") is True, "UAT 数据必须明确为可丢弃和重建")
    _require(
        tuple(
            storage.get(key)
            for key in ("warning_percent", "cleanup_percent", "stop_writes_percent")
        )
        == (70, 85, 95),
        "UAT 存储阈值必须为 70/85/95",
    )
    budgets = allocation.get("storage_budgets")
    _require(isinstance(budgets, dict), "资源确认缺少 storage_budgets")
    _require(budgets.get("postgres_and_wal_bytes") == 12 * GIB, "数据库与WAL预算必须为12 GiB")
    _require(budgets.get("ocr_models_bytes") == 4 * GIB, "OCR模型预算必须为4 GiB")
    business_bytes = int(budgets.get("business_data_bytes", 0))
    _require(0 < business_bytes <= 32 * GIB, "业务文件预算必须大于0且不超过32 GiB")
    _require(
        12 * GIB + business_bytes + 4 * GIB <= 48 * GIB,
        "持久化数据预算不得超过48 GiB",
    )
    _require(
        int(budgets.get("filesystem_and_runtime_bytes", 0))
        == 50 * GIB - 12 * GIB - business_bytes - 4 * GIB,
        "文件系统与运行余量必须补足50 GiB且至少为2 GiB",
    )
    _require(
        int(budgets["filesystem_and_runtime_bytes"]) >= 2 * GIB,
        "文件系统与运行余量不得低于2 GiB",
    )

    resources = allocation.get("resources")
    _require(isinstance(resources, dict), "资源确认缺少 resources")
    _require(float(resources.get("cpu_limit", 0)) == 8, "UAT 整栈 CPU 上限必须为 8 vCPU")
    _require(
        int(resources.get("memory_limit_bytes", 0)) == 16 * GIB,
        "UAT 整栈内存上限必须为 16 GiB",
    )

    monitoring = allocation.get("monitoring")
    _require(
        isinstance(monitoring, dict) and monitoring.get("deploy_node_exporter") is False,
        "UAT 禁止部署 Node Exporter",
    )
    _require(monitoring.get("deploy_alertmanager") is False, "UAT 禁止部署 Alertmanager")
    _require(monitoring.get("application_metrics_enabled") is True, "UAT 必须保留应用指标")
    _require(monitoring.get("mode") in {"manual", "existing"}, "UAT 监控模式无效")
    if monitoring.get("mode") == "manual":
        _require(
            monitoring.get("accepted_capability_gap") is True,
            "人工监控模式必须确认能力缺口",
        )
    record_reference = str(monitoring.get("record_reference", ""))
    _require(bool(record_reference), "UAT 监控缺少确认记录")
    if not ci_fixture:
        _require(not _has_placeholder(record_reference), "UAT 监控确认记录仍是占位值")

    ingress = allocation.get("ingress")
    _require(
        isinstance(ingress, dict)
        and ingress.get("mode") == "http_basic_uat"
        and ingress.get("public_access") is False,
        "UAT 入口必须是非公网的 HTTP 基础验收模式",
    )
    _require(ingress.get("shared_nginx_port") == 8077, "共享 Nginx 入口端口必须为 8077")
    _require(ingress.get("base_path") == "/smartscan/", "UAT 基路径必须为 /smartscan/")
    _require(ingress.get("upstream") == "127.0.0.1:18082", "UAT 上游必须为回环 18082")
    _require(
        ingress.get("https_required_after_basic_uat") is True,
        "基础 UAT 后必须保留 HTTPS 门禁",
    )

    backup = allocation.get("backup")
    _require(
        isinstance(backup, dict)
        and backup.get("required") is False
        and backup.get("disposable_uat_data") is True
        and backup.get("single_host_risk_acknowledged") is True,
        "UAT 必须明确无备份、数据可重建及单机风险",
    )

    networks = allocation.get("networks")
    _require(isinstance(networks, dict), "资源确认缺少 networks")
    approved_networks: list[ipaddress._BaseNetwork] = []
    for name in ("data", "edge", "egress"):
        item = networks.get(name)
        _require(isinstance(item, dict), f"资源确认缺少 {name} 网络")
        try:
            network = ipaddress.ip_network(str(item.get("subnet", "")), strict=True)
            gateway = ipaddress.ip_address(str(item.get("gateway", "")))
        except ValueError as exc:
            raise UatConfigError(f"资源确认的 {name} 网络无效") from exc
        _require(gateway in network, f"{name} 网关不在批准网段内")
        _require(
            deploy[f"SMARTSCAN_UAT_{name.upper()}_SUBNET"] == str(network)
            and deploy[f"SMARTSCAN_UAT_{name.upper()}_GATEWAY"] == str(gateway),
            f"部署配置与批准的 {name} 网络不一致",
        )
        approved_networks.append(network)
    for index, network in enumerate(approved_networks):
        _require(
            not any(network.overlaps(other) for other in approved_networks[index + 1 :]),
            "UAT 三个批准网段互相重叠",
        )

    bind_address, port = _allocation_port(allocation)
    _require(deploy["SMARTSCAN_UAT_BIND_ADDRESS"] == bind_address, "监听地址与资源确认不一致")
    _require(int(deploy["SMARTSCAN_UAT_HTTP_PORT"]) == port, "监听端口与资源确认不一致")
    return bind_address, port


def _memory_bytes(value: Any) -> int:
    text = str(value).strip().casefold()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kmgt]?)b?", text)
    _require(match is not None, f"容器内存限制无效：{value}")
    multipliers = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    return int(float(match.group(1)) * multipliers[match.group(2)])


def validate_compose_contract(
    allocation: dict[str, Any], path: Path = DEFAULT_COMPOSE_FILE
) -> None:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise UatConfigError("无法读取 UAT Compose 文件") from exc
    _require(isinstance(document, dict), "UAT Compose 根节点无效")
    services = document.get("services")
    _require(isinstance(services, dict), "UAT Compose 缺少 services")
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
    _require(set(services) == required_services, "UAT Compose 服务集合不完整")
    expected_images = {
        "postgres": "${SMARTSCAN_UAT_POSTGRES_IMAGE:",
        "migrate": "${SMARTSCAN_UAT_OPS_IMAGE:",
        "api": "${SMARTSCAN_UAT_API_IMAGE:",
        "worker-cpu-1": "${SMARTSCAN_UAT_WORKER_IMAGE:",
        "worker-cpu-2": "${SMARTSCAN_UAT_WORKER_IMAGE:",
        "worker-ai": "${SMARTSCAN_UAT_WORKER_IMAGE:",
        "ai-gateway": "${SMARTSCAN_UAT_AI_GATEWAY_IMAGE:",
        "nginx": "${SMARTSCAN_UAT_WEB_IMAGE:",
    }
    cpu_total = 0.0
    memory_total = 0
    base_cpu_total = 0.0
    base_memory_total = 0
    forbidden_mounts = {"/", "/proc", "/sys", "/srv/smartscan/staging"}
    expected_tmpfs = {
        "postgres": {
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "/var/run/postgresql:rw,noexec,nosuid,nodev,size=16m,mode=0777",
        },
        "migrate": {"/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777,uid=10001,gid=10001"},
        "api": {
            "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777,uid=10001,gid=10001",
            "/run/smartscan-prometheus:rw,noexec,nosuid,nodev,size=32m,mode=0770,uid=10001,gid=10001",
        },
        "worker-cpu-1": {"/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=10001,gid=10001"},
        "worker-cpu-2": {"/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=10001,gid=10001"},
        "worker-ai": {"/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777,uid=10001,gid=10001"},
        "ai-gateway": {"/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777,uid=10001,gid=10001"},
        "nginx": {
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "/var/cache/nginx:rw,noexec,nosuid,nodev,size=32m,mode=0755",
            "/var/run:rw,noexec,nosuid,nodev,size=4m,mode=0755",
        },
    }
    for name, service in services.items():
        _require(isinstance(service, dict), f"服务配置无效：{name}")
        _require("build" not in service, f"UAT 禁止在服务器现场构建镜像：{name}")
        _require(
            str(service.get("image", "")).startswith(expected_images[name]), f"{name} 镜像变量无效"
        )
        _require(
            str(service.get("restart", "")).casefold() in {"no", "false"}, f"{name} 禁止自动重启"
        )
        _require(service.get("read_only") is True, f"{name} 根文件系统必须只读")
        _require(set(service.get("tmpfs", [])) == expected_tmpfs[name], f"{name} tmpfs边界无效")
        _require(float(service.get("cpus", 0)) > 0, f"{name} 缺少 CPU 限制")
        _require(_memory_bytes(service.get("mem_limit", 0)) > 0, f"{name} 缺少内存限制")
        _require(int(service.get("pids_limit", 0)) > 0, f"{name} 缺少 PID 限制")
        logging = service.get("logging")
        _require(
            isinstance(logging, dict) and logging.get("driver") == "json-file",
            f"{name} 日志驱动无效",
        )
        options = logging.get("options", {})
        _require(
            options == {"max-size": "10m", "max-file": "3"},
            f"{name} 日志必须精确限制为10m×3",
        )
        cpu_total += float(service["cpus"])
        memory_total += _memory_bytes(service["mem_limit"])
        if not service.get("profiles"):
            base_cpu_total += float(service["cpus"])
            base_memory_total += _memory_bytes(service["mem_limit"])
        image = str(service.get("image", "")).casefold()
        _require(
            "node-exporter" not in name.casefold() and "node-exporter" not in image,
            "UAT 禁止重复 Node Exporter",
        )
        for volume in service.get("volumes", []):
            if not isinstance(volume, dict) or volume.get("type") != "bind":
                continue
            source = str(volume.get("source", ""))
            target = str(volume.get("target", ""))
            _require(
                source not in forbidden_mounts and target not in {"/", "/proc", "/sys"},
                f"{name} 包含禁止的宿主机挂载",
            )
            _require("/srv/smartscan/staging" not in source, f"{name} 仍使用旧 staging 目录")

    resources = allocation["resources"]
    _require(cpu_total <= float(resources["cpu_limit"]), "容器 CPU 限制总和超过资源确认")
    _require(memory_total <= int(resources["memory_limit_bytes"]), "容器内存限制总和超过资源确认")
    _require(base_cpu_total == 5.5, "UAT 基础栈 CPU 限制合计必须为 5.5 vCPU")
    _require(base_memory_total == int(8.75 * GIB), "UAT 基础栈内存限制合计必须为 8.75 GiB")
    _require(cpu_total == 7.5, "UAT 含 AI 栈 CPU 限制合计必须为 7.5 vCPU")
    _require(memory_total == int(11.75 * GIB), "UAT 含 AI 栈内存限制合计必须为 11.75 GiB")
    _require(
        "ports" not in services["postgres"] and "ports" not in services["api"],
        "数据库和 API 禁止暴露主机端口",
    )
    _require(services["nginx"].get("networks") == ["edge"], "Nginx 只能连接入口网络")
    _require(services["postgres"].get("networks") == ["data"], "PostgreSQL 只能连接数据网络")
    _require(services["ai-gateway"].get("profiles") == ["ai"], "AI 网关必须显式启用")
    _require(services["worker-ai"].get("profiles") == ["ai"], "AI Worker 必须显式启用")
    _require("volumes" not in document, "UAT禁止使用PostgreSQL socket named volume")
    postgres_mounts = services["postgres"].get("volumes", [])
    _require(
        len(postgres_mounts) == 1
        and postgres_mounts[0].get("type") == "bind"
        and postgres_mounts[0].get("target") == "/var/lib/postgresql/data"
        and postgres_mounts[0].get("read_only") is not True,
        "PostgreSQL只允许数据目录持久写入loop挂载",
    )

    networks = document.get("networks")
    _require(
        isinstance(networks, dict) and set(networks) == {"data", "edge", "egress"},
        "UAT 网络集合无效",
    )
    for name, network in networks.items():
        _require(network.get("driver") == "bridge", f"{name} 网络必须显式使用 bridge")
        configs = network.get("ipam", {}).get("config", [])
        _require(
            len(configs) == 1 and configs[0].get("subnet") and configs[0].get("gateway"),
            f"{name} 网络禁止自动分配 CIDR",
        )
    _require(networks["data"].get("internal") is True, "数据网络必须 internal")
    _require(networks["edge"].get("internal") is True, "入口网络必须 internal")


def validate_uat_config(
    deploy_env: Path,
    runtime_env: Path,
    allocation_file: Path,
    loop_evidence_file: Path,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    mount_unit_file: Path = DEFAULT_MOUNT_UNIT_FILE,
    ci_fixture: bool = False,
) -> ValidatedUatConfig:
    try:
        deploy = load_env_file(deploy_env)
        runtime = load_env_file(runtime_env)
    except StagingConfigError as exc:
        raise UatConfigError(str(exc)) from exc
    missing = sorted(DEPLOY_KEYS - deploy.keys())
    _require(not missing, f"部署配置缺少变量：{', '.join(missing)}")
    _validate_file_permissions(deploy_env, ci_fixture=ci_fixture)
    _validate_file_permissions(runtime_env, ci_fixture=ci_fixture)
    _validate_file_permissions(allocation_file, ci_fixture=ci_fixture)
    _validate_file_permissions(loop_evidence_file, ci_fixture=ci_fixture)
    _require(deploy["SMARTSCAN_DEPLOYMENT_TIER"] == "uat", "部署层级必须为 uat")
    _require(deploy["SMARTSCAN_UAT_ISOLATION_ACK"] == ISOLATION_ACK, "缺少 UAT 隔离确认")
    _require(deploy["COMPOSE_PROJECT_NAME"] == "smartscan-uat", "Compose 项目必须为 smartscan-uat")

    configured_allocation = PurePosixPath(deploy["SMARTSCAN_UAT_ALLOCATION_FILE"])
    _require(
        configured_allocation.is_absolute() and SECRET_ROOT in configured_allocation.parents,
        "资源确认文件必须位于 /etc/smartscan/uat 下",
    )
    configured_runtime = PurePosixPath(deploy["SMARTSCAN_UAT_RUNTIME_ENV_FILE"])
    _require(
        configured_runtime.is_absolute() and SECRET_ROOT in configured_runtime.parents,
        "运行配置必须位于 /etc/smartscan/uat 下",
    )
    configured_loop_evidence = PurePosixPath(deploy["SMARTSCAN_UAT_LOOP_EVIDENCE_FILE"])
    _require(
        configured_loop_evidence.is_absolute() and SECRET_ROOT in configured_loop_evidence.parents,
        "loop存储证据必须位于 /etc/smartscan/uat 下",
    )

    evidence_hash = deploy["SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256"]
    _require(IMAGE_DIGEST.fullmatch(evidence_hash) is not None, "OPS-000 证据摘要无效")
    if not ci_fixture:
        _require(len(set(evidence_hash)) >= 8, "OPS-000 证据摘要仍是占位值")
    loop_evidence_hash = hashlib.sha256(loop_evidence_file.read_bytes()).hexdigest()
    _require(
        deploy["SMARTSCAN_UAT_LOOP_EVIDENCE_SHA256"] == loop_evidence_hash,
        "loop存储证据摘要与实际文件不一致",
    )

    storage_roots = tuple(str(_validate_uat_path(deploy[key], key)) for key in sorted(PATH_KEYS))
    _require(len(set(storage_roots)) == len(storage_roots), "UAT 存储目录不得复用")
    image_digests = [
        _validate_digest_image(deploy[key], key, repository=repository, ci_fixture=ci_fixture)
        for key, repository in IMAGE_REPOSITORIES.items()
    ]
    image_digests.insert(
        0,
        _validate_digest_image(
            deploy["SMARTSCAN_UAT_POSTGRES_IMAGE"],
            "SMARTSCAN_UAT_POSTGRES_IMAGE",
            ci_fixture=ci_fixture,
        ),
    )

    allocation, allocation_hash = _load_json(allocation_file, "资源确认文件")
    bind_address, port = _validate_allocation(allocation, deploy, ci_fixture=ci_fixture)
    try:
        validate_loop_storage_evidence(
            allocation_file,
            mount_unit_file,
            loop_evidence_file,
            ci_fixture=ci_fixture,
        )
    except LoopStorageError as exc:
        raise UatConfigError(str(exc)) from exc
    try:
        cors_origins = json.loads(runtime["SMARTSCAN_CORS_ORIGINS"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise UatConfigError("UAT CORS 来源必须是 JSON 数组") from exc
    _require(
        isinstance(cors_origins, list) and len(cors_origins) == 1, "UAT 只能配置一个 CORS 来源"
    )
    if not ci_fixture:
        _require(not _has_placeholder(str(cors_origins[0])), "UAT CORS 来源仍是占位值")
    try:
        parsed_origin = urlparse(str(cors_origins[0]))
        origin_port = parsed_origin.port
    except ValueError as exc:
        raise UatConfigError("UAT CORS 来源端口无效") from exc
    _require(
        parsed_origin.scheme == "http"
        and parsed_origin.hostname
        and origin_port == 8077
        and parsed_origin.path in {"", "/"}
        and not parsed_origin.query
        and not parsed_origin.fragment,
        "UAT CORS 来源必须是共享 8077 HTTP 入口",
    )
    try:
        _validate_runtime(
            runtime,
            deploy,
            parsed_origin.hostname,
            ci_fixture=ci_fixture,
            expected_cors_origins=[str(cors_origins[0])],
        )
    except StagingConfigError as exc:
        raise UatConfigError(str(exc).replace("staging", "UAT")) from exc
    _require(
        int(runtime["SMARTSCAN_STORAGE_MIN_FREE_BYTES"]) >= 200 * GIB,
        "UAT 磁盘绝对预留必须至少 200 GiB",
    )
    _require(
        float(runtime["SMARTSCAN_STORAGE_MIN_FREE_PERCENT"]) >= 15, "UAT 磁盘比例预留必须至少 15%"
    )
    for key in (
        "SMARTSCAN_STORAGE_QUOTA_BYTES",
        "SMARTSCAN_STORAGE_WARNING_PERCENT",
        "SMARTSCAN_STORAGE_CLEANUP_PERCENT",
        "SMARTSCAN_STORAGE_STOP_WRITES_PERCENT",
    ):
        _require(key in runtime, f"运行配置缺少变量：{key}")
    _require(
        int(runtime["SMARTSCAN_STORAGE_QUOTA_BYTES"])
        == int(allocation["storage_budgets"]["business_data_bytes"]),
        "运行配置与确认的 UAT 业务文件预算不一致",
    )
    _require(
        int(runtime["SMARTSCAN_USER_STORAGE_QUOTA_BYTES"])
        <= int(allocation["storage_budgets"]["business_data_bytes"]),
        "单用户配额不得超过 UAT 业务文件预算",
    )
    _require(
        tuple(
            float(runtime[key])
            for key in (
                "SMARTSCAN_STORAGE_WARNING_PERCENT",
                "SMARTSCAN_STORAGE_CLEANUP_PERCENT",
                "SMARTSCAN_STORAGE_STOP_WRITES_PERCENT",
            )
        )
        == (70.0, 85.0, 95.0),
        "运行配置的 UAT 存储阈值必须为 70/85/95",
    )
    validate_compose_contract(allocation, compose_file)
    return ValidatedUatConfig(
        project_name="smartscan-uat",
        bind_address=bind_address,
        http_port=port,
        storage_roots=storage_roots,
        image_digests=tuple(image_digests),
        allocation_sha256=allocation_hash,
        preflight_evidence_sha256=evidence_hash,
        loop_evidence_sha256=loop_evidence_hash,
        ci_fixture=ci_fixture,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-env", type=Path, required=True)
    parser.add_argument("--runtime-env", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--loop-evidence", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--mount-unit", type=Path, default=DEFAULT_MOUNT_UNIT_FILE)
    parser.add_argument("--ci-fixture", action="store_true")
    arguments = parser.parse_args()
    try:
        result = validate_uat_config(
            arguments.deploy_env,
            arguments.runtime_env,
            arguments.allocation,
            arguments.loop_evidence,
            compose_file=arguments.compose_file,
            mount_unit_file=arguments.mount_unit,
            ci_fixture=arguments.ci_fixture,
        )
    except UatConfigError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result.safe_summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
