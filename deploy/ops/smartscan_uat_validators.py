#!/usr/bin/env python3
"""SmartScan UAT 统一控制器的内聚、只读验证模块。

本模块只验证固定对象，不创建、修复、格式化、挂载、安装、轮换或删除任何内容。
验证结果以 Python 结构体传递，不通过旧执行器 stdout 建立状态机事实。
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

GIB = 1024**3
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ENV_BYTES = 256 * 1024
BACKING_BYTES = 50 * GIB
MINIMUM_USABLE_BYTES = 48 * GIB
MINIMUM_HOST_RESERVE_BYTES = 200 * GIB
EXPECTED_MODEL_VERSION = "PP-OCRv6-small-v1"
EXPECTED_MODEL_FILES = {
    f"{directory}/{name}"
    for directory in ("PP-OCRv6_small_det", "PP-OCRv6_small_rec")
    for name in ("inference.json", "inference.pdiparams", "inference.yml")
}
EXPECTED_EVIDENCE_FILES = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM_MODEL_DESCRIPTION.md",
    "source-lock.json",
}
ACCEPTED_IMAGES = {
    "SMARTSCAN_UAT_POSTGRES_IMAGE": "ghcr.io/j4meshub/smartscan-postgres@sha256:94758173bbe1975014751a2e2855a22e0e554e8df996e4d6303bcf386cdae6d0",
    "SMARTSCAN_UAT_API_IMAGE": "ghcr.io/j4meshub/smartscan-api@sha256:80aea0a272791ea44d76895dbd825d091620e0f43ad76c32f32fb6ba97c646d0",
    "SMARTSCAN_UAT_WORKER_IMAGE": "ghcr.io/j4meshub/smartscan-worker@sha256:f1cb15e434e99fdced69885667e8646346c75bc293e8ecf9f6b0fa24951768a6",
    "SMARTSCAN_UAT_AI_GATEWAY_IMAGE": "ghcr.io/j4meshub/smartscan-ai-gateway@sha256:1813ada8bda225530d71e5afa9e1c3fd640d5e23d05000d370fdccad0e5e8b00",
    "SMARTSCAN_UAT_WEB_IMAGE": "ghcr.io/j4meshub/smartscan-web@sha256:3d701a4bcaf24c03ead231f10abd316ba83ab89a6984894dfe31af404d3c930c",
    "SMARTSCAN_UAT_OPS_IMAGE": "ghcr.io/j4meshub/smartscan-ops@sha256:be6c50fbdbc9404a9d9589a53799dbc6084470a63f2306ec6bee5736adf94cae",
}
SECRET_FIELDS = {
    "POSTGRES_PASSWORD",
    "SMARTSCAN_DATABASE_URL",
    "SMARTSCAN_SECRET_KEY",
    "SMARTSCAN_PHONE_HMAC_PEPPERS",
    "SMARTSCAN_PHONE_ENCRYPTION_KEYS",
    "SMARTSCAN_SUPERADMIN_PASSWORD",
    "SMARTSCAN_OPS_METRICS_TOKEN",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UNIT_SHA256 = "e48feb8db96f5fe42b21249846e12a2165b639504afdf99ded882e28eeedd5a3"


class ValidationError(RuntimeError):
    """固定对象不满足只读验证契约。"""


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason_code: str
    evidence_summary: dict[str, Any]
    next_state: str

    @classmethod
    def success(cls, *, evidence: dict[str, Any], next_state: str) -> ValidationResult:
        return cls(True, "passed", evidence, next_state)


@dataclass(frozen=True)
class StorageSpec:
    backing_bytes: int = BACKING_BYTES
    minimum_usable_bytes: int = MINIMUM_USABLE_BYTES
    minimum_host_reserve_bytes: int = MINIMUM_HOST_RESERVE_BYTES
    minimum_host_reserve_percent: int = 15
    filesystem_label: str = "smartscan-uat"
    unit_name: str = "mnt-data-smartscan-uat.mount"
    unit_sha256: str = UNIT_SHA256


@dataclass(frozen=True)
class Paths:
    config_root: Path = Path("/etc/smartscan/uat")
    data_mount: Path = Path("/mnt/data")
    backing_file: Path = Path("/mnt/data/smartscan-loop/uat.ext4")
    mount_point: Path = Path("/mnt/data/smartscan/uat")
    unit_path: Path = Path("/etc/systemd/system/mnt-data-smartscan-uat.mount")
    model_root: Path = Path("/mnt/data/smartscan/uat/models/ocr")
    deployment_input: Path = Path("/etc/smartscan/uat/deployment-input.json")
    preflight_summary: Path = Path("/etc/smartscan/uat/preflight-summary.json")
    loop_evidence: Path = Path("/etc/smartscan/uat/loop-storage-evidence.json")
    deploy_env: Path = Path("/etc/smartscan/uat/deploy.env")
    runtime_env: Path = Path("/etc/smartscan/uat/runtime.env")
    allocation: Path = Path("/etc/smartscan/uat/shared-host-allocation.json")
    bootstrap_password: Path = Path("/etc/smartscan/uat/bootstrap-admin-password")


class Runner(Protocol):
    def run(
        self,
        arguments: list[str],
        *,
        check: bool = True,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> str: ...


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValidationError(reason)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("json_duplicate_key")
        result[key] = value
    return result


def _strict_json_bytes(
    raw: bytes, reason: str, *, maximum_bytes: int = MAX_JSON_BYTES
) -> dict[str, Any]:
    _require(len(raw) <= maximum_bytes, f"{reason}:too_large")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{reason}:non_utf8") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{reason}:invalid_json") from exc
    _require(isinstance(value, dict), f"{reason}:root_not_object")
    return value


def _regular_file(
    path: Path,
    reason: str,
    *,
    uid: int | None = None,
    gid: int | None = None,
    mode: int | None = None,
) -> os.stat_result:
    _require(path.exists() and path.is_file() and not path.is_symlink(), f"{reason}:type")
    info = path.stat(follow_symlinks=False)
    _require(info.st_nlink == 1, f"{reason}:hardlink")
    if os.name != "nt":
        if uid is not None:
            _require(info.st_uid == uid, f"{reason}:owner")
        if gid is not None:
            _require(info.st_gid == gid, f"{reason}:group")
        if mode is not None:
            _require(stat.S_IMODE(info.st_mode) == mode, f"{reason}:mode")
    return info


def _strict_json_file(
    path: Path,
    reason: str,
    *,
    uid: int | None = None,
    gid: int | None = None,
    mode: int = 0o600,
    maximum_bytes: int = MAX_JSON_BYTES,
) -> tuple[dict[str, Any], bytes]:
    _regular_file(path, reason, uid=uid, gid=gid, mode=mode)
    raw = path.read_bytes()
    return _strict_json_bytes(raw, reason, maximum_bytes=maximum_bytes), raw


def _exact_int(value: Any, reason: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), reason)
    return value


def _parse_positive_int(value: str, reason: str) -> int:
    _require(re.fullmatch(r"[0-9]+", value) is not None, reason)
    return int(value)


def _parse_env(path: Path, *, uid: int, gid: int) -> dict[str, str]:
    _regular_file(path, f"env_invalid:{path.name}", uid=uid, gid=gid, mode=0o600)
    raw = path.read_bytes()
    _require(len(raw) <= MAX_ENV_BYTES, f"env_too_large:{path.name}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"env_non_utf8:{path.name}") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        _require("=" in line, f"env_line_invalid:{path.name}")
        key, value = line.split("=", 1)
        _require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None, f"env_key_invalid:{path.name}")
        _require(key not in values, f"env_duplicate_key:{key}")
        _require("\x00" not in value, f"env_value_invalid:{key}")
        values[key] = value
    return values


def _directory(path: Path, reason: str, *, uid: int, gid: int, mode: int) -> os.stat_result:
    _require(path.is_dir() and not path.is_symlink(), f"{reason}:type")
    info = path.stat(follow_symlinks=False)
    if os.name != "nt":
        _require((info.st_uid, info.st_gid) == (uid, gid), f"{reason}:owner")
        _require(stat.S_IMODE(info.st_mode) == mode, f"{reason}:mode")
    return info


def _plain_directory(path: Path, reason: str) -> os.stat_result:
    _require(path.is_dir() and not path.is_symlink(), f"{reason}:type")
    return path.stat(follow_symlinks=False)


class NativeValidators:
    """只读验证固定 UAT 存储、模型和配置。"""

    def __init__(
        self,
        runner: Runner,
        paths: Paths = Paths(),
        *,
        root_uid: int = 0,
        deploy_uid: int = 1000,
        deploy_gid: int | None = None,
        storage_spec: StorageSpec = StorageSpec(),
    ) -> None:
        self.runner = runner
        self.paths = paths
        self.root_uid = root_uid
        self.deploy_uid = deploy_uid
        self.deploy_gid = deploy_uid if deploy_gid is None else deploy_gid
        self.storage_spec = storage_spec

    def verify_storage(self) -> ValidationResult:
        spec = self.storage_spec
        paths = self.paths
        _plain_directory(paths.data_mount, "data_mount_invalid")
        _directory(
            paths.backing_file.parent,
            "loop_directory_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
            mode=0o700,
        )
        _directory(
            paths.mount_point.parent,
            "smartscan_directory_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
            mode=0o755,
        )
        _directory(
            paths.mount_point,
            "mount_point_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
            mode=0o755,
        )
        backing = _regular_file(
            paths.backing_file,
            "backing_file_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
            mode=0o600,
        )
        _require(backing.st_size == spec.backing_bytes, "backing_size_invalid")
        allocated = backing.st_blocks * 512
        _require(allocated >= spec.backing_bytes, "backing_sparse")
        unit = _regular_file(
            paths.unit_path,
            "mount_unit_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
            mode=0o644,
        )
        _require(unit.st_size <= 64 * 1024, "mount_unit_too_large")
        _require(_sha256(paths.unit_path) == spec.unit_sha256, "mount_unit_digest_mismatch")
        unit_text = paths.unit_path.read_text(encoding="utf-8", errors="strict")
        for required in (
            "RequiresMountsFor=/mnt/data",
            "Where=/mnt/data/smartscan/uat",
            "What=/mnt/data/smartscan-loop/uat.ext4",
            "Options=loop,nodev,nosuid,noatime",
        ):
            _require(required in unit_text, "mount_unit_contract_invalid")

        data_mount = self.runner.run(
            ["/usr/bin/findmnt", "-rn", "--target", str(paths.data_mount), "-o", "TARGET"]
        ).splitlines()
        _require(data_mount == [str(paths.data_mount)], "data_mount_not_independent")
        mount = self.runner.run(
            [
                "/usr/bin/findmnt",
                "-rn",
                "--mountpoint",
                str(paths.mount_point),
                "-o",
                "SOURCE,FSTYPE,OPTIONS",
            ]
        ).splitlines()
        _require(len(mount) == 1, "mount_missing_or_duplicate")
        parts = mount[0].split(maxsplit=2)
        _require(len(parts) == 3, "mount_record_invalid")
        source, filesystem, options_text = parts
        _require(re.fullmatch(r"/dev/loop[0-9]+", source) is not None, "mount_source_invalid")
        _require(filesystem == "ext4", "mount_type_invalid")
        options = set(options_text.split(","))
        _require({"nodev", "nosuid", "noatime"}.issubset(options), "mount_options_invalid")

        loop_lines = self.runner.run(
            [
                "/usr/sbin/losetup",
                "-j",
                str(paths.backing_file),
                "--noheadings",
                "--output",
                "NAME,AUTOCLEAR",
            ]
        ).splitlines()
        _require(len(loop_lines) == 1, "loop_mapping_invalid")
        loop_parts = loop_lines[0].split()
        _require(loop_parts == [source, "1"], "loop_autoclear_invalid")

        identity = self.runner.run(
            ["/usr/sbin/blkid", "-p", "-o", "export", str(paths.backing_file)]
        )
        identity_values = dict(line.split("=", 1) for line in identity.splitlines() if "=" in line)
        _require(identity_values.get("TYPE") == "ext4", "filesystem_type_invalid")
        _require(identity_values.get("LABEL") == spec.filesystem_label, "filesystem_label_invalid")
        superblock = self.runner.run(["/usr/sbin/dumpe2fs", "-h", str(paths.backing_file)])
        reserved = re.search(r"^Reserved block count:\s*([0-9]+)\s*$", superblock, re.MULTILINE)
        _require(reserved is not None and reserved.group(1) == "0", "reserved_blocks_invalid")

        usable_lines = self.runner.run(
            ["/usr/bin/df", "-B1", "--output=avail", str(paths.mount_point)]
        ).splitlines()
        _require(len(usable_lines) >= 2, "usable_space_evidence_invalid")
        usable = _parse_positive_int(usable_lines[-1].strip(), "usable_space_evidence_invalid")
        _require(usable >= spec.minimum_usable_bytes, "usable_space_insufficient")
        host_lines = self.runner.run(
            ["/usr/bin/df", "-B1", "--output=size,avail", str(paths.data_mount)]
        ).splitlines()
        _require(len(host_lines) >= 2, "host_space_evidence_invalid")
        host_parts = host_lines[-1].split()
        _require(len(host_parts) == 2, "host_space_evidence_invalid")
        host_size = _parse_positive_int(host_parts[0], "host_space_evidence_invalid")
        host_available = _parse_positive_int(host_parts[1], "host_space_evidence_invalid")
        reserve = max(
            spec.minimum_host_reserve_bytes,
            host_size * spec.minimum_host_reserve_percent // 100,
        )
        _require(host_available >= reserve, "host_reserve_insufficient")
        self.runner.run(["/usr/bin/systemctl", "is-enabled", "--quiet", spec.unit_name])
        self.runner.run(["/usr/bin/systemctl", "is-active", "--quiet", spec.unit_name])
        return ValidationResult.success(
            evidence={
                "backing_size_bytes": backing.st_size,
                "fully_preallocated": True,
                "filesystem": "ext4",
                "label": spec.filesystem_label,
                "usable_bytes": usable,
                "host_reserve_satisfied": True,
                "mount_source": "loop-redacted",
                "autoclear": True,
                "unit_enabled": True,
                "unit_active": True,
            },
            next_state="storage_verified",
        )

    def verify_models(self) -> ValidationResult:
        root = self.paths.model_root
        _directory(root, "model_root_invalid", uid=self.root_uid, gid=self.root_uid, mode=0o755)
        manifest, _ = _strict_json_file(
            root / "manifest.json",
            "model_manifest_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
            mode=0o444,
        )
        required = {
            "schema_version": 1,
            "artifact_kind": "smartscan-offline-ocr-models",
            "artifact_version": EXPECTED_MODEL_VERSION,
            "backend": "paddle_static",
            "paddleocr_version": "3.7.0",
            "paddlepaddle_version": "3.3.1",
            "model_version": EXPECTED_MODEL_VERSION,
            "license": "Apache-2.0",
            "text_detection_dir": "PP-OCRv6_small_det",
            "text_recognition_dir": "PP-OCRv6_small_rec",
        }
        _require(
            all(manifest.get(key) == value for key, value in required.items()),
            "model_contract_invalid",
        )
        _require(
            manifest.get("conversion")
            == {"performed": False, "description": "仅规范化目录名，模型字节未修改"},
            "model_conversion_invalid",
        )
        _require(
            isinstance(manifest.get("source"), str) and manifest["source"].strip(),
            "model_source_missing",
        )
        _require(
            isinstance(manifest.get("source_commit"), str)
            and re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]) is not None,
            "model_source_commit_invalid",
        )
        files = manifest.get("files")
        metadata = manifest.get("file_metadata")
        evidence = manifest.get("evidence_files")
        _require(
            isinstance(files, dict) and set(files) == EXPECTED_MODEL_FILES, "model_file_set_invalid"
        )
        _require(
            isinstance(metadata, dict) and set(metadata) == EXPECTED_MODEL_FILES,
            "model_metadata_set_invalid",
        )
        _require(
            isinstance(evidence, dict) and set(evidence) == EXPECTED_EVIDENCE_FILES,
            "model_evidence_set_invalid",
        )
        _require(
            files
            == {
                name: item.get("sha256")
                for name, item in metadata.items()
                if isinstance(item, dict)
            },
            "model_compatibility_hashes_invalid",
        )
        expected_paths = EXPECTED_MODEL_FILES | EXPECTED_EVIDENCE_FILES | {"manifest.json"}
        actual_files: set[str] = set()
        actual_directories: set[str] = set()
        for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            for name in directories:
                candidate = current_path / name
                info = candidate.lstat()
                _require(
                    stat.S_ISDIR(info.st_mode) and not candidate.is_symlink(),
                    "model_special_directory",
                )
                if os.name != "nt":
                    _require(info.st_nlink >= 2, "model_directory_links_invalid")
                    _require(
                        (info.st_uid, info.st_gid) == (self.root_uid, self.root_uid),
                        "model_directory_owner_invalid",
                    )
                    _require(stat.S_IMODE(info.st_mode) == 0o755, "model_directory_mode_invalid")
                actual_directories.add(candidate.relative_to(root).as_posix())
            for name in filenames:
                candidate = current_path / name
                info = candidate.lstat()
                _require(
                    stat.S_ISREG(info.st_mode) and not candidate.is_symlink(), "model_special_file"
                )
                _require(info.st_nlink == 1, "model_hardlink_rejected")
                if os.name != "nt":
                    _require(
                        (info.st_uid, info.st_gid) == (self.root_uid, self.root_uid),
                        "model_file_owner_invalid",
                    )
                    _require(stat.S_IMODE(info.st_mode) == 0o444, "model_file_mode_invalid")
                actual_files.add(candidate.relative_to(root).as_posix())
        _require(
            actual_directories == {"PP-OCRv6_small_det", "PP-OCRv6_small_rec"},
            "model_directory_set_invalid",
        )
        _require(actual_files == expected_paths, "model_extra_or_missing_file")
        total_model_bytes = 0
        total_package_bytes = 0
        for relative, item in {**metadata, **evidence}.items():
            _require(isinstance(item, dict), "model_file_metadata_invalid")
            size = _exact_int(item.get("size"), "model_file_size_invalid")
            digest = item.get("sha256")
            _require(
                isinstance(digest, str) and SHA256.fullmatch(digest) is not None,
                "model_file_digest_invalid",
            )
            target = root / relative
            _require(target.stat().st_size == size, "model_file_size_mismatch")
            _require(_sha256(target) == digest, "model_file_digest_mismatch")
            total_package_bytes += size
            if relative in EXPECTED_MODEL_FILES:
                total_model_bytes += size
        _require(total_package_bytes <= 4 * GIB, "model_package_too_large")
        _require(
            manifest.get("total_model_bytes") == total_model_bytes, "model_total_bytes_invalid"
        )
        return ValidationResult.success(
            evidence={
                "artifact_version": EXPECTED_MODEL_VERSION,
                "file_count": len(expected_paths),
                "model_file_count": len(EXPECTED_MODEL_FILES),
                "total_model_bytes": total_model_bytes,
                "total_package_bytes": total_package_bytes,
                "license_evidence": True,
                "source_evidence": True,
                "links_rejected": True,
            },
            next_state="models_verified",
        )

    def verify_config(self) -> ValidationResult:
        paths = self.paths
        input_document, _ = _strict_json_file(
            paths.deployment_input,
            "deployment_input_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
        )
        preflight, preflight_raw = _strict_json_file(
            paths.preflight_summary,
            "preflight_summary_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
        )
        loop, loop_raw = _strict_json_file(
            paths.loop_evidence,
            "loop_evidence_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
        )
        allocation, _ = _strict_json_file(
            paths.allocation,
            "allocation_invalid",
            uid=self.root_uid,
            gid=self.root_uid,
        )
        deploy = _parse_env(paths.deploy_env, uid=self.deploy_uid, gid=self.deploy_gid)
        runtime = _parse_env(paths.runtime_env, uid=self.deploy_uid, gid=self.deploy_gid)
        bootstrap = _regular_file(
            paths.bootstrap_password,
            "bootstrap_password_invalid",
            uid=self.deploy_uid,
            gid=self.deploy_gid,
            mode=0o600,
        )
        _require(33 <= bootstrap.st_size <= 256, "bootstrap_password_length_invalid")

        _require(input_document.get("schema_version") == "1.0", "deployment_input_schema_invalid")
        _require(
            input_document.get("target_hostname") == "ctiecaiserver", "deployment_hostname_invalid"
        )
        origin = input_document.get("shared_entry_origin")
        _require(isinstance(origin, str), "deployment_origin_invalid")
        parsed_origin = urlparse(origin)
        _require(
            parsed_origin.scheme == "http"
            and parsed_origin.hostname is not None
            and parsed_origin.port == 8077
            and parsed_origin.path in {"", "/"}
            and parsed_origin.username is None
            and parsed_origin.password is None
            and not parsed_origin.query
            and not parsed_origin.fragment,
            "deployment_origin_invalid",
        )
        confirmation = input_document.get("confirmation")
        _require(isinstance(confirmation, dict), "deployment_confirmation_invalid")
        for key in (
            "confirmed_by",
            "confirmed_at",
            "change_record",
            "validation_record",
            "rollback_record",
        ):
            _require(
                isinstance(confirmation.get(key), str) and confirmation[key].strip(),
                "deployment_confirmation_invalid",
            )
        networks = input_document.get("networks")
        _require(
            isinstance(networks, dict) and set(networks) == {"data", "edge", "egress"},
            "deployment_networks_invalid",
        )
        parsed_networks: list[ipaddress._BaseNetwork] = []
        for name in ("data", "edge", "egress"):
            item = networks[name]
            _require(
                isinstance(item, dict) and set(item) >= {"subnet", "gateway"},
                "deployment_network_invalid",
            )
            try:
                subnet = ipaddress.ip_network(str(item["subnet"]), strict=True)
                gateway = ipaddress.ip_address(str(item["gateway"]))
            except ValueError as exc:
                raise ValidationError("deployment_network_invalid") from exc
            _require(gateway in subnet, "deployment_gateway_invalid")
            parsed_networks.append(subnet)
        _require(
            all(
                not network.overlaps(other)
                for index, network in enumerate(parsed_networks)
                for other in parsed_networks[index + 1 :]
            ),
            "deployment_network_overlap",
        )

        _require(preflight.get("status") == "passed", "preflight_status_invalid")
        _require(
            preflight.get("contains_sensitive_data") is False, "preflight_sensitive_flag_invalid"
        )
        _require(loop.get("contains_sensitive_data") is False, "loop_sensitive_flag_invalid")
        backing = loop.get("backing_file")
        filesystem = loop.get("filesystem")
        mount = loop.get("mount")
        loop_state = loop.get("loop")
        unit = loop.get("systemd_unit")
        _require(
            all(isinstance(item, dict) for item in (backing, filesystem, mount, loop_state, unit)),
            "loop_evidence_shape_invalid",
        )
        _require(backing.get("size_bytes") == BACKING_BYTES, "loop_evidence_size_invalid")
        _require(
            backing.get("allocated_bytes", 0) >= BACKING_BYTES and backing.get("sparse") is False,
            "loop_evidence_allocation_invalid",
        )
        _require(
            filesystem.get("type") == "ext4" and filesystem.get("label") == "smartscan-uat",
            "loop_evidence_filesystem_invalid",
        )
        _require(
            filesystem.get("reserved_blocks_percent") == 0
            and filesystem.get("usable_bytes", 0) >= MINIMUM_USABLE_BYTES,
            "loop_evidence_capacity_invalid",
        )
        _require(
            mount.get("active") is True and mount.get("target") == "/mnt/data/smartscan/uat",
            "loop_evidence_mount_invalid",
        )
        _require(
            {"loop", "nodev", "nosuid", "noatime"}.issubset(set(mount.get("options", []))),
            "loop_evidence_options_invalid",
        )
        _require(loop_state.get("autoclear") is True, "loop_evidence_autoclear_invalid")
        _require(
            unit.get("enabled") is True and unit.get("active") is True, "loop_evidence_unit_invalid"
        )

        _require(
            all(deploy.get(key) == value for key, value in ACCEPTED_IMAGES.items()),
            "accepted_images_changed",
        )
        expected_deploy = {
            "SMARTSCAN_DEPLOYMENT_TIER": "uat",
            "SMARTSCAN_UAT_ISOLATION_ACK": "uat-only-no-production-data",
            "COMPOSE_PROJECT_NAME": "smartscan-uat",
            "SMARTSCAN_UAT_RUNTIME_ENV_FILE": "/etc/smartscan/uat/runtime.env",
            "SMARTSCAN_UAT_ALLOCATION_FILE": "/etc/smartscan/uat/shared-host-allocation.json",
            "SMARTSCAN_UAT_BIND_ADDRESS": "127.0.0.1",
            "SMARTSCAN_UAT_HTTP_PORT": "18082",
            "SMARTSCAN_UAT_POSTGRES_ROOT": "/mnt/data/smartscan/uat/postgres",
            "SMARTSCAN_UAT_DATA_ROOT": "/mnt/data/smartscan/uat/data",
            "SMARTSCAN_UAT_MODEL_ROOT": "/mnt/data/smartscan/uat/models/ocr",
        }
        _require(
            all(deploy.get(key) == value for key, value in expected_deploy.items()),
            "deploy_contract_invalid",
        )
        for name in ("data", "edge", "egress"):
            prefix = f"SMARTSCAN_UAT_{name.upper()}"
            _require(
                deploy.get(f"{prefix}_SUBNET") == str(networks[name]["subnet"]),
                "deploy_network_mismatch",
            )
            _require(
                deploy.get(f"{prefix}_GATEWAY") == str(networks[name]["gateway"]),
                "deploy_network_mismatch",
            )
        _require(
            deploy.get("SMARTSCAN_UAT_PREFLIGHT_EVIDENCE_SHA256")
            == hashlib.sha256(preflight_raw).hexdigest(),
            "preflight_digest_mismatch",
        )
        _require(
            deploy.get("SMARTSCAN_UAT_LOOP_EVIDENCE_SHA256")
            == hashlib.sha256(loop_raw).hexdigest(),
            "loop_digest_mismatch",
        )
        _require(not deploy.get("COMPOSE_PROFILES"), "ai_profile_must_be_disabled")

        _require(
            all(key in deploy or key in runtime for key in SECRET_FIELDS), "secret_field_missing"
        )
        _require(len(deploy.get("POSTGRES_PASSWORD", "")) >= 48, "database_secret_invalid")
        _require(len(runtime.get("SMARTSCAN_SECRET_KEY", "")) >= 48, "application_secret_invalid")
        _require(
            len(runtime.get("SMARTSCAN_SUPERADMIN_PASSWORD", "")) >= 32, "bootstrap_secret_invalid"
        )
        _require(
            len(runtime.get("SMARTSCAN_OPS_METRICS_TOKEN", "")) >= 48, "metrics_secret_invalid"
        )
        try:
            hmac_peppers = json.loads(
                runtime.get("SMARTSCAN_PHONE_HMAC_PEPPERS", ""),
                object_pairs_hook=_object_without_duplicates,
            )
            encryption_keys = json.loads(
                runtime.get("SMARTSCAN_PHONE_ENCRYPTION_KEYS", ""),
                object_pairs_hook=_object_without_duplicates,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValidationError("phone_secret_json_invalid") from exc
        _require(
            isinstance(hmac_peppers, dict) and len(hmac_peppers) == 1, "phone_hmac_secret_invalid"
        )
        hmac_value = next(iter(hmac_peppers.values()))
        _require(
            isinstance(hmac_value, str) and len(hmac_value) >= 32,
            "phone_hmac_secret_invalid",
        )
        _require(
            isinstance(encryption_keys, dict) and len(encryption_keys) == 1,
            "phone_encryption_secret_invalid",
        )
        encryption_value = next(iter(encryption_keys.values()))
        try:
            decoded_key = base64.b64decode(encryption_value, altchars=b"-_", validate=True)
        except (ValueError, TypeError) as exc:
            raise ValidationError("phone_encryption_secret_invalid") from exc
        _require(len(decoded_key) == 32, "phone_encryption_secret_invalid")
        database_url = runtime.get("SMARTSCAN_DATABASE_URL", "")
        _require(
            database_url.startswith("postgresql+psycopg://smartscan:")
            and database_url.endswith("@postgres:5432/smartscan"),
            "database_url_invalid",
        )
        expected_runtime = {
            "SMARTSCAN_ENV": "production",
            "SMARTSCAN_AUTO_MIGRATE": "false",
            "SMARTSCAN_SMS_MODE": "disabled",
            "SMARTSCAN_DEV_SMS_CODE": "",
            "SMARTSCAN_WECOM_MODE": "disabled",
            "SMARTSCAN_WECOM_CORP_ID": "",
            "SMARTSCAN_WECOM_AGENT_ID": "",
            "SMARTSCAN_WECOM_SECRET": "",
            "SMARTSCAN_WECOM_REDIRECT_URI": "",
            "SMARTSCAN_AI_PROVIDERS": "[]",
            "SMARTSCAN_AI_INTERNAL_TOKEN": "",
            "SMARTSCAN_AI_GATEWAY_URL": "",
            "SMARTSCAN_AI_PROVIDER_ID": "",
            "SMARTSCAN_AI_INTERNAL_MEDIA_URL": "",
            "SMARTSCAN_AI_MEDIA_BASE_URL": "",
            "SMARTSCAN_AI_MOCK_MODE": "false",
            "SMARTSCAN_OCR_ENABLED": "true",
            "SMARTSCAN_OCR_MODEL_VERSION": EXPECTED_MODEL_VERSION,
            "SMARTSCAN_STORAGE_WARNING_PERCENT": "70",
            "SMARTSCAN_STORAGE_CLEANUP_PERCENT": "85",
            "SMARTSCAN_STORAGE_STOP_WRITES_PERCENT": "95",
        }
        _require(
            all(runtime.get(key) == value for key, value in expected_runtime.items()),
            "runtime_contract_invalid",
        )

        _require(allocation.get("schema_version") == "1.2", "allocation_schema_invalid")
        _require(
            allocation.get("compose_project_name") == "smartscan-uat", "allocation_project_invalid"
        )
        _require(allocation.get("networks") == networks, "allocation_network_mismatch")
        host_ports = allocation.get("host_ports")
        _require(
            host_ports
            == [{"purpose": "UAT Web 回环入口", "port": 18082, "bind_address": "127.0.0.1"}],
            "allocation_ports_invalid",
        )
        storage = allocation.get("storage")
        resources = allocation.get("resources")
        budgets = allocation.get("storage_budgets")
        monitoring = allocation.get("monitoring")
        _require(
            isinstance(storage, dict) and storage.get("quota_bytes") == BACKING_BYTES,
            "allocation_storage_invalid",
        )
        _require(
            (
                storage.get("warning_percent"),
                storage.get("cleanup_percent"),
                storage.get("stop_writes_percent"),
            )
            == (70, 85, 95),
            "allocation_thresholds_invalid",
        )
        _require(
            isinstance(resources, dict)
            and resources.get("cpu_limit") == 8
            and resources.get("memory_limit_bytes") == 16 * GIB,
            "allocation_resources_invalid",
        )
        _require(
            isinstance(budgets, dict)
            and sum(_exact_int(value, "allocation_budget_invalid") for value in budgets.values())
            <= BACKING_BYTES,
            "allocation_budget_invalid",
        )
        _require(
            isinstance(monitoring, dict)
            and monitoring.get("deploy_node_exporter") is False
            and monitoring.get("deploy_alertmanager") is False
            and monitoring.get("accepted_capability_gap") is True,
            "allocation_monitoring_invalid",
        )
        return ValidationResult.success(
            evidence={
                "fixed_image_count": len(ACCEPTED_IMAGES),
                "network_count": 3,
                "loop_evidence_bound": True,
                "preflight_evidence_bound": True,
                "secret_fields_present": len(SECRET_FIELDS),
                "secret_values_printed": False,
                "external_services": {
                    "sms": "disabled",
                    "wecom": "disabled",
                    "real_ai": "disabled",
                    "ai_profile": "disabled",
                },
                "ocr_model_version": EXPECTED_MODEL_VERSION,
            },
            next_state="config_verified",
        )
