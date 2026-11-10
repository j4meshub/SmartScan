"""采集并离线验证 SmartScan 共享宿主机只读预检证据。"""

from __future__ import annotations

import argparse
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

SCHEMA_VERSION = "1.0"
GIB = 1024**3
DEFAULT_MAX_AGE_HOURS = 24
REQUIRED_NETWORKS = frozenset({"data", "edge", "egress"})
FORBIDDEN_HOST_PORTS = frozenset({80, 443})
PLACEHOLDER_WORDS = ("replace", "example", "placeholder", "change-me", "待填写", "待确认")
SAFE_BIND_ADDRESSES = frozenset({"127.0.0.1", "::1"})
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
        networks.append(
            {
                "id": str(item.get("Id", "")),
                "name": str(item.get("Name", "")),
                "driver": str(item.get("Driver", "")),
                "internal": bool(item.get("Internal", False)),
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
                "-P",
                "-T",
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
                "-P",
                "-i",
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
        allocation.get("schema_version") == SCHEMA_VERSION,
        "schema_invalid",
        "资源分配版本不匹配",
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

    approval = allocation.get("approval") if isinstance(allocation.get("approval"), dict) else {}
    _non_placeholder(approval.get("approved_by"), "批准人")
    _non_placeholder(approval.get("change_ticket"), "变更单")
    approved_at = _parse_time(approval.get("approved_at"), "approved_at")
    _require(approved_at <= now + timedelta(minutes=5), "approval_invalid", "批准时间来自未来")

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
        _non_placeholder(item.get("purpose"), "端口用途")
        seen_ports.add(port)

    storage = allocation.get("storage") if isinstance(allocation.get("storage"), dict) else {}
    storage_root = PurePosixPath(str(storage.get("root", "")))
    _require(
        storage_root == PurePosixPath("/mnt/data/smartscan/uat"),
        "storage_root_invalid",
        "UAT 数据根必须为 /mnt/data/smartscan/uat",
    )
    quota = storage.get("quota_bytes")
    _require(isinstance(quota, int) and quota >= 100 * GIB, "storage_quota_invalid", "UAT 配额不足")
    _require(storage.get("hard_limit_confirmed") is True, "storage_limit_missing", "未确认硬限制")
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
    _require(isinstance(cpu_limit, int) and cpu_limit >= 8, "cpu_limit_invalid", "UAT CPU 上限不足")
    _require(
        isinstance(memory_limit, int) and memory_limit >= 16 * GIB,
        "memory_limit_invalid",
        "UAT 内存上限不足",
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
    _require(ingress.get("internal_https") is True, "ingress_invalid", "必须使用内部 HTTPS")
    _require(ingress.get("public_access") is False, "ingress_invalid", "第一阶段禁止公网入口")
    _non_placeholder(ingress.get("hostname"), "内部 HTTPS 域名")

    monitoring = (
        allocation.get("monitoring") if isinstance(allocation.get("monitoring"), dict) else {}
    )
    _require(monitoring.get("reuse_existing") is True, "monitoring_invalid", "必须复用现有监控")
    _require(
        monitoring.get("deploy_node_exporter") is False,
        "monitoring_invalid",
        "禁止重复部署 Node Exporter",
    )
    _non_placeholder(monitoring.get("metrics_target_reference"), "监控接入引用")
    detected_monitoring = (
        snapshot.get("monitoring") if isinstance(snapshot.get("monitoring"), dict) else {}
    )
    _require(
        all(
            detected_monitoring.get(name) is True
            for name in ("prometheus", "grafana", "alertmanager")
        ),
        "monitoring_not_detected",
        "现场未同时检测到现有 Prometheus、Grafana 和 Alertmanager",
    )

    backup = allocation.get("backup") if isinstance(allocation.get("backup"), dict) else {}
    _require(backup.get("off_host") is True, "backup_invalid", "备份必须位于异机或对象存储")
    _non_placeholder(backup.get("endpoint_reference"), "异机备份端点引用")

    checks = (
        "snapshot_fresh_and_read_only",
        "approval_complete",
        "fixed_networks_no_overlap",
        "host_ports_available",
        "storage_quota_and_reserve",
        "cpu_memory_headroom",
        "internal_https_only",
        "existing_monitoring_reused",
        "off_host_backup_confirmed",
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
