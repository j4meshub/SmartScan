#!/usr/bin/env python3
"""SmartScan UAT 仓库外配置生成与失败关闭校验器。

该文件由受限 sudo 执行器按固定路径调用。命令行不接受路径或配置值，
所有内部参数来自 root 预先审核的固定输入文件，所有 Secret 在目标主机本地生成。
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

try:
    import pwd
except ModuleNotFoundError:  # Windows只运行纯函数测试；目标服务器必须是Linux
    pwd = None  # type: ignore[assignment]


EXPECTED_HOSTNAME = "ctiecaiserver"
DEPLOY_USER = "szhzx"
GIB = 1024**3

ACCEPTED_IMAGES = {
    "SMARTSCAN_UAT_POSTGRES_IMAGE": "ghcr.io/j4meshub/smartscan-postgres@sha256:94758173bbe1975014751a2e2855a22e0e554e8df996e4d6303bcf386cdae6d0",
    "SMARTSCAN_UAT_API_IMAGE": "ghcr.io/j4meshub/smartscan-api@sha256:80aea0a272791ea44d76895dbd825d091620e0f43ad76c32f32fb6ba97c646d0",
    "SMARTSCAN_UAT_WORKER_IMAGE": "ghcr.io/j4meshub/smartscan-worker@sha256:f1cb15e434e99fdced69885667e8646346c75bc293e8ecf9f6b0fa24951768a6",
    "SMARTSCAN_UAT_AI_GATEWAY_IMAGE": "ghcr.io/j4meshub/smartscan-ai-gateway@sha256:1813ada8bda225530d71e5afa9e1c3fd640d5e23d05000d370fdccad0e5e8b00",
    "SMARTSCAN_UAT_WEB_IMAGE": "ghcr.io/j4meshub/smartscan-web@sha256:3d701a4bcaf24c03ead231f10abd316ba83ab89a6984894dfe31af404d3c930c",
    "SMARTSCAN_UAT_OPS_IMAGE": "ghcr.io/j4meshub/smartscan-ops@sha256:be6c50fbdbc9404a9d9589a53799dbc6084470a63f2306ec6bee5736adf94cae",
}

REJECTED_POSTGRES_DIGESTS = (
    "e54319a0ae69c22731599fb942500e942e5ba03d34c32406a3d747bffcefd04b",
    "bdda",
    "7064",
)

SECRET_FIELDS = (
    "POSTGRES_PASSWORD",
    "SMARTSCAN_DATABASE_URL",
    "SMARTSCAN_SECRET_KEY",
    "SMARTSCAN_PHONE_HMAC_PEPPERS",
    "SMARTSCAN_PHONE_ENCRYPTION_KEYS",
    "SMARTSCAN_SUPERADMIN_PASSWORD",
    "SMARTSCAN_OPS_METRICS_TOKEN",
)


class ConfigError(RuntimeError):
    """固定 UAT 配置未满足失败关闭要求。"""


@dataclass(frozen=True)
class Paths:
    config_root: Path = Path("/etc/smartscan/uat")
    input_file: Path = Path("/etc/smartscan/uat/deployment-input.json")
    deploy_env: Path = Path("/etc/smartscan/uat/deploy.env")
    runtime_env: Path = Path("/etc/smartscan/uat/runtime.env")
    allocation: Path = Path("/etc/smartscan/uat/shared-host-allocation.json")
    preflight: Path = Path("/etc/smartscan/uat/preflight-summary.json")
    loop_evidence: Path = Path("/etc/smartscan/uat/loop-storage-evidence.json")
    bootstrap_password: Path = Path("/etc/smartscan/uat/bootstrap-admin-password")
    image_identities: Path = Path("/etc/smartscan/uat/image-identities.json")
    postgres_root: Path = Path("/mnt/data/smartscan/uat/postgres")
    data_root: Path = Path("/mnt/data/smartscan/uat/data")
    model_root: Path = Path("/mnt/data/smartscan/uat/models/ocr")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _load_json(path: Path, *, owner_uid: int | None = None) -> tuple[dict[str, Any], bytes]:
    _require(path.exists() and path.is_file() and not path.is_symlink(), f"固定文件无效：{path}")
    info = path.stat()
    if os.name != "nt":
        _require(stat.S_IMODE(info.st_mode) == 0o600, f"固定文件权限必须为0600：{path}")
    if owner_uid is not None and os.name != "nt":
        _require(info.st_uid == owner_uid, f"固定文件所有者无效：{path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"固定JSON无效：{path}") from exc
    _require(isinstance(value, dict), f"固定JSON根节点必须是对象：{path}")
    return value, raw


def _safe_text(value: Any, label: str) -> str:
    text = str(value).strip()
    _require(bool(text), f"缺少字段：{label}")
    _require("\x00" not in text and "\n" not in text and "\r" not in text, f"字段无效：{label}")
    _require(
        not any(word in text.casefold() for word in ("replace", "placeholder", "待填写", "待确认")),
        f"字段仍是占位值：{label}",
    )
    return text


def _validate_input(document: dict[str, Any]) -> dict[str, Any]:
    _require(document.get("schema_version") == "1.0", "部署输入schema_version无效")
    _require(document.get("target_hostname") == EXPECTED_HOSTNAME, "部署输入主机名无效")
    origin = _safe_text(document.get("shared_entry_origin"), "shared_entry_origin")
    parsed = urlparse(origin)
    _require(
        parsed.scheme == "http"
        and parsed.hostname
        and parsed.port == 8077
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment,
        "共享入口必须是固定8077 HTTP origin",
    )

    confirmation = document.get("confirmation")
    _require(isinstance(confirmation, dict), "部署输入缺少confirmation")
    for key in (
        "confirmed_by",
        "confirmed_at",
        "change_record",
        "validation_record",
        "rollback_record",
    ):
        _safe_text(confirmation.get(key), f"confirmation.{key}")

    networks = document.get("networks")
    _require(
        isinstance(networks, dict) and set(networks) == {"data", "edge", "egress"}, "网络输入不完整"
    )
    parsed_networks: list[ipaddress._BaseNetwork] = []
    for name in ("data", "edge", "egress"):
        item = networks[name]
        _require(isinstance(item, dict), f"{name}网络输入无效")
        try:
            subnet = ipaddress.ip_network(str(item.get("subnet", "")), strict=True)
            gateway = ipaddress.ip_address(str(item.get("gateway", "")))
        except ValueError as exc:
            raise ConfigError(f"{name}网络或网关无效") from exc
        _require(gateway in subnet, f"{name}网关不在网段内")
        parsed_networks.append(subnet)
    for index, network in enumerate(parsed_networks):
        _require(
            not any(network.overlaps(other) for other in parsed_networks[index + 1 :]),
            "三张候选网络相互重叠",
        )

    reserved = document.get("reserved_cidrs")
    _require(isinstance(reserved, list) and reserved, "部署输入缺少脱敏保留网段记录")
    for value in reserved:
        try:
            candidate = ipaddress.ip_network(str(value), strict=True)
        except ValueError as exc:
            raise ConfigError("保留网段格式无效") from exc
        _require(
            not any(candidate.overlaps(item) for item in parsed_networks), "候选网络与保留网段重叠"
        )

    monitoring_record = _safe_text(document.get("monitoring_record"), "monitoring_record")
    return {
        "origin": origin,
        "confirmation": confirmation,
        "networks": networks,
        "reserved_cidrs": reserved,
        "monitoring_record": monitoring_record,
    }


def _validate_evidence(paths: Paths, *, root_uid: int) -> tuple[str, str]:
    preflight, preflight_raw = _load_json(paths.preflight, owner_uid=root_uid)
    _require(preflight.get("status") == "passed", "部署前只读预检状态不是passed")
    _require(preflight.get("contains_sensitive_data") is False, "预检摘要必须是脱敏证据")
    _safe_text(preflight.get("captured_at"), "preflight.captured_at")

    loop, loop_raw = _load_json(paths.loop_evidence, owner_uid=root_uid)
    _require(loop.get("contains_sensitive_data") is False, "loop证据必须是脱敏证据")
    backing = loop.get("backing_file", {})
    filesystem = loop.get("filesystem", {})
    mount = loop.get("mount", {})
    loop_state = loop.get("loop", {})
    unit = loop.get("systemd_unit", {})
    _require(backing.get("size_bytes") == 50 * GIB, "loop后备文件不是50 GiB")
    _require(
        backing.get("allocated_bytes", 0) >= 50 * GIB and backing.get("sparse") is False,
        "loop后备文件未完整预分配",
    )
    _require(
        filesystem.get("type") == "ext4" and filesystem.get("label") == "smartscan-uat",
        "loop文件系统身份无效",
    )
    _require(filesystem.get("reserved_blocks_percent") == 0, "loop reserved block无效")
    _require(filesystem.get("usable_bytes", 0) >= 48 * GIB, "loop可用空间不足48 GiB")
    _require(
        mount.get("active") is True and mount.get("target") == "/mnt/data/smartscan/uat",
        "loop挂载未激活",
    )
    _require(
        {"loop", "nodev", "nosuid", "noatime"}.issubset(set(mount.get("options", []))),
        "loop挂载参数不完整",
    )
    _require(loop_state.get("autoclear") is True, "loop未启用autoclear")
    _require(unit.get("enabled") is True and unit.get("active") is True, "loop systemd单元未启用")
    return hashlib.sha256(preflight_raw).hexdigest(), hashlib.sha256(loop_raw).hexdigest()


def _allocation(validated: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.2",
        "environment": "uat",
        "compose_project_name": "smartscan-uat",
        "target_hostname": EXPECTED_HOSTNAME,
        "confirmation": validated["confirmation"],
        "networks": validated["networks"],
        "reserved_cidrs": validated["reserved_cidrs"],
        "host_ports": [{"purpose": "UAT Web 回环入口", "port": 18082, "bind_address": "127.0.0.1"}],
        "storage": {
            "root": "/mnt/data/smartscan/uat",
            "quota_bytes": 50 * GIB,
            "hard_limit_type": "loop_ext4",
            "hard_limit_confirmed": True,
            "warning_percent": 70,
            "cleanup_percent": 85,
            "stop_writes_percent": 95,
            "disposable_data": True,
        },
        "storage_budgets": {
            "postgres_and_wal_bytes": 12 * GIB,
            "business_data_bytes": 32 * GIB,
            "ocr_models_bytes": 4 * GIB,
            "filesystem_and_runtime_bytes": 2 * GIB,
        },
        "loop_storage": {
            "backing_file": "/mnt/data/smartscan-loop/uat.ext4",
            "backing_file_bytes": 50 * GIB,
            "fully_preallocated": True,
            "sparse_file_forbidden": True,
            "filesystem_type": "ext4",
            "reserved_blocks_percent": 0,
            "mount_point": "/mnt/data/smartscan/uat",
            "mount_options": ["loop", "nodev", "nosuid", "noatime"],
            "autoclear_required": True,
            "systemd_unit_name": "mnt-data-smartscan-uat.mount",
            "systemd_unit_path": "/etc/systemd/system/mnt-data-smartscan-uat.mount",
            "requires_mounts_for": "/mnt/data",
            "rollback_documented": True,
        },
        "docker_logging": {
            "storage_scope": "shared_docker_root_outside_uat_loop",
            "driver": "json-file",
            "max_size": "10m",
            "max_file": 3,
            "max_container_count": 8,
            "maximum_bytes": 240 * 1024**2,
        },
        "resources": {"cpu_limit": 8, "memory_limit_bytes": 16 * GIB},
        "ingress": {
            "mode": "http_basic_uat",
            "public_access": False,
            "shared_nginx_port": 8077,
            "base_path": "/smartscan/",
            "upstream": "127.0.0.1:18082",
            "https_required_after_basic_uat": True,
        },
        "monitoring": {
            "mode": "manual",
            "deploy_node_exporter": False,
            "deploy_alertmanager": False,
            "application_metrics_enabled": True,
            "accepted_capability_gap": True,
            "record_reference": validated["monitoring_record"],
        },
        "backup": {
            "required": False,
            "disposable_uat_data": True,
            "single_host_risk_acknowledged": True,
        },
    }


def _env_text(values: dict[str, str]) -> bytes:
    for key, value in values.items():
        _require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None, f"环境变量名无效：{key}")
        _require(
            "\n" not in value and "\r" not in value and "\x00" not in value,
            f"环境变量值无效：{key}",
        )
    return ("\n".join(f"{key}={value}" for key, value in values.items()) + "\n").encode()


def _random_urlsafe(byte_count: int = 48) -> str:
    return secrets.token_urlsafe(byte_count)


def _build_files(
    validated: dict[str, Any], preflight_hash: str, loop_hash: str
) -> tuple[dict[str, bytes], dict[str, str]]:
    database_password = _random_urlsafe()
    secret_key = _random_urlsafe()
    phone_pepper = _random_urlsafe()
    phone_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    admin_password = _random_urlsafe(32)
    metrics_token = _random_urlsafe()
    networks = validated["networks"]

    deploy = {
        "SMARTSCAN_DEPLOYMENT_TIER": "uat",
        "SMARTSCAN_UAT_ISOLATION_ACK": "uat-only-no-production-data",
        "COMPOSE_PROJECT_NAME": "smartscan-uat",
        "SMARTSCAN_UAT_RUNTIME_ENV_FILE": "/etc/smartscan/uat/runtime.env",
        "SMARTSCAN_UAT_ALLOCATION_FILE": "/etc/smartscan/uat/shared-host-allocation.json",
        "SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256": preflight_hash,
        "SMARTSCAN_UAT_LOOP_EVIDENCE_FILE": "/etc/smartscan/uat/loop-storage-evidence.json",
        "SMARTSCAN_UAT_LOOP_EVIDENCE_SHA256": loop_hash,
        "SMARTSCAN_UAT_BIND_ADDRESS": "127.0.0.1",
        "SMARTSCAN_UAT_HTTP_PORT": "18082",
        "SMARTSCAN_UAT_DATA_SUBNET": str(networks["data"]["subnet"]),
        "SMARTSCAN_UAT_DATA_GATEWAY": str(networks["data"]["gateway"]),
        "SMARTSCAN_UAT_EDGE_SUBNET": str(networks["edge"]["subnet"]),
        "SMARTSCAN_UAT_EDGE_GATEWAY": str(networks["edge"]["gateway"]),
        "SMARTSCAN_UAT_EGRESS_SUBNET": str(networks["egress"]["subnet"]),
        "SMARTSCAN_UAT_EGRESS_GATEWAY": str(networks["egress"]["gateway"]),
        "SMARTSCAN_UAT_POSTGRES_ROOT": "/mnt/data/smartscan/uat/postgres",
        "SMARTSCAN_UAT_DATA_ROOT": "/mnt/data/smartscan/uat/data",
        "SMARTSCAN_UAT_MODEL_ROOT": "/mnt/data/smartscan/uat/models/ocr",
        **ACCEPTED_IMAGES,
        "POSTGRES_PASSWORD": database_password,
    }
    runtime = {
        "SMARTSCAN_ENV": "production",
        "SMARTSCAN_DATABASE_URL": f"postgresql+psycopg://smartscan:{quote(database_password, safe='')}@postgres:5432/smartscan",
        "SMARTSCAN_AUTO_MIGRATE": "false",
        "SMARTSCAN_STORAGE_ROOT": "/srv/smartscan/data",
        "SMARTSCAN_INTERNAL_FILE_SEND_PREFIX": "/_smartscan_files",
        "SMARTSCAN_SECRET_KEY": secret_key,
        "SMARTSCAN_PHONE_HMAC_ACTIVE_KEY_ID": "uat-v1",
        "SMARTSCAN_PHONE_HMAC_PEPPERS": json.dumps({"uat-v1": phone_pepper}, separators=(",", ":")),
        "SMARTSCAN_PHONE_ENCRYPTION_ACTIVE_KEY_ID": "phone-uat-v1",
        "SMARTSCAN_PHONE_ENCRYPTION_KEYS": json.dumps(
            {"phone-uat-v1": phone_key}, separators=(",", ":")
        ),
        "SMARTSCAN_SUPERADMIN_PASSWORD": admin_password,
        "SMARTSCAN_CORS_ORIGINS": json.dumps([validated["origin"]], separators=(",", ":")),
        "SMARTSCAN_DEV_SMS_CODE": "",
        "SMARTSCAN_SMS_MODE": "disabled",
        "SMARTSCAN_WECOM_MODE": "disabled",
        "SMARTSCAN_WECOM_CORP_ID": "",
        "SMARTSCAN_WECOM_AGENT_ID": "",
        "SMARTSCAN_WECOM_SECRET": "",
        "SMARTSCAN_WECOM_REDIRECT_URI": "",
        "SMARTSCAN_OCR_ENABLED": "true",
        "SMARTSCAN_OCR_MODEL_ROOT": "/opt/smartscan/models/ocr",
        "SMARTSCAN_OCR_PACKAGE_VERSION": "3.7.0",
        "SMARTSCAN_OCR_ENGINE_VERSION": "3.3.1",
        "SMARTSCAN_OCR_MODEL_VERSION": "PP-OCRv6-small-v1",
        "SMARTSCAN_AI_PROVIDERS": "[]",
        "SMARTSCAN_AI_INTERNAL_TOKEN": "",
        "SMARTSCAN_AI_GATEWAY_URL": "",
        "SMARTSCAN_AI_PROVIDER_ID": "",
        "SMARTSCAN_AI_MEDIA_TRANSFER_MODE": "inline_data_url",
        "SMARTSCAN_AI_INTERNAL_MEDIA_URL": "",
        "SMARTSCAN_AI_MEDIA_BASE_URL": "",
        "SMARTSCAN_AI_MOCK_MODE": "false",
        "SMARTSCAN_QUEUE_HIGH_WATER_JOBS": "1000",
        "SMARTSCAN_MAX_ACTIVE_JOBS_PER_USER": "2",
        "SMARTSCAN_STORAGE_MIN_FREE_BYTES": str(2 * GIB),
        "SMARTSCAN_STORAGE_MIN_FREE_PERCENT": "15",
        "SMARTSCAN_STORAGE_QUOTA_BYTES": str(32 * GIB),
        "SMARTSCAN_STORAGE_WARNING_PERCENT": "70",
        "SMARTSCAN_STORAGE_CLEANUP_PERCENT": "85",
        "SMARTSCAN_STORAGE_STOP_WRITES_PERCENT": "95",
        "SMARTSCAN_USER_STORAGE_QUOTA_BYTES": str(32 * GIB),
        "SMARTSCAN_WORKER_HEARTBEAT_INTERVAL_SECONDS": "10",
        "SMARTSCAN_WORKER_STALE_SECONDS": "45",
        "SMARTSCAN_OPS_METRICS_ENABLED": "true",
        "SMARTSCAN_OPS_METRICS_TOKEN": metrics_token,
    }
    allocation = (
        json.dumps(_allocation(validated), ensure_ascii=False, indent=2, sort_keys=True).encode()
        + b"\n"
    )
    files = {
        "deploy": _env_text(deploy),
        "runtime": _env_text(runtime),
        "allocation": allocation,
        "bootstrap": (admin_password + "\n").encode(),
    }
    secret_lengths = {
        "POSTGRES_PASSWORD": str(len(database_password)),
        "SMARTSCAN_DATABASE_URL": "derived-from-POSTGRES_PASSWORD",
        "SMARTSCAN_SECRET_KEY": str(len(secret_key)),
        "SMARTSCAN_PHONE_HMAC_PEPPERS": str(len(phone_pepper)),
        "SMARTSCAN_PHONE_ENCRYPTION_KEYS": "32-bytes",
        "SMARTSCAN_SUPERADMIN_PASSWORD": str(len(admin_password)),
        "SMARTSCAN_OPS_METRICS_TOKEN": str(len(metrics_token)),
    }
    return files, secret_lengths


def _write_atomic(path: Path, content: bytes, *, uid: int, gid: int) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".smartscan-uat-config.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        remaining = memoryview(content)
        while remaining:
            written = os.write(fd, remaining)
            _require(written > 0, f"配置原子写入失败：{path}")
            remaining = remaining[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        if os.name != "nt":
            os.chown(temporary, uid, gid)
        else:
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        _require("=" in raw, f"环境文件格式无效：{path}")
        key, value = raw.split("=", 1)
        _require(key not in values, f"环境变量重复：{key}")
        values[key] = value
    return values


def _verify_ocr_model(path: Path, *, root_uid: int = 0) -> dict[str, Any]:
    manifest_path = path / "manifest.json"
    _require(manifest_path.is_file() and not manifest_path.is_symlink(), "OCR模型manifest缺失")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("OCR模型manifest无效") from exc
    _require(manifest.get("schema_version") == 1, "OCR模型manifest版本无效")
    _require(manifest.get("paddleocr_version") == "3.7.0", "OCR模型PaddleOCR版本无效")
    _require(manifest.get("paddlepaddle_version") == "3.3.1", "OCR模型PaddlePaddle版本无效")
    _require(manifest.get("model_version") == "PP-OCRv6-small-v1", "OCR模型内部版本无效")
    source = _safe_text(manifest.get("source"), "ocr.source")
    license_name = _safe_text(manifest.get("license"), "ocr.license")
    root = path.resolve()
    _require(path.is_dir() and not path.is_symlink(), "OCR模型根目录无效")
    model_directories: list[Path] = []
    for key in ("text_detection_dir", "text_recognition_dir"):
        relative_directory = Path(str(manifest.get(key, "")))
        _require(
            not relative_directory.is_absolute() and ".." not in relative_directory.parts,
            "OCR模型目录字段无效",
        )
        directory = (path / relative_directory).resolve()
        _require(root in directory.parents and directory.is_dir(), "OCR模型目录缺失或越界")
        model_directories.append(directory)
    files = manifest.get("files")
    _require(isinstance(files, dict) and files, "OCR模型文件清单为空")
    actual_files = {
        item.relative_to(root).as_posix()
        for directory in model_directories
        for item in directory.rglob("*")
        if item.is_file()
    }
    _require(actual_files == set(files), "OCR模型文件清单不完整")
    total_bytes = 0
    for relative, expected in files.items():
        _require(
            isinstance(relative, str) and re.fullmatch(r"[a-f0-9]{64}", str(expected)) is not None,
            "OCR模型文件清单无效",
        )
        target = (path / relative).resolve()
        _require(
            root in target.parents and target.is_file() and not target.is_symlink(),
            "OCR模型文件路径无效",
        )
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        _require(actual == expected, "OCR模型文件摘要不一致")
        total_bytes += target.stat().st_size
        if os.name != "nt":
            info = target.stat()
            _require(
                info.st_uid == root_uid and info.st_gid == root_uid,
                "OCR模型文件必须由root拥有",
            )
            _require(
                stat.S_IMODE(info.st_mode) & 0o022 == 0,
                "OCR模型文件不得允许组或其他用户写入",
            )
    _require(total_bytes <= 4 * GIB, "OCR模型包超过4 GiB预算")
    return {
        "model_version": manifest["model_version"],
        "file_count": len(files),
        "total_bytes": total_bytes,
        "source_recorded": bool(source),
        "license_recorded": bool(license_name),
    }


def verify(
    paths: Paths = Paths(), *, deploy_uid: int | None = None, root_uid: int = 0
) -> dict[str, Any]:
    if deploy_uid is None:
        _require(pwd is not None, "目标系统缺少POSIX用户数据库")
        deploy_uid = pwd.getpwnam(DEPLOY_USER).pw_uid
    deploy_gid = pwd.getpwnam(DEPLOY_USER).pw_gid if pwd is not None else deploy_uid
    for path in (paths.deploy_env, paths.runtime_env, paths.bootstrap_password):
        _require(path.is_file() and not path.is_symlink(), f"配置文件缺失或类型异常：{path}")
        info = path.stat()
        if os.name != "nt":
            _require(
                info.st_uid == deploy_uid
                and info.st_gid == deploy_gid
                and stat.S_IMODE(info.st_mode) == 0o600,
                f"部署配置所有者或权限无效：{path}",
            )
    for path in (paths.allocation, paths.preflight, paths.loop_evidence, paths.input_file):
        _load_json(path, owner_uid=root_uid)

    deploy = _parse_env(paths.deploy_env)
    runtime = _parse_env(paths.runtime_env)
    for key, expected in ACCEPTED_IMAGES.items():
        _require(deploy.get(key) == expected, f"固定镜像被替换：{key}")
    postgres_ref = deploy["SMARTSCAN_UAT_POSTGRES_IMAGE"]
    _require(
        not any(item in postgres_ref for item in REJECTED_POSTGRES_DIGESTS),
        "未接受的PostgreSQL制品被写入配置",
    )
    _require(
        deploy.get("SMARTSCAN_UAT_BIND_ADDRESS") == "127.0.0.1"
        and deploy.get("SMARTSCAN_UAT_HTTP_PORT") == "18082",
        "回环入口配置无效",
    )
    _require(runtime.get("SMARTSCAN_SMS_MODE") == "disabled", "UAT短信必须关闭")
    _require(runtime.get("SMARTSCAN_WECOM_MODE") == "disabled", "UAT企业微信必须关闭")
    _require(runtime.get("SMARTSCAN_AI_PROVIDERS") == "[]", "UAT真实AI Provider必须关闭")
    _require(
        not runtime.get("SMARTSCAN_AI_GATEWAY_URL")
        and not runtime.get("SMARTSCAN_AI_INTERNAL_TOKEN"),
        "UAT AI运行参数必须为空",
    )
    for key in SECRET_FIELDS:
        _require(key in deploy or key in runtime, f"缺少Secret字段：{key}")
    _require(len(deploy["POSTGRES_PASSWORD"]) >= 48, "数据库Secret长度不足")
    _require(len(runtime["SMARTSCAN_SECRET_KEY"]) >= 48, "应用Secret长度不足")
    _require(len(runtime["SMARTSCAN_SUPERADMIN_PASSWORD"]) >= 32, "引导管理员Secret长度不足")
    _require(len(runtime["SMARTSCAN_OPS_METRICS_TOKEN"]) >= 48, "指标Secret长度不足")
    _require(
        paths.bootstrap_password.read_text(encoding="utf-8").rstrip("\n")
        == runtime["SMARTSCAN_SUPERADMIN_PASSWORD"],
        "引导密码交付文件与运行配置不一致",
    )
    preflight_hash, loop_hash = _validate_evidence(paths, root_uid=root_uid)
    _require(
        deploy.get("SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256") == preflight_hash, "预检摘要不一致"
    )
    _require(deploy.get("SMARTSCAN_UAT_LOOP_EVIDENCE_SHA256") == loop_hash, "loop证据摘要不一致")
    model = _verify_ocr_model(paths.model_root, root_uid=root_uid)
    return {
        "status": "passed",
        "fixed_image_count": len(ACCEPTED_IMAGES),
        "secret_fields": {key: {"present": True, "value_printed": False} for key in SECRET_FIELDS},
        "ocr_model": model,
        "external_services": {
            "sms": "disabled",
            "wecom": "disabled",
            "real_ai": "disabled",
            "ai_profile": "not_started",
        },
        "secrets_included": False,
    }


def generate(
    paths: Paths = Paths(), *, deploy_uid: int | None = None, root_uid: int = 0
) -> dict[str, Any]:
    if deploy_uid is None:
        _require(pwd is not None, "目标系统缺少POSIX用户数据库")
        deploy_record = pwd.getpwnam(DEPLOY_USER)
        deploy_uid, deploy_gid = deploy_record.pw_uid, deploy_record.pw_gid
    else:
        deploy_gid = deploy_uid
    outputs = (paths.deploy_env, paths.runtime_env, paths.allocation, paths.bootstrap_password)
    existing = [path.exists() or path.is_symlink() for path in outputs]
    if all(existing):
        result = verify(paths, deploy_uid=deploy_uid, root_uid=root_uid)
        result["result"] = "already_ready"
        return result
    _require(not any(existing), "配置存在部分状态，拒绝覆盖或自动修复")
    source, _ = _load_json(paths.input_file, owner_uid=root_uid)
    validated = _validate_input(source)
    preflight_hash, loop_hash = _validate_evidence(paths, root_uid=root_uid)
    files, secret_lengths = _build_files(validated, preflight_hash, loop_hash)
    _write_atomic(paths.deploy_env, files["deploy"], uid=deploy_uid, gid=deploy_gid)
    _write_atomic(paths.runtime_env, files["runtime"], uid=deploy_uid, gid=deploy_gid)
    _write_atomic(paths.allocation, files["allocation"], uid=root_uid, gid=root_uid)
    _write_atomic(paths.bootstrap_password, files["bootstrap"], uid=deploy_uid, gid=deploy_gid)
    return {
        "status": "passed",
        "result": "generated",
        "secret_fields": {
            key: {"present": True, "length": secret_lengths[key], "value_printed": False}
            for key in SECRET_FIELDS
        },
        "secrets_included": False,
        "ocr_model_ready": (paths.model_root / "manifest.json").is_file(),
    }


def validate_image_identities(
    paths: Paths = Paths(), *, root_uid: int = 0
) -> dict[str, tuple[int, int]]:
    document, _ = _load_json(paths.image_identities, owner_uid=root_uid)
    _require(document.get("schema_version") == "1.0", "镜像身份schema_version无效")
    _require(document.get("platform") == "linux/amd64", "镜像身份平台必须是linux/amd64")
    images = document.get("images")
    _require(isinstance(images, dict) and set(images) == set(ACCEPTED_IMAGES), "镜像身份记录不完整")
    identities: dict[str, tuple[int, int]] = {}
    for key, reference in ACCEPTED_IMAGES.items():
        item = images[key]
        _require(
            isinstance(item, dict) and item.get("reference") == reference,
            f"镜像身份引用不一致：{key}",
        )
        _require(item.get("repo_digest_verified") is True, f"镜像RepoDigest未核验：{key}")
        uid, gid = item.get("runtime_uid"), item.get("runtime_gid")
        _require(
            isinstance(uid, int) and isinstance(gid, int) and uid >= 0 and gid >= 0,
            f"镜像UID/GID无效：{key}",
        )
        identities[key] = (uid, gid)
    _require(identities["SMARTSCAN_UAT_POSTGRES_IMAGE"] == (70, 70), "PostgreSQL必须是70:70")
    _require(
        identities["SMARTSCAN_UAT_API_IMAGE"] == identities["SMARTSCAN_UAT_WORKER_IMAGE"],
        "API与Worker共享数据目录但UID/GID不一致",
    )
    return identities


def apply_ownership(paths: Paths = Paths(), *, root_uid: int = 0) -> dict[str, Any]:
    identities = validate_image_identities(paths, root_uid=root_uid)
    targets = {
        paths.postgres_root: (*identities["SMARTSCAN_UAT_POSTGRES_IMAGE"], 0o700),
        paths.data_root: (*identities["SMARTSCAN_UAT_API_IMAGE"], 0o750),
        paths.model_root: (root_uid, root_uid, 0o755),
    }
    for path in targets:
        _require(path.is_dir() and not path.is_symlink(), f"所有权目标不是固定真实目录：{path}")
    _require(not any(paths.postgres_root.iterdir()), "PostgreSQL目录非空，拒绝改变所有权")
    _require(not any(paths.data_root.iterdir()), "业务数据目录非空，拒绝改变所有权")
    for path, (uid, gid, mode) in targets.items():
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        info = path.stat()
        _require(
            (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode),
            f"所有权应用后复核失败：{path}",
        )
    return {
        "status": "passed",
        "result": "ownership_applied",
        "directories": {
            "postgres": {
                "uid": targets[paths.postgres_root][0],
                "gid": targets[paths.postgres_root][1],
                "mode": "0700",
            },
            "data": {
                "uid": targets[paths.data_root][0],
                "gid": targets[paths.data_root][1],
                "mode": "0750",
            },
            "models": {"uid": root_uid, "gid": root_uid, "mode": "0755"},
        },
        "secrets_included": False,
    }


def safe_status(paths: Paths = Paths()) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "passed", "secrets_included": False, "objects": {}}
    for name, path in {
        "deploy_env": paths.deploy_env,
        "runtime_env": paths.runtime_env,
        "allocation": paths.allocation,
        "preflight": paths.preflight,
        "loop_evidence": paths.loop_evidence,
        "bootstrap_password": paths.bootstrap_password,
        "image_identities": paths.image_identities,
        "postgres_root": paths.postgres_root,
        "data_root": paths.data_root,
        "model_root": paths.model_root,
    }.items():
        if path.is_symlink():
            state = "abnormal_symlink"
        elif path.is_file():
            state = "file"
        elif path.is_dir():
            state = "directory"
        elif path.exists():
            state = "abnormal"
        else:
            state = "absent"
        result["objects"][name] = state
    return result


def _print_safe(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in {
        "generate",
        "verify",
        "status",
        "validate-identities",
        "apply-ownership",
    }:
        print(
            "用法：smartscan-uat-config {generate|verify|status|validate-identities|apply-ownership}",
            file=sys.stderr,
        )
        return 64
    try:
        if arguments[0] == "generate":
            result = generate()
        elif arguments[0] == "verify":
            result = verify()
        elif arguments[0] == "validate-identities":
            identities = validate_image_identities()
            result = {
                "status": "passed",
                "identity_count": len(identities),
                "secrets_included": False,
            }
        elif arguments[0] == "apply-ownership":
            result = apply_ownership()
        else:
            result = safe_status()
    except ConfigError as exc:
        _print_safe({"status": "failed", "reason": str(exc), "secrets_included": False})
        return 1
    _print_safe(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
