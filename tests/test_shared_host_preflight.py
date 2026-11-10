from __future__ import annotations

import ipaddress
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.shared_host_preflight import (
    GIB,
    PreflightError,
    _write_new_json,
    build_snapshot,
    validate_preflight,
)

NOW = datetime(2026, 11, 10, 4, 0, tzinfo=UTC)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOCATION_EXAMPLE = PROJECT_ROOT / "deploy" / "compose" / "shared-host-allocation.example.json"


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], str]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: tuple[str, ...]) -> str:
        self.calls.append(args)
        return self.responses[args]


def collection_runner() -> FakeRunner:
    network_list = ("docker", "network", "ls", "--no-trunc", "--format", "{{json .}}")
    network_inspect = ("docker", "network", "inspect", "net1")
    return FakeRunner(
        {
            network_list: json.dumps({"ID": "net1", "Name": "existing"}) + "\n",
            network_inspect: json.dumps(
                [
                    {
                        "Id": "net1",
                        "Name": "existing",
                        "Driver": "bridge",
                        "Internal": False,
                        "Labels": {"secret-looking-label": "must-not-be-collected"},
                        "Containers": {"container-id": {"IPv4Address": "172.20.0.2/16"}},
                        "IPAM": {
                            "Config": [
                                {
                                    "Subnet": "172.20.0.0/16",
                                    "Gateway": "172.20.0.1",
                                }
                            ]
                        },
                    }
                ]
            ),
            ("docker", "version", "--format", "{{json .Server}}"): json.dumps(
                {
                    "Version": "29.0.2",
                    "ApiVersion": "1.52",
                    "Components": [{"Details": {"secret": "discarded"}}],
                }
            ),
            ("docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"): "\n".join(
                (
                    json.dumps(
                        {
                            "ID": "abc",
                            "Names": "prometheus",
                            "Image": "prom/prometheus:v3",
                            "State": "running",
                            "Ports": "127.0.0.1:19090->9090/tcp",
                            "Networks": "monitoring",
                            "Mounts": "/secret",
                        }
                    ),
                    json.dumps(
                        {
                            "ID": "def",
                            "Names": "grafana",
                            "Image": "grafana/grafana:latest",
                            "State": "running",
                            "Ports": "0.0.0.0:3000->3000/tcp",
                            "Networks": "monitoring",
                        }
                    ),
                    json.dumps(
                        {
                            "ID": "ghi",
                            "Names": "alertmanager",
                            "Image": "prom/alertmanager:v1",
                            "State": "running",
                            "Ports": "",
                            "Networks": "monitoring",
                        }
                    ),
                )
            ),
            (
                "df",
                "-B1",
                "-P",
                "-T",
                "--output=source,fstype,size,used,avail,pcent,target",
                "/",
                "/mnt/data",
            ): (
                "Filesystem Type 1B-blocks Used Available Use% Mounted on\n"
                "/dev/root ext4 900000000000 650000000000 250000000000 73% /\n"
                "/dev/data xfs 4000000000000 2400000000000 1600000000000 60% /mnt/data\n"
            ),
            (
                "df",
                "-P",
                "-i",
                "--output=itotal,iused,iavail,ipcent,target",
                "/",
                "/mnt/data",
            ): (
                "Inodes IUsed IFree IUse% Mounted on\n"
                "1000000 100000 900000 10% /\n"
                "4000000 1000000 3000000 25% /mnt/data\n"
            ),
            ("ip", "-j", "-4", "route", "show", "table", "all"): json.dumps(
                [
                    {"dst": "default", "gateway": "10.0.0.1", "dev": "eth0"},
                    {"dst": "10.0.0.0/8", "dev": "eth0", "table": "main"},
                ]
            ),
            ("ip", "-j", "-6", "route", "show", "table", "all"): "[]",
            ("ip", "-j", "rule", "show"): json.dumps(
                [{"priority": 0, "from": "all", "table": "local"}]
            ),
            ("ip", "-j", "address", "show"): json.dumps(
                [
                    {
                        "ifname": "lo",
                        "addr_info": [
                            {
                                "family": "inet",
                                "local": "127.0.0.1",
                                "prefixlen": 8,
                                "scope": "host",
                            }
                        ],
                    },
                    {
                        "ifname": "eth0",
                        "addr_info": [
                            {
                                "family": "inet",
                                "local": "10.8.0.150",
                                "prefixlen": 24,
                                "scope": "global",
                            }
                        ],
                    },
                ]
            ),
            ("ss", "-H", "-lntu"): (
                "tcp LISTEN 0 4096 127.0.0.1:5432 0.0.0.0:*\nudp UNCONN 0 0 0.0.0.0:68 0.0.0.0:*\n"
            ),
            ("docker", "compose", "version", "--short"): "2.40.3\n",
        }
    )


def valid_snapshot() -> dict[str, object]:
    runner = collection_runner()
    return build_snapshot(
        runner=runner,
        now=NOW,
        hostname="ctiecaiserver",
        os_release={"id": "ubuntu", "version_id": "24.04"},
        memory=(503 * GIB, 349 * GIB),
        logical_cpu_count=128,
        load_average=(8.0, 10.0, 12.0),
    )


def valid_allocation() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "environment": "uat",
        "compose_project_name": "smartscan-uat",
        "target_hostname": "ctiecaiserver",
        "approval": {
            "approved_by": "公司运维负责人",
            "approved_at": "2026-11-10T03:00:00Z",
            "change_ticket": "OPS-2026-11010",
        },
        "networks": {
            "data": {"subnet": "172.30.0.0/28", "gateway": "172.30.0.1"},
            "edge": {"subnet": "172.30.0.16/28", "gateway": "172.30.0.17"},
            "egress": {"subnet": "172.30.0.32/28", "gateway": "172.30.0.33"},
        },
        "reserved_cidrs": ["192.168.53.0/24", "192.168.0.0/16"],
        "host_ports": [
            {"purpose": "UAT Web 回环入口", "port": 18081, "bind_address": "127.0.0.1"},
            {"purpose": "内部指标入口", "port": 19081, "bind_address": "127.0.0.1"},
        ],
        "storage": {
            "root": "/mnt/data/smartscan/uat",
            "quota_bytes": 100 * GIB,
            "hard_limit_confirmed": True,
        },
        "resources": {"cpu_limit": 8, "memory_limit_bytes": 16 * GIB},
        "ingress": {
            "internal_https": True,
            "public_access": False,
            "hostname": "smartscan-uat.intra.company",
        },
        "monitoring": {
            "reuse_existing": True,
            "deploy_node_exporter": False,
            "metrics_target_reference": "MONITORING-2026-18",
        },
        "backup": {"off_host": True, "endpoint_reference": "BACKUP-2026-09"},
    }


def validate(snapshot: dict[str, object], allocation: dict[str, object]):
    return validate_preflight(
        snapshot,
        allocation,
        snapshot_sha256="a" * 64,
        allocation_sha256="b" * 64,
        now=NOW,
    )


def test_collector_uses_only_fixed_read_only_commands_and_drops_sensitive_fields() -> None:
    runner = collection_runner()

    snapshot = build_snapshot(
        runner=runner,
        now=NOW,
        hostname="ctiecaiserver",
        os_release={"id": "ubuntu", "version_id": "24.04"},
        memory=(503 * GIB, 349 * GIB),
        logical_cpu_count=128,
        load_average=(8.0, 10.0, 12.0),
    )

    rendered = json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["collector"]["read_only_commands"] is True
    assert snapshot["collector"]["secrets_collected"] is False
    assert snapshot["monitoring"]["prometheus"] is True
    assert snapshot["monitoring"]["grafana"] is True
    assert snapshot["monitoring"]["alertmanager"] is True
    assert snapshot["network"]["listeners"][0]["port"] == 5432
    assert snapshot["host"]["filesystems"][1]["inode_available"] == 3_000_000
    assert "secret-looking-label" not in rendered
    assert "must-not-be-collected" not in rendered
    assert '"Mounts"' not in rendered
    assert not any(
        "inspect" in call and call[:2] == ("docker", "container") for call in runner.calls
    )


def test_valid_approved_allocation_returns_only_safe_evidence() -> None:
    result = validate(valid_snapshot(), valid_allocation())

    summary = result.safe_summary()
    rendered = json.dumps(summary, ensure_ascii=False)
    assert summary["status"] == "passed"
    assert summary["project_name"] == "smartscan-uat"
    assert len(summary["checks"]) == 9
    assert summary["contains_network_details"] is False
    assert "172.30" not in rendered
    assert "smartscan-uat.intra.company" not in rendered


def test_committed_allocation_example_is_non_executable_and_contains_no_secret_fields() -> None:
    example = json.loads(ALLOCATION_EXAMPLE.read_text(encoding="utf-8"))
    rendered = json.dumps(example, ensure_ascii=False).casefold()

    assert "replace_with" in rendered
    assert "password" not in rendered
    assert "token" not in rendered
    assert "private_key" not in rendered
    with pytest.raises(PreflightError, match="占位值"):
        validate(valid_snapshot(), example)


def test_snapshot_must_be_fresh_and_from_expected_host() -> None:
    snapshot = valid_snapshot()
    snapshot["captured_at"] = (NOW - timedelta(hours=25)).isoformat()
    with pytest.raises(PreflightError, match="超过 24 小时") as stale:
        validate(snapshot, valid_allocation())
    assert stale.value.code == "snapshot_stale"

    snapshot = valid_snapshot()
    snapshot["hostname"] = "another-host"
    with pytest.raises(PreflightError, match="主机不匹配"):
        validate(snapshot, valid_allocation())

    snapshot = valid_snapshot()
    snapshot["collector"]["container_mounts_collected"] = True
    with pytest.raises(PreflightError, match="挂载"):
        validate(snapshot, valid_allocation())


@pytest.mark.parametrize(
    ("network_name", "subnet", "message"),
    [
        ("data", "172.20.10.0/24", "现场网络"),
        ("data", "10.20.0.0/24", "现场网络"),
        ("data", "192.168.53.0/28", "现场网络"),
        ("data", "192.168.60.0/24", "现场网络"),
        ("edge", "172.30.0.0/28", "网段重叠"),
    ],
)
def test_networks_reject_docker_route_reserved_and_requested_overlap(
    network_name: str, subnet: str, message: str
) -> None:
    allocation = valid_allocation()
    allocation["networks"][network_name]["subnet"] = subnet
    allocation["networks"][network_name]["gateway"] = str(
        next(ipaddress.ip_network(subnet).hosts())
    )

    with pytest.raises(PreflightError, match=message):
        validate(valid_snapshot(), allocation)


@pytest.mark.parametrize(
    ("port", "address", "message"),
    [
        (5432, "127.0.0.1", "端口已被占用"),
        (19090, "127.0.0.1", "端口已被占用"),
        (443, "127.0.0.1", "端口无效|80/443"),
        (18081, "0.0.0.0", "禁止绑定所有接口"),
        (18081, "10.8.0.151", "不属于目标宿主机"),
    ],
)
def test_ports_reject_listener_container_privileged_and_wildcard_bind(
    port: int, address: str, message: str
) -> None:
    allocation = valid_allocation()
    allocation["host_ports"][0]["port"] = port
    allocation["host_ports"][0]["bind_address"] = address

    with pytest.raises(PreflightError, match=message):
        validate(valid_snapshot(), allocation)


def test_storage_requires_exact_root_hard_limit_and_shared_disk_reserve() -> None:
    allocation = valid_allocation()
    allocation["storage"]["root"] = "/srv/smartscan/uat"
    with pytest.raises(PreflightError, match="/mnt/data/smartscan/uat"):
        validate(valid_snapshot(), allocation)

    allocation = valid_allocation()
    allocation["storage"]["hard_limit_confirmed"] = False
    with pytest.raises(PreflightError, match="硬限制"):
        validate(valid_snapshot(), allocation)

    snapshot = valid_snapshot()
    snapshot["host"]["filesystems"][1]["available_bytes"] = 250 * GIB
    with pytest.raises(PreflightError, match="安全余量"):
        validate(snapshot, valid_allocation())

    snapshot = valid_snapshot()
    snapshot["host"]["filesystems"][1]["inode_available"] = 100
    with pytest.raises(PreflightError, match="inode"):
        validate(snapshot, valid_allocation())


def test_resources_leave_host_safety_margin() -> None:
    snapshot = valid_snapshot()
    snapshot["host"]["logical_cpu_count"] = 20
    with pytest.raises(PreflightError, match="CPU 安全余量"):
        validate(snapshot, valid_allocation())

    snapshot = valid_snapshot()
    snapshot["host"]["memory_available_bytes"] = 40 * GIB
    with pytest.raises(PreflightError, match="内存安全余量"):
        validate(snapshot, valid_allocation())

    snapshot = valid_snapshot()
    snapshot["host"]["load_average"]["fifteen_minutes"] = 120.0
    with pytest.raises(PreflightError, match="15 分钟负载"):
        validate(snapshot, valid_allocation())


def test_approval_ingress_monitoring_and_backup_fail_closed() -> None:
    allocation = valid_allocation()
    allocation["approval"]["change_ticket"] = "REPLACE-ME"
    with pytest.raises(PreflightError, match="占位值"):
        validate(valid_snapshot(), allocation)

    allocation = valid_allocation()
    allocation["ingress"]["public_access"] = True
    with pytest.raises(PreflightError, match="禁止公网入口"):
        validate(valid_snapshot(), allocation)

    allocation = valid_allocation()
    allocation["monitoring"]["deploy_node_exporter"] = True
    with pytest.raises(PreflightError, match="Node Exporter"):
        validate(valid_snapshot(), allocation)

    snapshot = valid_snapshot()
    snapshot["monitoring"]["alertmanager"] = False
    with pytest.raises(PreflightError, match="Alertmanager"):
        validate(snapshot, valid_allocation())

    runner = collection_runner()
    container_command = ("docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}")
    runner.responses[container_command] = runner.responses[container_command].replace(
        '"State": "running", "Ports": "", "Networks": "monitoring"',
        '"State": "exited", "Ports": "", "Networks": "monitoring"',
    )
    snapshot = build_snapshot(
        runner=runner,
        now=NOW,
        hostname="ctiecaiserver",
        os_release={"id": "ubuntu", "version_id": "24.04"},
        memory=(503 * GIB, 349 * GIB),
        logical_cpu_count=128,
        load_average=(8.0, 10.0, 12.0),
    )
    with pytest.raises(PreflightError, match="Alertmanager"):
        validate(snapshot, valid_allocation())

    allocation = valid_allocation()
    allocation["backup"]["off_host"] = False
    with pytest.raises(PreflightError, match="异机"):
        validate(valid_snapshot(), allocation)


def test_evidence_writer_is_0600_and_refuses_overwrite(tmp_path: Path) -> None:
    output = (tmp_path / "evidence.json").resolve()

    _write_new_json(output, {"status": "passed", "contains_secrets": False})

    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"
    if os.name != "nt":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(PreflightError, match="覆盖"):
        _write_new_json(output, {"status": "changed"})
