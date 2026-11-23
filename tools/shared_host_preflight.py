"""采集并离线验证 SmartScan 共享宿主机只读预检证据。"""

from __future__ import annotations

import argparse
import glob
import hashlib
import ipaddress
import json
import os
import platform
import re
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import pwd
except ModuleNotFoundError:  # Windows 仅运行纯函数测试
    pwd = None  # type: ignore[assignment]

SCHEMA_VERSION = "1.0"
ALLOCATION_SCHEMA_VERSION = "1.2"
GIB = 1024**3
DEFAULT_MAX_AGE_HOURS = 24
REQUIRED_NETWORKS = frozenset({"data", "edge", "egress"})
FORBIDDEN_HOST_PORTS = frozenset({80, 443})
PLACEHOLDER_WORDS = ("replace", "example", "placeholder", "change-me", "待填写", "待确认")
SAFE_BIND_ADDRESSES = frozenset({"127.0.0.1", "::1"})
BOOTSTRAP_ROOT = Path("/home/szhzx/smartscan-uat-config-bootstrap")
BOOTSTRAP_FILENAMES = (
    "deployment-input.json",
    "preflight-summary.json",
    "loop-storage-evidence.json",
)
EXPECTED_HOSTNAME = "ctiecaiserver"
EXPECTED_USER = "szhzx"
LOOP_EXECUTOR = "/usr/local/libexec/smartscan/smartscan-uat-loop-storage"
OCR_EXECUTOR = "/usr/local/libexec/smartscan/smartscan-uat-ocr-model"
LOOP_BACKING_FILE = "/mnt/data/smartscan-loop/uat.ext4"
LOOP_MOUNT_POINT = "/mnt/data/smartscan/uat"
LOOP_UNIT_NAME = "mnt-data-smartscan-uat.mount"
LOOP_UNIT_PATH = f"/etc/systemd/system/{LOOP_UNIT_NAME}"
Runner = Callable[[tuple[str, ...]], str]


class PreflightError(ValueError):
    """预检输入或现场状态不满足失败关闭要求。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreflightResult:
    environment: str
    project_name: str
    captured_at: str
    validated_at: str
    checks: tuple[str, ...]
    snapshot_sha256: str
    allocation_sha256: str

    def safe_summary(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "environment": self.environment,
            "project_name": self.project_name,
            "captured_at": self.captured_at,
            "validated_at": self.validated_at,
            "checks": list(self.checks),
            "snapshot_sha256": self.snapshot_sha256,
            "allocation_sha256": self.allocation_sha256,
            "contains_network_details": False,
            "contains_secrets": False,
        }


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise PreflightError(code, message)


def _run_command(args: tuple[str, ...]) -> str:
    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("command_failed", f"只读命令执行失败：{args[0]}") from exc
    return completed.stdout


def _json_output(runner: Runner, args: tuple[str, ...]) -> Any:
    raw = runner(args).strip()
    try:
        return json.loads(raw or "null")
    except json.JSONDecodeError as exc:
        raise PreflightError("command_json_invalid", f"只读命令返回无效 JSON：{args[0]}") from exc


def _parse_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PreflightError("os_release_unavailable", "无法读取 /etc/os-release") from exc
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return {"id": values.get("ID", ""), "version_id": values.get("VERSION_ID", "")}


def _parse_meminfo(path: Path = Path("/proc/meminfo")) -> tuple[int, int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PreflightError("meminfo_unavailable", "无法读取 /proc/meminfo") from exc
    values: dict[str, int] = {}
    for line in lines:
        match = re.fullmatch(r"([A-Za-z_()]+):\s+(\d+)\s+kB", line.strip())
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    _require("MemTotal" in values, "meminfo_invalid", "MemTotal 缺失")
    _require("MemAvailable" in values, "meminfo_invalid", "MemAvailable 缺失")
    return values["MemTotal"], values["MemAvailable"]


def _parse_filesystems(raw: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:
        fields = line.split(maxsplit=6)
        if len(fields) != 7:
            continue
        source, fs_type, total, used, available, percent, target = fields
        rows.append(
            {
                "source": source,
                "fs_type": fs_type,
                "total_bytes": int(total),
                "used_bytes": int(used),
                "available_bytes": int(available),
                "used_percent": int(percent.rstrip("%")),
                "target": target,
            }
        )
    return rows


def _parse_inode_filesystems(raw: str) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    for line in raw.splitlines()[1:]:
        fields = line.split(maxsplit=4)
        if len(fields) != 5:
            continue
        total, used, available, percent, target = fields
        rows[target] = {
            "inode_total": int(total),
            "inode_used": int(used),
            "inode_available": int(available),
            "inode_used_percent": int(percent.rstrip("%")),
        }
    return rows


def _parse_listeners(raw: str) -> list[dict[str, Any]]:
    listeners: list[dict[str, Any]] = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        protocol = fields[0].casefold()
        local = fields[4]
        address, separator, port_text = local.rpartition(":")
        if not separator or not port_text.isdigit():
            continue
        listeners.append(
            {
                "protocol": "tcp" if protocol.startswith("tcp") else "udp",
                "address": address.strip("[]"),
                "port": int(port_text),
            }
        )
    return listeners


def _parse_containers(raw: str) -> list[dict[str, str]]:
    containers: list[dict[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PreflightError("docker_ps_invalid", "docker ps 返回无效 JSON 行") from exc
        containers.append(
            {
                "id": str(item.get("ID", "")),
                "name": str(item.get("Names", "")),
                "image": str(item.get("Image", "")),
                "state": str(item.get("State", "")),
                "status": str(item.get("Status", "")),
                "ports": str(item.get("Ports", "")),
                "networks": str(item.get("Networks", "")),
            }
        )
    return containers


def _parse_network_ids(raw: str) -> tuple[str, ...]:
    ids: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PreflightError(
                "docker_network_ls_invalid", "docker network ls 返回无效 JSON 行"
            ) from exc
        network_id = str(item.get("ID", ""))
        if network_id:
            ids.append(network_id)
    return tuple(ids)


def _normalize_networks(items: Any) -> list[dict[str, Any]]:
    _require(isinstance(items, list), "docker_network_inspect_invalid", "网络检查结果必须是数组")
    networks: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ipam = item.get("IPAM") if isinstance(item.get("IPAM"), dict) else {}
        configs = ipam.get("Config") if isinstance(ipam.get("Config"), list) else []
        endpoints = item.get("Containers")
        networks.append(
            {
                "id": str(item.get("Id", "")),
                "name": str(item.get("Name", "")),
                "driver": str(item.get("Driver", "")),
                "internal": bool(item.get("Internal", False)),
                "endpoint_count": len(endpoints) if isinstance(endpoints, dict) else 0,
                "subnets": [
                    {
                        "subnet": str(config.get("Subnet", "")),
                        "gateway": str(config.get("Gateway", "")),
                        "ip_range": str(config.get("IPRange", "")),
                    }
                    for config in configs
                    if isinstance(config, dict) and config.get("Subnet")
                ],
            }
        )
    return networks


def _normalize_routes(items: Any, family: int) -> list[dict[str, Any]]:
    _require(isinstance(items, list), "route_output_invalid", "路由检查结果必须是数组")
    routes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        routes.append(
            {
                "family": family,
                "dst": str(item.get("dst", "default")),
                "gateway": str(item.get("gateway", "")),
                "dev": str(item.get("dev", "")),
                "table": str(item.get("table", "main")),
                "type": str(item.get("type", "unicast")),
            }
        )
    return routes


def _normalize_rules(items: Any) -> list[dict[str, Any]]:
    _require(isinstance(items, list), "rule_output_invalid", "策略路由检查结果必须是数组")
    return [
        {
            "priority": item.get("priority"),
            "from": str(item.get("from", "all")),
            "to": str(item.get("to", "all")),
            "table": str(item.get("table", "")),
            "fwmark": str(item.get("fwmark", "")),
        }
        for item in items
        if isinstance(item, dict)
    ]


def _normalize_addresses(items: Any) -> list[dict[str, Any]]:
    _require(isinstance(items, list), "address_output_invalid", "接口地址检查结果必须是数组")
    addresses: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        interface = str(item.get("ifname", ""))
        for info in item.get("addr_info", []):
            if not isinstance(info, dict) or info.get("family") not in {"inet", "inet6"}:
                continue
            addresses.append(
                {
                    "interface": interface,
                    "family": str(info.get("family")),
                    "address": str(info.get("local", "")),
                    "prefixlen": int(info.get("prefixlen", 0)),
                    "scope": str(info.get("scope", "")),
                }
            )
    return addresses


def _published_ports(containers: Iterable[Mapping[str, Any]]) -> set[int]:
    ports: set[int] = set()
    for container in containers:
        raw = str(container.get("ports", ""))
        for match in re.finditer(r"(?:^|,\s*)(?:[^,]*:)?(\d+)->\d+/(?:tcp|udp)", raw):
            ports.add(int(match.group(1)))
    return ports


def build_snapshot(
    *,
    runner: Runner = _run_command,
    now: datetime | None = None,
    hostname: str | None = None,
    os_release: Mapping[str, str] | None = None,
    memory: tuple[int, int] | None = None,
    logical_cpu_count: int | None = None,
    load_average: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """只执行固定的只读命令并返回已裁剪的现场快照。"""

    now = now or datetime.now(UTC)
    os_release = dict(os_release or _parse_os_release())
    memory_total, memory_available = memory or _parse_meminfo()
    network_ids = _parse_network_ids(
        runner(("docker", "network", "ls", "--no-trunc", "--format", "{{json .}}"))
    )
    networks = (
        _normalize_networks(_json_output(runner, ("docker", "network", "inspect", *network_ids)))
        if network_ids
        else []
    )
    server = _json_output(runner, ("docker", "version", "--format", "{{json .Server}}"))
    if not isinstance(server, dict):
        raise PreflightError("docker_version_invalid", "Docker Server 版本信息无效")
    containers = _parse_containers(
        runner(("docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"))
    )
    filesystems = _parse_filesystems(
        runner(
            (
                "df",
                "-B1",
                "--output=source,fstype,size,used,avail,pcent,target",
                "/",
                "/mnt/data",
            )
        )
    )
    inode_filesystems = _parse_inode_filesystems(
        runner(
            (
                "df",
                "--output=itotal,iused,iavail,ipcent,target",
                "/",
                "/mnt/data",
            )
        )
    )
    for filesystem in filesystems:
        filesystem.update(inode_filesystems.get(str(filesystem["target"]), {}))
    routes = _normalize_routes(
        _json_output(runner, ("ip", "-j", "-4", "route", "show", "table", "all")), 4
    ) + _normalize_routes(
        _json_output(runner, ("ip", "-j", "-6", "route", "show", "table", "all")), 6
    )
    rules = _normalize_rules(_json_output(runner, ("ip", "-j", "rule", "show")))
    addresses = _normalize_addresses(_json_output(runner, ("ip", "-j", "address", "show")))
    listeners = _parse_listeners(runner(("ss", "-H", "-lntu")))
    compose_version = runner(("docker", "compose", "version", "--short")).strip()
    monitoring_markers = ("prometheus", "grafana", "alertmanager", "node-exporter")
    monitoring = {
        marker: any(
            item["state"].casefold() == "running"
            and marker.replace("-", "")
            in f"{item['name']} {item['image']}".casefold().replace("-", "").replace("_", "")
            for item in containers
        )
        for marker in monitoring_markers
    }
    load_one, load_five, load_fifteen = load_average or os.getloadavg()
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "hostname": hostname or socket.gethostname(),
        "os": {
            "id": str(os_release.get("id", "")),
            "version_id": str(os_release.get("version_id", "")),
            "kernel": platform.release(),
        },
        "host": {
            "logical_cpu_count": logical_cpu_count or os.cpu_count() or 0,
            "memory_total_bytes": memory_total,
            "memory_available_bytes": memory_available,
            "load_average": {
                "one_minute": load_one,
                "five_minutes": load_five,
                "fifteen_minutes": load_fifteen,
            },
            "filesystems": filesystems,
        },
        "docker": {
            "server_version": str(server.get("Version", "")),
            "api_version": str(server.get("ApiVersion", "")),
            "compose_version": compose_version,
            "containers": containers,
            "networks": networks,
        },
        "network": {
            "routes": routes,
            "rules": rules,
            "addresses": addresses,
            "listeners": listeners,
        },
        "monitoring": monitoring,
        "collector": {
            "read_only_commands": True,
            "container_environment_collected": False,
            "container_mounts_collected": False,
            "secrets_collected": False,
        },
    }


def _read_json_file(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError("input_invalid", f"无法读取有效的{label} JSON") from exc
    _require(isinstance(document, dict), "input_invalid", f"{label}根节点必须是对象")
    return document, hashlib.sha256(raw).hexdigest()


def _parse_time(value: Any, label: str) -> datetime:
    _require(isinstance(value, str), "time_invalid", f"{label}必须是时间字符串")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PreflightError("time_invalid", f"{label}格式无效") from exc
    _require(parsed.tzinfo is not None, "time_invalid", f"{label}必须包含时区")
    return parsed.astimezone(UTC)


def _non_placeholder(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value.strip(), "approval_missing", f"{label}缺失")
    normalized = value.strip()
    _require(
        not any(word in normalized.casefold() for word in PLACEHOLDER_WORDS),
        "approval_placeholder",
        f"{label}仍是占位值",
    )
    return normalized


def _network(
    value: Any, label: str, *, enforce_application_size: bool = True
) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(str(value), strict=True)
    except ValueError as exc:
        raise PreflightError("cidr_invalid", f"{label} CIDR 无效") from exc
    _require(isinstance(network, ipaddress.IPv4Network), "cidr_invalid", f"{label}仅支持 IPv4")
    _require(
        network.is_private and not network.is_loopback and not network.is_link_local,
        "cidr_unsafe",
        f"{label}必须使用批准的私有 IPv4 网段",
    )
    if enforce_application_size:
        _require(16 <= network.prefixlen <= 29, "cidr_size_invalid", f"{label}前缀长度不安全")
    return network


def _existing_networks(snapshot: Mapping[str, Any]) -> list[ipaddress.IPv4Network]:
    values: list[ipaddress.IPv4Network] = []
    docker = snapshot.get("docker") if isinstance(snapshot.get("docker"), dict) else {}
    for item in docker.get("networks", []):
        if not isinstance(item, dict):
            continue
        for config in item.get("subnets", []):
            if not isinstance(config, dict) or not config.get("subnet"):
                continue
            try:
                parsed = ipaddress.ip_network(str(config["subnet"]), strict=False)
            except ValueError:
                continue
            if isinstance(parsed, ipaddress.IPv4Network):
                values.append(parsed)
    return values


def _route_networks(snapshot: Mapping[str, Any]) -> list[ipaddress.IPv4Network]:
    values: list[ipaddress.IPv4Network] = []
    network = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    for item in network.get("routes", []):
        if not isinstance(item, dict) or int(item.get("family", 0)) != 4:
            continue
        destination = str(item.get("dst", "default"))
        if destination == "default":
            continue
        try:
            parsed = ipaddress.ip_network(destination, strict=False)
        except ValueError:
            continue
        if parsed.prefixlen > 0:
            values.append(parsed)
    return values


def _find_filesystem(snapshot: Mapping[str, Any], root: PurePosixPath) -> Mapping[str, Any]:
    host = snapshot.get("host") if isinstance(snapshot.get("host"), dict) else {}
    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for item in host.get("filesystems", []):
        if not isinstance(item, dict):
            continue
        target = PurePosixPath(str(item.get("target", "")))
        if target == root or target in root.parents:
            candidates.append((len(target.parts), item))
    _require(bool(candidates), "filesystem_missing", "存储根没有对应文件系统证据")
    return max(candidates, key=lambda item: item[0])[1]


def validate_preflight(
    snapshot: Mapping[str, Any],
    allocation: Mapping[str, Any],
    *,
    snapshot_sha256: str,
    allocation_sha256: str,
    now: datetime | None = None,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> PreflightResult:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    _require(snapshot.get("schema_version") == SCHEMA_VERSION, "schema_invalid", "快照版本不匹配")
    _require(
        allocation.get("schema_version") == ALLOCATION_SCHEMA_VERSION,
        "schema_invalid",
        "资源确认版本不匹配",
    )
    captured = _parse_time(snapshot.get("captured_at"), "captured_at")
    _require(captured <= now + timedelta(minutes=5), "snapshot_future", "现场快照来自未来")
    _require(
        now - captured <= timedelta(hours=max_age_hours),
        "snapshot_stale",
        f"现场快照超过 {max_age_hours} 小时",
    )
    collector = snapshot.get("collector") if isinstance(snapshot.get("collector"), dict) else {}
    _require(collector.get("read_only_commands") is True, "collector_unsafe", "快照不是只读采集")
    _require(
        collector.get("container_environment_collected") is False
        and collector.get("container_mounts_collected") is False
        and collector.get("secrets_collected") is False,
        "collector_unsafe",
        "快照包含环境变量、挂载或 Secret",
    )

    environment = allocation.get("environment")
    project_name = allocation.get("compose_project_name")
    _require(environment == "uat", "environment_invalid", "OPS-000 第一阶段只允许 UAT")
    _require(project_name == "smartscan-uat", "project_invalid", "Compose 项目必须为 smartscan-uat")
    expected_hostname = _non_placeholder(allocation.get("target_hostname"), "目标主机")
    _require(snapshot.get("hostname") == expected_hostname, "hostname_mismatch", "目标主机不匹配")

    confirmation = (
        allocation.get("confirmation") if isinstance(allocation.get("confirmation"), dict) else {}
    )
    _non_placeholder(confirmation.get("confirmed_by"), "服务器共同使用人")
    _non_placeholder(confirmation.get("change_record"), "变更记录")
    _non_placeholder(confirmation.get("validation_record"), "验证记录")
    _non_placeholder(confirmation.get("rollback_record"), "回滚记录")
    confirmed_at = _parse_time(confirmation.get("confirmed_at"), "confirmed_at")
    _require(
        confirmed_at <= now + timedelta(minutes=5),
        "confirmation_invalid",
        "确认时间来自未来",
    )

    requested_networks = allocation.get("networks")
    _require(isinstance(requested_networks, dict), "networks_missing", "缺少固定网络分配")
    _require(set(requested_networks) == REQUIRED_NETWORKS, "networks_invalid", "网络集合必须精确")
    parsed_networks: dict[str, ipaddress.IPv4Network] = {}
    for name in sorted(REQUIRED_NETWORKS):
        config = requested_networks[name]
        _require(isinstance(config, dict), "networks_invalid", f"{name} 网络配置无效")
        parsed = _network(config.get("subnet"), name)
        try:
            gateway = ipaddress.ip_address(str(config.get("gateway", "")))
        except ValueError as exc:
            raise PreflightError("gateway_invalid", f"{name} 网关无效") from exc
        _require(gateway in parsed.hosts(), "gateway_invalid", f"{name} 网关不在可用地址内")
        parsed_networks[name] = parsed
    for name, network in parsed_networks.items():
        for other_name, other in parsed_networks.items():
            if name < other_name:
                _require(
                    not network.overlaps(other),
                    "requested_network_overlap",
                    f"{name} 与 {other_name} 网段重叠",
                )
    reserved = [
        _network(value, "保留网段", enforce_application_size=False)
        for value in allocation.get("reserved_cidrs", [])
    ]
    conflicts = _existing_networks(snapshot) + _route_networks(snapshot) + reserved
    for name, network in parsed_networks.items():
        _require(
            not any(network.overlaps(existing) for existing in conflicts),
            "network_conflict",
            f"{name} 与现场网络、路由或保留网段冲突",
        )

    listeners = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    occupied = {
        int(item["port"])
        for item in listeners.get("listeners", [])
        if isinstance(item, dict) and isinstance(item.get("port"), int)
    }
    docker = snapshot.get("docker") if isinstance(snapshot.get("docker"), dict) else {}
    occupied.update(_published_ports(docker.get("containers", [])))
    host_addresses = {
        str(item.get("address", ""))
        for item in listeners.get("addresses", [])
        if isinstance(item, dict) and item.get("address")
    }
    ports = allocation.get("host_ports")
    _require(isinstance(ports, list) and ports, "ports_missing", "缺少主机端口分配")
    _require(len(ports) == 1, "ports_invalid", "UAT 只能分配一个宿主机回环端口")
    seen_ports: set[int] = set()
    for item in ports:
        _require(isinstance(item, dict), "port_invalid", "主机端口配置无效")
        port = item.get("port")
        _require(isinstance(port, int) and 1024 <= port <= 65535, "port_invalid", "端口无效")
        _require(port not in FORBIDDEN_HOST_PORTS, "port_forbidden", "禁止占用 80/443")
        _require(port not in occupied and port not in seen_ports, "port_conflict", "端口已被占用")
        address = str(item.get("bind_address", ""))
        if address not in SAFE_BIND_ADDRESSES:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise PreflightError("bind_address_invalid", "监听地址无效") from exc
            _require(
                parsed_address.is_private and not parsed_address.is_unspecified,
                "bind_address_invalid",
                "禁止绑定所有接口或公网地址",
            )
            _require(
                address in host_addresses,
                "bind_address_missing",
                "监听地址不属于目标宿主机",
            )
        purpose = _non_placeholder(item.get("purpose"), "端口用途")
        _require(
            purpose == "UAT Web 回环入口" and port == 18082 and address == "127.0.0.1",
            "port_invalid",
            "UAT 只允许 127.0.0.1:18082 Web 回环入口",
        )
        seen_ports.add(port)

    storage = allocation.get("storage") if isinstance(allocation.get("storage"), dict) else {}
    storage_root = PurePosixPath(str(storage.get("root", "")))
    _require(
        storage_root == PurePosixPath("/mnt/data/smartscan/uat"),
        "storage_root_invalid",
        "UAT 数据根必须为 /mnt/data/smartscan/uat",
    )
    quota = storage.get("quota_bytes")
    _require(
        isinstance(quota, int) and quota == 50 * GIB,
        "storage_quota_invalid",
        "UAT 配额必须为 50 GiB",
    )
    _require(
        storage.get("hard_limit_type") == "loop_ext4",
        "storage_limit_type_invalid",
        "UAT 硬限制必须使用loop ext4",
    )
    _require(storage.get("hard_limit_confirmed") is True, "storage_limit_missing", "未确认硬限制")
    _require(
        storage.get("disposable_data") is True,
        "storage_policy_invalid",
        "UAT 数据必须明确可丢弃和重建",
    )
    _require(
        tuple(
            storage.get(key)
            for key in ("warning_percent", "cleanup_percent", "stop_writes_percent")
        )
        == (70, 85, 95),
        "storage_thresholds_invalid",
        "UAT 存储阈值必须为 70/85/95",
    )
    budgets = allocation.get("storage_budgets")
    business_bytes = int(budgets.get("business_data_bytes", 0)) if isinstance(budgets, dict) else 0
    expected_budgets = {
        "postgres_and_wal_bytes": 12 * GIB,
        "business_data_bytes": business_bytes,
        "ocr_models_bytes": 4 * GIB,
        "filesystem_and_runtime_bytes": 50 * GIB - 12 * GIB - business_bytes - 4 * GIB,
    }
    _require(
        budgets == expected_budgets,
        "storage_budgets_invalid",
        "UAT 存储预算字段无效",
    )
    _require(
        0 < business_bytes <= 32 * GIB
        and 12 * GIB + business_bytes + 4 * GIB <= 48 * GIB
        and int(budgets["filesystem_and_runtime_bytes"]) >= 2 * GIB,
        "storage_budgets_invalid",
        "UAT 数据预算不得超过48 GiB且运行余量不得低于2 GiB",
    )
    loop_storage = allocation.get("loop_storage")
    _require(
        loop_storage
        == {
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
        "loop_storage_invalid",
        "loop ext4计划与固定边界不一致",
    )
    _require(
        allocation.get("docker_logging")
        == {
            "storage_scope": "shared_docker_root_outside_uat_loop",
            "driver": "json-file",
            "max_size": "10m",
            "max_file": 3,
            "max_container_count": 8,
            "maximum_bytes": 240 * 1024**2,
        },
        "docker_logging_invalid",
        "Docker日志边界必须为8个容器、每个10m×3且位于loop之外",
    )
    filesystem = _find_filesystem(snapshot, storage_root)
    total = int(filesystem.get("total_bytes", 0))
    available = int(filesystem.get("available_bytes", 0))
    inode_total = int(filesystem.get("inode_total", 0))
    inode_available = int(filesystem.get("inode_available", 0))
    reserve = max(200 * GIB, int(total * 0.15))
    _require(
        available - quota >= reserve,
        "storage_capacity_insufficient",
        "分配 UAT 后无法保留共享数据盘安全余量",
    )
    _require(
        inode_total > 0 and inode_available / inode_total >= 0.15,
        "inode_capacity_insufficient",
        "共享数据盘 inode 安全余量不足",
    )

    resources = allocation.get("resources") if isinstance(allocation.get("resources"), dict) else {}
    cpu_limit = resources.get("cpu_limit")
    memory_limit = resources.get("memory_limit_bytes")
    _require(
        isinstance(cpu_limit, int) and cpu_limit == 8,
        "cpu_limit_invalid",
        "UAT CPU 上限必须为 8 vCPU",
    )
    _require(
        isinstance(memory_limit, int) and memory_limit == 16 * GIB,
        "memory_limit_invalid",
        "UAT 内存上限必须为 16 GiB",
    )
    host = snapshot.get("host") if isinstance(snapshot.get("host"), dict) else {}
    _require(
        int(host.get("logical_cpu_count", 0)) - cpu_limit >= 16,
        "cpu_capacity_insufficient",
        "共享宿主机 CPU 安全余量不足",
    )
    _require(
        int(host.get("memory_available_bytes", 0)) - memory_limit >= 32 * GIB,
        "memory_capacity_insufficient",
        "共享宿主机内存安全余量不足",
    )
    load_average = host.get("load_average") if isinstance(host.get("load_average"), dict) else {}
    _require(
        float(load_average.get("fifteen_minutes", cpu_limit + 1))
        <= int(host.get("logical_cpu_count", 0)) * 0.8,
        "host_load_too_high",
        "共享宿主机 15 分钟负载超过预检阈值",
    )

    ingress = allocation.get("ingress") if isinstance(allocation.get("ingress"), dict) else {}
    _require(
        ingress.get("mode") == "http_basic_uat",
        "ingress_invalid",
        "第一阶段必须使用 HTTP 基础 UAT 模式",
    )
    _require(ingress.get("public_access") is False, "ingress_invalid", "第一阶段禁止公网入口")
    _require(ingress.get("shared_nginx_port") == 8077, "ingress_invalid", "共享入口必须使用 8077")
    _require(ingress.get("base_path") == "/smartscan/", "ingress_invalid", "入口基路径无效")
    _require(ingress.get("upstream") == "127.0.0.1:18082", "ingress_invalid", "入口上游无效")
    _require(
        ingress.get("https_required_after_basic_uat") is True,
        "ingress_invalid",
        "基础 UAT 后必须保留 HTTPS 门禁",
    )

    monitoring = (
        allocation.get("monitoring") if isinstance(allocation.get("monitoring"), dict) else {}
    )
    _require(
        monitoring.get("deploy_node_exporter") is False,
        "monitoring_invalid",
        "UAT 禁止部署 Node Exporter",
    )
    _require(
        monitoring.get("deploy_alertmanager") is False,
        "monitoring_invalid",
        "UAT 禁止部署 Alertmanager",
    )
    _require(
        monitoring.get("application_metrics_enabled") is True,
        "monitoring_invalid",
        "UAT 必须保留应用指标",
    )
    monitoring_mode = monitoring.get("mode")
    _require(
        monitoring_mode in {"manual", "existing"},
        "monitoring_invalid",
        "监控模式必须为 manual 或 existing",
    )
    _non_placeholder(monitoring.get("record_reference"), "监控确认记录")
    detected_monitoring = (
        snapshot.get("monitoring") if isinstance(snapshot.get("monitoring"), dict) else {}
    )
    if monitoring_mode == "existing":
        _require(
            all(detected_monitoring.get(name) is True for name in ("prometheus", "grafana")),
            "monitoring_not_detected",
            "现场未同时检测到可复用的 Prometheus 和 Grafana",
        )
    else:
        _require(
            monitoring.get("accepted_capability_gap") is True,
            "monitoring_invalid",
            "人工监控模式必须确认能力缺口",
        )

    backup = allocation.get("backup") if isinstance(allocation.get("backup"), dict) else {}
    _require(
        backup.get("required") is False
        and backup.get("disposable_uat_data") is True
        and backup.get("single_host_risk_acknowledged") is True,
        "backup_invalid",
        "UAT 必须明确无备份、数据可重建及单机风险",
    )

    checks = (
        "snapshot_fresh_and_read_only",
        "shared_server_user_confirmation_complete",
        "fixed_networks_no_overlap",
        "host_ports_available",
        "storage_quota_and_reserve",
        "cpu_memory_headroom",
        "http_basic_uat_boundary_confirmed",
        "monitoring_mode_confirmed",
        "disposable_uat_data_confirmed",
    )
    return PreflightResult(
        environment="uat",
        project_name="smartscan-uat",
        captured_at=captured.isoformat().replace("+00:00", "Z"),
        validated_at=now.isoformat().replace("+00:00", "Z"),
        checks=checks,
        snapshot_sha256=snapshot_sha256,
        allocation_sha256=allocation_sha256,
    )


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    _require(path.is_absolute(), "output_path_invalid", "输出路径必须是绝对路径")
    _require(path.parent.is_dir(), "output_parent_missing", "输出目录必须已存在")
    _require(not path.exists(), "output_exists", "拒绝覆盖已有证据文件")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _require(temporary is not None, "output_failed", "临时证据文件创建失败")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise PreflightError("output_exists", "拒绝覆盖已有证据文件") from exc
        temporary.unlink()
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _canonical_json(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )


def _first_usable_gateway(network: ipaddress.IPv4Network) -> str:
    try:
        return str(next(network.hosts()))
    except StopIteration as exc:  # pragma: no cover - /28 契约已排除此分支
        raise PreflightError("gateway_invalid", "候选网段没有可用网关") from exc


def _bootstrap_networks(spec: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    _require(spec.get("schema_version") == "1.0", "schema_invalid", "引导输入版本无效")
    _require(
        set(spec) == {"schema_version", "networks"},
        "input_invalid",
        "引导输入只允许schema_version和networks",
    )
    values = spec.get("networks")
    _require(
        isinstance(values, dict) and set(values) == REQUIRED_NETWORKS,
        "networks_invalid",
        "引导输入必须精确包含data、edge和egress",
    )
    result: dict[str, dict[str, str]] = {}
    parsed: list[ipaddress.IPv4Network] = []
    for name in sorted(REQUIRED_NETWORKS):
        network = _network(values[name], name)
        _require(network.prefixlen == 28, "cidr_size_invalid", f"{name}必须是/28固定网段")
        parsed.append(network)
        result[name] = {"subnet": str(network), "gateway": _first_usable_gateway(network)}
    for index, network in enumerate(parsed):
        _require(
            not any(network.overlaps(other) for other in parsed[index + 1 :]),
            "requested_network_overlap",
            "三张候选网络相互重叠",
        )
    return result


def _server_address_from_ssh(
    snapshot: Mapping[str, Any], ssh_connection: str
) -> ipaddress.IPv4Address:
    fields = ssh_connection.split()
    _require(len(fields) == 4, "ssh_context_invalid", "缺少可信SSH连接上下文")
    try:
        address = ipaddress.ip_address(fields[2])
    except ValueError as exc:
        raise PreflightError("ssh_context_invalid", "SSH目标地址无效") from exc
    _require(
        isinstance(address, ipaddress.IPv4Address) and address.is_private,
        "ssh_context_invalid",
        "SSH目标必须是私有IPv4地址",
    )
    network = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    host_addresses = {
        str(item.get("address", ""))
        for item in network.get("addresses", [])
        if isinstance(item, dict) and item.get("address")
    }
    _require(str(address) in host_addresses, "ssh_context_invalid", "SSH目标地址不属于当前主机")
    return address


def _reserved_cidrs(snapshot: Mapping[str, Any]) -> list[str]:
    networks = _existing_networks(snapshot) + _route_networks(snapshot)
    values = {
        str(network)
        for network in networks
        if network.is_private
        and not network.is_loopback
        and not network.is_link_local
        and network.prefixlen > 0
    }
    _require(bool(values), "reserved_cidrs_missing", "未取得现场保留网段")
    return sorted(
        values, key=lambda value: (int(ipaddress.ip_network(value).network_address), value)
    )


def build_bootstrap_deployment_input(
    snapshot: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    ssh_connection: str,
    captured_at: str,
) -> dict[str, Any]:
    """从仓库外CIDR与只读现场快照生成不含Secret的部署输入。"""

    address = _server_address_from_ssh(snapshot, ssh_connection)
    return {
        "schema_version": "1.0",
        "target_hostname": EXPECTED_HOSTNAME,
        "shared_entry_origin": f"http://{address}:8077",
        "confirmation": {
            "confirmed_by": "服务器共同使用人 szhzx",
            "confirmed_at": captured_at,
            "change_record": "OPS-001E-UAT仓库外部署输入与证据准备",
            "validation_record": "OPS-001E-现场只读预检、loop与OCR门禁通过",
            "rollback_record": "未安装到/etc；暂存证据的清理必须另行授权",
        },
        "networks": _bootstrap_networks(spec),
        "reserved_cidrs": _reserved_cidrs(snapshot),
        "monitoring_record": "D-085：UAT接受应用健康检查与人工资源检查能力缺口",
    }


def build_uat_allocation(deployment: Mapping[str, Any]) -> dict[str, Any]:
    """生成与受限配置工具1.2契约逐字段一致的资源确认。"""

    networks = deployment["networks"]
    return {
        "schema_version": "1.2",
        "environment": "uat",
        "compose_project_name": "smartscan-uat",
        "target_hostname": EXPECTED_HOSTNAME,
        "confirmation": deployment["confirmation"],
        "networks": networks,
        "reserved_cidrs": deployment["reserved_cidrs"],
        "host_ports": [{"purpose": "UAT Web 回环入口", "port": 18082, "bind_address": "127.0.0.1"}],
        "storage": {
            "root": LOOP_MOUNT_POINT,
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
            "backing_file": LOOP_BACKING_FILE,
            "backing_file_bytes": 50 * GIB,
            "fully_preallocated": True,
            "sparse_file_forbidden": True,
            "filesystem_type": "ext4",
            "reserved_blocks_percent": 0,
            "mount_point": LOOP_MOUNT_POINT,
            "mount_options": ["loop", "nodev", "nosuid", "noatime"],
            "autoclear_required": True,
            "systemd_unit_name": LOOP_UNIT_NAME,
            "systemd_unit_path": LOOP_UNIT_PATH,
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
            "record_reference": deployment["monitoring_record"],
        },
        "backup": {
            "required": False,
            "disposable_uat_data": True,
            "single_host_risk_acknowledged": True,
        },
    }


def _parse_key_value_output(raw: str, label: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    _require(values.get("status") == "passed", "executor_failed", f"{label}未通过")
    return values


def build_loop_evidence(
    verify_output: str,
    findmnt_output: str,
    *,
    captured_at: str,
) -> dict[str, Any]:
    """将已通过的受限loop验证与只读挂载事实转为固定证据。"""

    verified = _parse_key_value_output(verify_output, "loop验证")
    _require(verified.get("action") == "verify", "executor_failed", "loop动作不是verify")
    _require(verified.get("backing_size_bytes") == str(50 * GIB), "loop_invalid", "loop大小无效")
    _require(verified.get("fully_preallocated") == "true", "loop_invalid", "loop不是完整预分配")
    _require(verified.get("filesystem") == "ext4", "loop_invalid", "loop文件系统无效")
    _require(verified.get("label") == "smartscan-uat", "loop_invalid", "loop标签无效")
    _require(verified.get("mount_active") == "true", "loop_invalid", "loop挂载未激活")
    _require(verified.get("autoclear") == "true", "loop_invalid", "loop未启用autoclear")
    _require(
        verified.get("unit_enabled") == "true" and verified.get("unit_active") == "true",
        "loop_invalid",
        "loop systemd单元未启用",
    )
    try:
        mount_document = json.loads(findmnt_output)
        filesystems = mount_document["filesystems"]
        mount = filesystems[0]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise PreflightError("loop_invalid", "findmnt返回无效") from exc
    source = str(mount.get("source", ""))
    _require(re.fullmatch(r"/dev/loop[0-9]+", source) is not None, "loop_invalid", "挂载源不是loop")
    _require(mount.get("target") == LOOP_MOUNT_POINT, "loop_invalid", "loop挂载点无效")
    _require(mount.get("fstype") == "ext4", "loop_invalid", "loop挂载类型无效")
    options = {item for item in str(mount.get("options", "")).split(",") if item}
    _require({"nodev", "nosuid", "noatime"} <= options, "loop_invalid", "loop挂载参数不完整")
    usable_bytes = int(verified.get("usable_bytes", "0"))
    _require(usable_bytes >= 48 * GIB, "loop_invalid", "loop可用空间不足48 GiB")
    return {
        "schema_version": "1.0",
        "captured_at": captured_at,
        "backing_file": {
            "path": LOOP_BACKING_FILE,
            "size_bytes": 50 * GIB,
            "allocated_bytes": 50 * GIB,
            "sparse": False,
            "mode": "0600",
        },
        "filesystem": {
            "type": "ext4",
            "label": "smartscan-uat",
            "reserved_blocks_percent": 0,
            "usable_bytes": usable_bytes,
        },
        "mount": {
            "active": True,
            "source": source,
            "target": LOOP_MOUNT_POINT,
            "type": "ext4",
            "options": sorted(options | {"loop"}),
        },
        "loop": {"backing_file": LOOP_BACKING_FILE, "autoclear": True},
        "systemd_unit": {
            "name": LOOP_UNIT_NAME,
            "path": LOOP_UNIT_PATH,
            "mode": "0644",
            "enabled": True,
            "active": True,
            "requires_mounts_for": "/mnt/data",
            "rollback_record": "OPS-001B受限执行器stop仅在单独授权后执行并保留后备文件",
        },
        "contains_sensitive_data": False,
    }


def _inspect_nginx_configuration(main_path: Path = Path("/etc/nginx/nginx.conf")) -> None:
    queue = [main_path]
    seen: set[Path] = set()
    texts: list[str] = []
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise PreflightError("nginx_config_unreadable", "Nginx include不可读") from exc
        texts.append(text)
        for raw in re.findall(r"(?m)^\s*include\s+([^;]+);", text):
            candidate = raw.strip().strip("\"'")
            if not candidate.startswith("/"):
                candidate = str(path.parent / candidate)
            queue.extend(Path(item) for item in sorted(glob.glob(candidate)))
    combined = "\n".join(texts)
    _require(
        bool(re.search(r"(?m)^\s*listen\s+[^;]*\b8077\b[^;]*;", combined)),
        "nginx_8077_missing",
        "共享Nginx没有8077入口",
    )
    locations = re.findall(r"(?m)^\s*location\s+([^\s{]+)", combined)
    _require(
        not any(value.casefold().startswith("/smartscan") for value in locations),
        "nginx_path_conflict",
        "共享Nginx已存在SmartScan路径",
    )
    _require("127.0.0.1:18082" not in combined, "nginx_upstream_conflict", "18082已被Nginx引用")


def _validate_ocr_outputs(verify_output: str, status_output: str) -> None:
    try:
        verified = json.loads(verify_output)
        status = json.loads(status_output)
    except json.JSONDecodeError as exc:
        raise PreflightError("ocr_invalid", "OCR受限执行器返回无效") from exc
    _require(verified.get("status") == "passed", "ocr_invalid", "OCR模型验证未通过")
    _require(
        status.get("installed") is True and status.get("status") == "passed",
        "ocr_invalid",
        "OCR模型未安装",
    )
    _require(
        verified.get("artifact_version") == "PP-OCRv6-small-v1"
        and status.get("artifact_version") == "PP-OCRv6-small-v1",
        "ocr_invalid",
        "OCR模型版本无效",
    )


def _validate_shared_runtime_health(snapshot: Mapping[str, Any]) -> None:
    network = snapshot.get("network") if isinstance(snapshot.get("network"), dict) else {}
    listeners = network.get("listeners", [])
    _require(
        any(isinstance(item, dict) and item.get("port") == 8077 for item in listeners),
        "nginx_8077_missing",
        "共享Nginx没有监听8077",
    )
    docker = snapshot.get("docker") if isinstance(snapshot.get("docker"), dict) else {}
    containers = docker.get("containers", [])
    for item in containers:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state", "")).casefold()
        status = str(item.get("status", "")).casefold()
        _require(
            state != "restarting" and "restarting" not in status,
            "container_unhealthy",
            "存在重启中的共租户容器",
        )
        _require("unhealthy" not in status, "container_unhealthy", "存在不健康的共租户容器")


def _validate_bootstrap_file(path: Path, *, expected_uid: int) -> tuple[int, str]:
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode), "output_invalid", "证据不是普通文件")
    _require(not path.is_symlink() and info.st_nlink == 1, "output_invalid", "证据链接状态无效")
    _require(info.st_uid == expected_uid, "output_invalid", "证据所有者无效")
    _require(stat.S_IMODE(info.st_mode) == 0o600, "output_invalid", "证据权限必须为0600")
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _generator_sha256() -> str:
    injected = globals().get("__generator_sha256__")
    if isinstance(injected, str) and re.fullmatch(r"[0-9a-f]{64}", injected):
        return injected
    source = Path(__file__)
    _require(source.is_file(), "generator_identity_missing", "无法确认生成器摘要")
    return hashlib.sha256(source.read_bytes()).hexdigest()


def _prepare_output_root(path: Path, *, expected_uid: int) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    info = path.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "output_invalid", "暂存根不是普通目录"
    )
    _require(info.st_uid == expected_uid, "output_invalid", "暂存根所有者无效")
    _require(stat.S_IMODE(info.st_mode) == 0o700, "output_invalid", "暂存根权限必须为0700")
    _require(not any(path.iterdir()), "output_exists", "暂存根必须为空")
    for name in BOOTSTRAP_FILENAMES:
        _require(not (path / name).exists(), "output_exists", "拒绝覆盖已有引导证据")


def _write_bootstrap_documents(path: Path, documents: Mapping[str, Mapping[str, Any]]) -> None:
    """以同目录临时文件和硬链接提交三份证据，失败时不留下部分结果。"""

    _require(set(documents) == set(BOOTSTRAP_FILENAMES), "output_invalid", "证据文件集合无效")
    temporary: list[Path] = []
    published: list[Path] = []
    try:
        for name in BOOTSTRAP_FILENAMES:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path,
                prefix=f".{name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp = Path(handle.name)
                temporary.append(temp)
                handle.write(_canonical_json(documents[name]))
                handle.flush()
                os.fsync(handle.fileno())
            temp.chmod(0o600)
        for name, temp in zip(BOOTSTRAP_FILENAMES, temporary, strict=True):
            target = path / name
            try:
                os.link(temp, target)
            except FileExistsError as exc:
                raise PreflightError("output_exists", "拒绝覆盖已有引导证据") from exc
            published.append(target)
        for temp in temporary:
            temp.unlink()
        temporary.clear()
    except BaseException:
        for target in published:
            target.unlink(missing_ok=True)
        for temp in temporary:
            temp.unlink(missing_ok=True)
        raise


def prepare_bootstrap_command(args: argparse.Namespace) -> int:
    _require(sys.platform.startswith("linux"), "platform_invalid", "引导证据只允许在Linux生成")
    _require(pwd is not None, "platform_invalid", "缺少Linux用户数据库")
    uid = os.getuid()
    _require(socket.gethostname() == EXPECTED_HOSTNAME, "hostname_mismatch", "目标主机不匹配")
    _require(
        pwd.getpwuid(uid).pw_name == EXPECTED_USER and uid == 1000, "user_mismatch", "执行用户无效"
    )
    try:
        spec = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise PreflightError("input_invalid", "标准输入不是有效引导JSON") from exc
    _require(isinstance(spec, dict), "input_invalid", "引导输入根节点必须是对象")
    now = datetime.now(UTC)
    captured_at = now.isoformat().replace("+00:00", "Z")
    snapshot = build_snapshot(now=now)
    deployment = build_bootstrap_deployment_input(
        snapshot,
        spec,
        ssh_connection=os.environ.get("SSH_CONNECTION", ""),
        captured_at=captured_at,
    )
    allocation = build_uat_allocation(deployment)
    allocation_raw = _canonical_json(allocation)
    snapshot_raw = _canonical_json(snapshot)
    result = validate_preflight(
        snapshot,
        allocation,
        snapshot_sha256=hashlib.sha256(snapshot_raw).hexdigest(),
        allocation_sha256=hashlib.sha256(allocation_raw).hexdigest(),
        now=now,
    )
    _validate_shared_runtime_health(snapshot)
    _inspect_nginx_configuration()
    loop_output = _run_command(("sudo", "-n", LOOP_EXECUTOR, "verify"))
    findmnt_output = _run_command(
        ("findmnt", "-J", "-T", LOOP_MOUNT_POINT, "-o", "SOURCE,TARGET,FSTYPE,OPTIONS")
    )
    loop_evidence = build_loop_evidence(loop_output, findmnt_output, captured_at=captured_at)
    ocr_verify = _run_command(("sudo", "-n", OCR_EXECUTOR, "verify"))
    ocr_status = _run_command(("sudo", "-n", OCR_EXECUTOR, "status"))
    _validate_ocr_outputs(ocr_verify, ocr_status)
    preflight = result.safe_summary()
    preflight["checks"] = list(preflight["checks"]) + [
        "shared_nginx_8077_no_smartscan_conflict",
        "loop_storage_verified",
        "ocr_model_verified",
    ]
    preflight["contains_sensitive_data"] = False
    preflight["generator_sha256"] = _generator_sha256()
    documents = {
        "deployment-input.json": deployment,
        "preflight-summary.json": preflight,
        "loop-storage-evidence.json": loop_evidence,
    }
    _prepare_output_root(BOOTSTRAP_ROOT, expected_uid=uid)
    _write_bootstrap_documents(BOOTSTRAP_ROOT, documents)
    summaries = []
    for name in BOOTSTRAP_FILENAMES:
        size, digest = _validate_bootstrap_file(BOOTSTRAP_ROOT / name, expected_uid=uid)
        summaries.append({"name": name, "size_bytes": size, "sha256": digest, "mode": "0600"})
    print(
        json.dumps(
            {
                "status": "prepared",
                "root": str(BOOTSTRAP_ROOT),
                "generator_sha256": preflight["generator_sha256"],
                "files": summaries,
                "contains_sensitive_data": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def collect_command(args: argparse.Namespace) -> int:
    _require(sys.platform.startswith("linux"), "platform_invalid", "现场采集只允许在 Linux 执行")
    snapshot = build_snapshot()
    _write_new_json(args.output.resolve(), snapshot)
    print(json.dumps({"status": "collected", "output": str(args.output), "secrets": False}))
    return 0


def validate_command(args: argparse.Namespace) -> int:
    snapshot, snapshot_hash = _read_json_file(args.snapshot, "现场快照")
    allocation, allocation_hash = _read_json_file(args.allocation, "资源分配")
    result = validate_preflight(
        snapshot,
        allocation,
        snapshot_sha256=snapshot_hash,
        allocation_sha256=allocation_hash,
        max_age_hours=args.max_age_hours,
    )
    summary = result.safe_summary()
    if args.evidence:
        _write_new_json(args.evidence.resolve(), summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartScan 共享宿主机只读预检")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="在目标 Linux 主机执行固定只读命令")
    collect.add_argument("--output", type=Path, required=True, help="新的绝对 JSON 输出路径")
    collect.set_defaults(handler=collect_command)
    validate = subparsers.add_parser("validate", help="离线验证快照和批准的资源分配")
    validate.add_argument("--snapshot", type=Path, required=True)
    validate.add_argument("--allocation", type=Path, required=True)
    validate.add_argument("--evidence", type=Path)
    validate.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS)
    validate.set_defaults(handler=validate_command)
    prepare = subparsers.add_parser(
        "prepare-bootstrap",
        help="在目标主机从标准输入CIDR与只读现场事实生成三份固定仓库外证据",
    )
    prepare.set_defaults(handler=prepare_bootstrap_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except PreflightError as exc:
        print(
            json.dumps(
                {"status": "failed", "code": exc.code, "message": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
