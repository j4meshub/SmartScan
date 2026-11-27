#!/usr/bin/env python3
"""SmartScan UAT 单用途、状态机式部署控制器。

控制器没有通用命令入口；所有路径、Compose 项目、服务和外部命令均固定。
它只输出脱敏 JSON，任何失败都保留现场并停止，不执行清理或 prune。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

try:
    from . import smartscan_uat_validators as native_validators
except ImportError:  # pragma: no cover - 服务器以固定脚本路径执行
    import smartscan_uat_validators as native_validators

COMMANDS = (
    "status",
    "preflight",
    "verify-storage",
    "verify-models",
    "verify-config",
    "accept-release",
    "import-images",
    "verify-images",
    "probe-identities",
    "apply-ownership",
    "start-database",
    "verify-database",
    "run-migrations",
    "start-core",
    "verify-core",
    "stage-nginx",
    "activate-nginx",
    "verify-uat",
    "stop-core",
    "rollback-images",
    "resume-basic-uat",
)
ALLOWED_PREFIX = "ghcr.io/j4meshub/smartscan-"
PLATFORM = "linux/amd64"
PROJECT = "smartscan-uat"
MIGRATION_TARGET = "20261022_0024"
MIGRATION_STORAGE_ROOT = "/tmp/smartscan-data"
EXPECTED_SERVICES = {"postgres", "api", "worker", "ai-gateway", "web", "ops"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LOCAL_TAG = re.compile(r"^smartscan-uat-[a-z0-9-]+:sha256-[0-9a-f]{12}$")
ARCHIVE_NAME = re.compile(r"^smartscan-[a-z0-9-]+-[0-9a-f]{12}-linux-amd64\.docker\.tar$")
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
INSTALLED_ASSET_SHA256 = {
    "docker-compose.uat.yml": "01b5970c309074a19e5722c8ce2ae2a1a646b69cea6777b29140121cb1d76b37",
    "shared-8077-smartscan-location.conf": "500aee2ae34f6a14e658823588899647ece628b97fb65554132eef95e741d227",
    "smartscan_uat_validators.py": "27916a63ea05c9fb149255b5ee63edc1bd43b1f4e26ec347266eef6026e0467b",
}


class ControllerError(RuntimeError):
    """状态或固定对象不满足失败关闭条件。"""


class FixedFilePolicy(Enum):
    """控制器固定文件的有限权限策略；调用方不能传入任意模式或所有者。"""

    PUBLIC_ROOT_ASSET_0644 = "public_root_asset_0644"
    INTERNAL_STATE_ROOT_0600 = "internal_state_root_0600"
    UPLOADED_RELEASE_DEPLOY_0600 = "uploaded_release_deploy_0600"


@dataclass(frozen=True)
class FixedFilePermissionContract:
    owner_role: str
    mode: int
    sensitive: bool


FIXED_FILE_PERMISSION_CONTRACTS = {
    FixedFilePolicy.PUBLIC_ROOT_ASSET_0644: FixedFilePermissionContract(
        owner_role="root", mode=0o644, sensitive=False
    ),
    FixedFilePolicy.INTERNAL_STATE_ROOT_0600: FixedFilePermissionContract(
        owner_role="root", mode=0o600, sensitive=True
    ),
    FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600: FixedFilePermissionContract(
        owner_role="deploy", mode=0o600, sensitive=True
    ),
}


@dataclass(frozen=True)
class CommandResult:
    """只在控制器内部使用的子进程结果，原始输出不得直接持久化。"""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RuntimeImageIdentity:
    """Docker 本地对象与已审核离线内容链的结构化绑定。"""

    runtime_image_id: str
    runtime_descriptor_digest: str
    runtime_descriptor_size: int
    runtime_identity_kind: str
    repo_digests: tuple[str, ...]
    rootfs_diff_ids: tuple[str, ...]

    def evidence(self) -> dict[str, Any]:
        return {
            "runtime_image_id": self.runtime_image_id,
            "runtime_descriptor_digest": self.runtime_descriptor_digest,
            "runtime_descriptor_size": self.runtime_descriptor_size,
            "runtime_identity_kind": self.runtime_identity_kind,
            "repo_digests": list(self.repo_digests),
            "rootfs_diff_ids": list(self.rootfs_diff_ids),
        }


@dataclass(frozen=True)
class Paths:
    config_root: Path = Path("/etc/smartscan/uat")
    data_root: Path = Path("/mnt/data/smartscan/uat")
    upload_root: Path = Path("/home/szhzx/smartscan-uat-offline-images")
    installed_release: Path = Path("/etc/smartscan/uat/release-manifest.json")
    installed_map: Path = Path("/etc/smartscan/uat/release-map.json")
    local_images_env: Path = Path("/etc/smartscan/uat/local-images.env")
    image_identities: Path = Path("/etc/smartscan/uat/image-identities.json")
    state_file: Path = Path("/etc/smartscan/uat/uatctl-state.json")
    migration_failure: Path = Path("/etc/smartscan/uat/migration-failure.json")
    deploy_env: Path = Path("/etc/smartscan/uat/deploy.env")
    runtime_env: Path = Path("/etc/smartscan/uat/runtime.env")
    activation_plan: Path = Path("/etc/smartscan/uat/nginx-activation.json")
    staged_nginx: Path = Path("/etc/smartscan/uat/nginx-smartscan-8077.locations.conf")
    prepared_nginx_config: Path = Path("/etc/smartscan/uat/nginx-8077-server.updated.conf")
    nginx_backup: Path = Path("/etc/smartscan/uat/nginx-8077-server.original.conf")
    active_nginx: Path = Path("/etc/nginx/snippets/smartscan-uat-8077.locations.conf")
    compose_file: Path = Path("/usr/local/libexec/smartscan/docker-compose.uat.yml")
    nginx_template: Path = Path("/usr/local/libexec/smartscan/shared-8077-smartscan-location.conf")
    validator_module: Path = Path("/usr/local/libexec/smartscan/smartscan_uat_validators.py")
    # 普通增量发布使用固定上传入口。用户对清单摘要显式授权后，控制器再以
    # accept-release 固定命令登记；不再把每个候选文件名或摘要编译进包装器。
    candidate_release: Path = Path(
        "/home/szhzx/smartscan-uat-offline-images/candidate-release.json"
    )
    previous_release: Path = Path("/etc/smartscan/uat/previous-release-manifest.json")
    previous_map: Path = Path("/etc/smartscan/uat/previous-release-map.json")
    previous_local_images: Path = Path("/etc/smartscan/uat/previous-local-images.env")
    previous_identities: Path = Path("/etc/smartscan/uat/previous-image-identities.json")
    previous_web_release: Path = Path("/etc/smartscan/uat/previous-web-release-manifest.json")
    previous_web_map: Path = Path("/etc/smartscan/uat/previous-web-release-map.json")
    previous_web_local_images: Path = Path("/etc/smartscan/uat/previous-web-local-images.env")
    previous_web_identities: Path = Path("/etc/smartscan/uat/previous-web-image-identities.json")
    publish_network_evidence: Path = Path("/etc/smartscan/uat/publish-network-evidence.json")


class Runner(Protocol):
    def run(
        self,
        arguments: list[str],
        *,
        check: bool = True,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> str: ...

    def run_result(
        self,
        arguments: list[str],
        *,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    def run_result(
        self,
        arguments: list[str],
        *,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> CommandResult:
        try:
            process = subprocess.run(
                arguments,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise ControllerError(f"command_timeout:{Path(arguments[0]).name}") from exc
        return CommandResult(process.returncode, process.stdout.strip(), process.stderr.strip())

    def run(
        self,
        arguments: list[str],
        *,
        check: bool = True,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        result = self.run_result(
            arguments,
            timeout_seconds=timeout_seconds,
            environment=environment,
        )
        if check and result.returncode != 0:
            raise ControllerError(f"command_failed:{Path(arguments[0]).name}")
        return result.stdout


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ControllerError(reason)


def _normalize_sha256(value: object, reason: str) -> str:
    text = str(value).strip().lower().removeprefix("sha256:")
    _require(SHA256.fullmatch(text) is not None, reason)
    return f"sha256:{text}"


def _json_command_output(value: str, reason: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ControllerError(reason) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_sha256(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _tar_json(bundle: tarfile.TarFile, member: tarfile.TarInfo, reason: str) -> dict[str, Any]:
    stream = bundle.extractfile(member)
    _require(stream is not None, reason)
    try:
        value = json.loads(stream.read())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerError(reason) from exc
    _require(isinstance(value, dict), reason)
    return value


def _tar_json_list(
    bundle: tarfile.TarFile, member: tarfile.TarInfo, reason: str
) -> list[dict[str, Any]]:
    stream = bundle.extractfile(member)
    _require(stream is not None, reason)
    try:
        value = json.loads(stream.read())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerError(reason) from exc
    _require(isinstance(value, list) and all(isinstance(item, dict) for item in value), reason)
    return value


def _verify_fixed_file(
    path: Path,
    policy: FixedFilePolicy,
    *,
    expected_root_uid: int = 0,
    expected_deploy_uid: int = 1000,
) -> None:
    """按命名策略验证固定普通文件，拒绝链接、宽松模式和所有者漂移。"""

    _require(path.is_file() and not path.is_symlink(), f"fixed_json_invalid:{path.name}")
    if os.name != "nt":
        info = path.stat()
        contract = FIXED_FILE_PERMISSION_CONTRACTS[policy]
        expected_uid = expected_root_uid if contract.owner_role == "root" else expected_deploy_uid
        _require(
            info.st_uid == expected_uid and info.st_gid == expected_uid,
            f"fixed_json_owner_invalid:{path.name}",
        )
        _require(
            stat.S_IMODE(info.st_mode) == contract.mode,
            f"fixed_json_mode_invalid:{path.name}",
        )
        _require(info.st_nlink == 1, f"fixed_json_links_invalid:{path.name}")


def _load_json(
    path: Path,
    *,
    policy: FixedFilePolicy,
    expected_root_uid: int = 0,
    expected_deploy_uid: int = 1000,
) -> dict[str, Any]:
    _verify_fixed_file(
        path,
        policy,
        expected_root_uid=expected_root_uid,
        expected_deploy_uid=expected_deploy_uid,
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControllerError(f"fixed_json_content_invalid:{path.name}") from exc
    _require(isinstance(value, dict), f"fixed_json_root_invalid:{path.name}")
    return value


def _atomic_json(path: Path, value: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        os.write(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def _atomic_text(path: Path, value: str, mode: int = 0o600) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        os.write(fd, value.encode())
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def _initial_state() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "completed": [],
        "history": [],
        "secrets_included": False,
    }


class Controller:
    def __init__(
        self,
        paths: Paths = Paths(),
        runner: Runner | None = None,
        *,
        root_uid: int = 0,
        deploy_uid: int = 1000,
        validator: native_validators.NativeValidators | None = None,
    ) -> None:
        self.paths = paths
        self.runner = runner or SubprocessRunner()
        self.root_uid = root_uid
        self.deploy_uid = deploy_uid
        self.validator = validator or native_validators.NativeValidators(
            self.runner,
            native_validators.Paths(
                config_root=self.paths.config_root,
                mount_point=self.paths.data_root,
                model_root=self.paths.data_root / "models" / "ocr",
                deployment_input=self.paths.config_root / "deployment-input.json",
                preflight_summary=self.paths.config_root / "preflight-summary.json",
                loop_evidence=self.paths.config_root / "loop-storage-evidence.json",
                deploy_env=self.paths.deploy_env,
                runtime_env=self.paths.runtime_env,
                allocation=self.paths.config_root / "shared-host-allocation.json",
                bootstrap_password=self.paths.config_root / "bootstrap-admin-password",
            ),
            root_uid=root_uid,
            deploy_uid=deploy_uid,
        )

    def _state(self) -> dict[str, Any]:
        if not self.paths.state_file.exists():
            return _initial_state()
        return _load_json(
            self.paths.state_file,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )

    def _completed(self, name: str) -> bool:
        return name in self._state().get("completed", [])

    def _record(self, name: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self._state()
        completed = list(state.get("completed", []))
        already_complete = name in completed
        if not already_complete:
            completed.append(name)
            state["history"] = [
                *state.get("history", []),
                {"step": name, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            ][-100:]
        state["completed"] = completed
        if evidence:
            state.setdefault("evidence", {})[name] = evidence
        state["secrets_included"] = False
        _atomic_json(self.paths.state_file, state)
        return {"status": "passed", "step": name, "already_complete": already_complete}

    def _require_steps(self, *names: str) -> None:
        completed = set(self._state().get("completed", []))
        _require(set(names).issubset(completed), f"state_prerequisite_missing:{','.join(names)}")

    def _record_validation(
        self, result: native_validators.ValidationResult, expected_state: str
    ) -> dict[str, Any]:
        _require(result.passed, f"native_validation_failed:{result.reason_code}")
        _require(result.next_state == expected_state, "native_validation_state_mismatch")
        return self._record(expected_state, result.evidence_summary)

    def _run_native_validation(self, action, expected_state: str) -> dict[str, Any]:
        try:
            result = action()
        except native_validators.ValidationError as exc:
            raise ControllerError(f"native_validation_failed:{exc}") from exc
        return self._record_validation(result, expected_state)

    def _fixed_release(self, *, uploaded: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata_root = self.paths.upload_root if uploaded else self.paths.config_root
        policy = (
            FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600
            if uploaded
            else FixedFilePolicy.INTERNAL_STATE_ROOT_0600
        )
        release = _load_json(
            metadata_root / "release-manifest.json",
            policy=policy,
            expected_root_uid=self.root_uid,
            expected_deploy_uid=self.deploy_uid,
        )
        mapping = _load_json(
            metadata_root / "release-map.json",
            policy=policy,
            expected_root_uid=self.root_uid,
            expected_deploy_uid=self.deploy_uid,
        )
        _require(release.get("schema_version") in {"1.0", "1.1"}, "release_schema_invalid")
        _require(release.get("platform") == PLATFORM, "release_platform_invalid")
        _require(release.get("registry_prefix") == ALLOWED_PREFIX, "release_registry_invalid")
        images = release.get("images")
        records = mapping.get("images")
        _require(isinstance(images, list) and len(images) == 6, "release_images_invalid")
        _require(isinstance(records, list) and len(records) == 6, "release_map_invalid")
        by_service = {item.get("service"): item for item in records if isinstance(item, dict)}
        _require(set(by_service) == EXPECTED_SERVICES, "release_map_services_invalid")
        for image in images:
            _require(isinstance(image, dict), "release_image_invalid")
            service = image.get("service")
            source = str(image.get("source", ""))
            tag = str(image.get("local_tag", ""))
            archive_name = str(image.get("archive_name", ""))
            _require(service in EXPECTED_SERVICES, "release_service_invalid")
            _require(
                source.startswith(ALLOWED_PREFIX) and "@sha256:" in source, "release_source_invalid"
            )
            source_digest = source.rsplit("@sha256:", 1)[-1]
            _require(SHA256.fullmatch(source_digest) is not None, "release_source_digest_invalid")
            _require(LOCAL_TAG.fullmatch(tag) is not None, "release_local_tag_invalid")
            _require(
                ARCHIVE_NAME.fullmatch(archive_name) is not None, "release_archive_name_invalid"
            )
            _require(
                source_digest[:12] in tag and source_digest[:12] in archive_name,
                "release_name_unbound",
            )
            record = by_service[service]
            _require(record.get("source") == source, "release_map_source_mismatch")
            _require(record.get("local_tag") == tag, "release_map_tag_mismatch")
            _require(
                record.get("image_id") == record.get("config_digest"),
                "release_map_image_id_invalid",
            )
            _require(
                SHA256.fullmatch(str(record.get("archive_sha256", ""))) is not None,
                "archive_digest_invalid",
            )
            archive = self._archive_path(release, image)
            _require(archive.is_file() and not archive.is_symlink(), "archive_missing")
            if os.name != "nt":
                info = archive.stat()
                _require(
                    info.st_uid == self.deploy_uid
                    and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1,
                    "archive_permissions_invalid",
                )
            _require(
                archive.stat().st_size == int(record.get("archive_size", -1)),
                "archive_size_invalid",
            )
            _require(_sha256(archive) == record.get("archive_sha256"), "archive_hash_invalid")
            self._verify_uploaded_archive(image, record, archive)
        return release, mapping

    def _archive_path(self, release: dict[str, Any], image: dict[str, Any]) -> Path:
        changed = release.get("changed_services", [])
        if release.get("schema_version") == "1.1" and image.get("service") in changed:
            candidate_root = self.paths.upload_root / str(release.get("release_id", ""))
            if candidate_root.is_dir() and not candidate_root.is_symlink():
                return candidate_root / str(image["archive_name"])
        return self.paths.upload_root / str(image["archive_name"])

    def _candidate_release(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """验证固定单服务候选，不改变当前已激活发布。"""

        candidate = _load_json(
            self.paths.candidate_release,
            policy=FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600,
            expected_deploy_uid=self.deploy_uid,
        )
        _require(candidate.get("schema_version") == "1.1", "incremental_release_schema_invalid")
        changed = candidate.get("changed_services")
        _require(changed in (["worker"], ["web"]), "incremental_scope_invalid")
        changed_service = changed[0]
        active, active_map = self._fixed_release(uploaded=False)
        _require(
            candidate.get("base_release_id") == active.get("release_id")
            and candidate.get("base_release_manifest_sha256")
            == _sha256(self.paths.installed_release),
            "incremental_base_release_mismatch",
        )
        candidate_root = self.paths.upload_root / str(candidate.get("release_id", ""))
        uploaded_manifest = candidate_root / "release-manifest.json"
        uploaded_map = candidate_root / "release-map.json"
        _require(
            candidate_root.is_dir()
            and not candidate_root.is_symlink()
            and uploaded_manifest.is_file()
            and not uploaded_manifest.is_symlink()
            and uploaded_map.is_file()
            and not uploaded_map.is_symlink(),
            "incremental_release_upload_missing",
        )
        if os.name != "nt":
            for path in (candidate_root, uploaded_manifest, uploaded_map):
                info = path.stat()
                expected_mode = 0o700 if path == candidate_root else 0o600
                _require(
                    info.st_uid == self.deploy_uid
                    and stat.S_IMODE(info.st_mode) == expected_mode
                    and (path == candidate_root or info.st_nlink == 1),
                    f"incremental_release_permissions_invalid:{path.name}",
                )
        _require(
            _sha256(uploaded_manifest) == _sha256(self.paths.candidate_release),
            "incremental_manifest_digest_mismatch",
        )
        # 候选映射属于部署用户上传证据；上方已经固定校验所有者、0600、
        # 单硬链接和候选目录边界。活动映射仍必须由root安装并按默认门禁读取。
        mapping = _load_json(
            uploaded_map,
            policy=FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600,
            expected_deploy_uid=self.deploy_uid,
        )
        _require(
            mapping.get("release_id") == candidate.get("release_id")
            and mapping.get("release_manifest_sha256") == _sha256(self.paths.candidate_release),
            "incremental_map_binding_invalid",
        )
        active_images = {item["service"]: item for item in active["images"]}
        active_records = {item["service"]: item for item in active_map["images"]}
        candidate_images = {item["service"]: item for item in candidate.get("images", [])}
        candidate_records = {
            item["service"]: item for item in mapping.get("images", []) if isinstance(item, dict)
        }
        _require(
            set(candidate_images) == EXPECTED_SERVICES
            and set(candidate_records) == EXPECTED_SERVICES,
            "incremental_release_services_invalid",
        )
        for service in EXPECTED_SERVICES - {changed_service}:
            _require(
                candidate_images[service] == active_images[service]
                and candidate_records[service] == active_records[service],
                f"incremental_unchanged_service_drift:{service}",
            )
        changed_image = candidate_images[changed_service]
        changed_record = candidate_records[changed_service]
        _require(
            changed_image != active_images[changed_service]
            and changed_image["source"] != active_images[changed_service]["source"]
            and changed_image["local_tag"] != active_images[changed_service]["local_tag"],
            f"incremental_{changed_service}_not_changed",
        )
        archive = candidate_root / changed_image["archive_name"]
        _require(
            archive.is_file() and not archive.is_symlink(),
            f"incremental_{changed_service}_archive_missing",
        )
        if os.name != "nt":
            info = archive.stat()
            _require(
                info.st_uid == self.deploy_uid
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1,
                f"incremental_{changed_service}_archive_permissions_invalid",
            )
        _require(
            archive.stat().st_size == int(changed_record.get("archive_size", -1))
            and _sha256(archive) == changed_record.get("archive_sha256"),
            f"incremental_{changed_service}_archive_digest_invalid",
        )
        self._verify_uploaded_archive(changed_image, changed_record, archive)
        if changed_service == "web":
            self._publish_network_spec(candidate)
        return candidate, mapping

    def _publish_network_spec(self, candidate: dict[str, Any]) -> dict[str, Any]:
        path = (
            self.paths.upload_root / str(candidate.get("release_id", "")) / "publish-network.json"
        )
        value = _load_json(
            path,
            policy=FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600,
            expected_deploy_uid=self.deploy_uid,
        )
        _require(value.get("schema_version") == "1.0", "publish_network_schema_invalid")
        _require(
            value.get("network_name") == "smartscan-uat-publish", "publish_network_name_invalid"
        )
        _require(
            value.get("risk_acknowledgement") == "loopback-proxy-has-theoretical-egress",
            "publish_network_risk_ack_missing",
        )
        try:
            subnet = ipaddress.ip_network(str(value.get("subnet", "")), strict=True)
            gateway = ipaddress.ip_address(str(value.get("gateway", "")))
        except ValueError as exc:
            raise ControllerError("publish_network_ipam_invalid") from exc
        _require(
            isinstance(subnet, ipaddress.IPv4Network)
            and subnet.is_private
            and subnet.prefixlen == 28,
            "publish_network_subnet_invalid",
        )
        _require(gateway == subnet.network_address + 1, "publish_network_gateway_invalid")
        confirmation = value.get("confirmation")
        _require(isinstance(confirmation, dict), "publish_network_confirmation_invalid")
        for field in (
            "confirmed_by",
            "confirmed_at",
            "change_record",
            "validation_record",
            "rollback_record",
        ):
            _require(
                isinstance(confirmation.get(field), str) and confirmation[field].strip(),
                f"publish_network_confirmation_missing:{field}",
            )
        return value

    @staticmethod
    def _network_from_ipam(value: Any) -> list[ipaddress.IPv4Network]:
        result: list[ipaddress.IPv4Network] = []
        if not isinstance(value, list):
            return result
        for item in value:
            if not isinstance(item, dict) or not item.get("Subnet"):
                continue
            try:
                network = ipaddress.ip_network(str(item["Subnet"]), strict=False)
            except ValueError:
                continue
            if isinstance(network, ipaddress.IPv4Network):
                result.append(network)
        return result

    def _inspect_publish_network(self, expected: dict[str, Any]) -> bool:
        result = self.runner.run_result(
            [
                "/usr/bin/docker",
                "network",
                "inspect",
                "smartscan-uat-publish",
            ]
        )
        if result.returncode != 0:
            return False
        try:
            values = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ControllerError("publish_network_inspect_invalid") from exc
        _require(isinstance(values, list) and len(values) == 1, "publish_network_inspect_invalid")
        network = values[0]
        _require(
            network.get("Name") == "smartscan-uat-publish"
            and network.get("Driver") == "bridge"
            and network.get("Scope") == "local"
            and network.get("Internal") is False,
            "publish_network_contract_invalid",
        )
        configs = network.get("IPAM", {}).get("Config", [])
        _require(
            isinstance(configs, list)
            and len(configs) == 1
            and configs[0].get("Subnet") == expected["subnet"]
            and configs[0].get("Gateway") == expected["gateway"]
            and not configs[0].get("IPRange")
            and not configs[0].get("AuxiliaryAddresses"),
            "publish_network_ipam_drift",
        )
        labels = network.get("Labels") or {}
        _require(
            labels.get("com.smartscan.environment") == "uat"
            and labels.get("com.smartscan.managed-by") == "smartscan-uatctl"
            and labels.get("com.smartscan.role") == "loopback-publish",
            "publish_network_labels_invalid",
        )
        return True

    def _ensure_publish_network(self, candidate: dict[str, Any]) -> None:
        expected = self._publish_network_spec(candidate)
        if self._inspect_publish_network(expected):
            return
        proposed = ipaddress.ip_network(expected["subnet"], strict=True)
        network_ids = self.runner.run(["/usr/bin/docker", "network", "ls", "--quiet"]).splitlines()
        for network_id in network_ids:
            raw = self.runner.run(
                [
                    "/usr/bin/docker",
                    "network",
                    "inspect",
                    "--format",
                    "{{json .IPAM.Config}}",
                    network_id,
                ]
            )
            try:
                configs = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ControllerError("docker_ipam_snapshot_invalid") from exc
            _require(
                not any(proposed.overlaps(item) for item in self._network_from_ipam(configs)),
                "publish_network_docker_overlap",
            )
        for command, reason in (
            (["/usr/sbin/ip", "-j", "-4", "route", "show", "table", "all"], "route"),
            (["/usr/sbin/ip", "-j", "-4", "rule", "show"], "policy"),
            (["/usr/sbin/ip", "-j", "-4", "address", "show"], "interface"),
        ):
            try:
                rows = json.loads(self.runner.run(command))
            except json.JSONDecodeError as exc:
                raise ControllerError(f"publish_network_{reason}_snapshot_invalid") from exc
            _require(isinstance(rows, list), f"publish_network_{reason}_snapshot_invalid")
            for row in rows:
                values = []
                if reason == "route":
                    values.append(row.get("dst"))
                elif reason == "policy":
                    values.extend((row.get("from"), row.get("to")))
                else:
                    values.extend(item.get("local") for item in row.get("addr_info", []))
                for text in values:
                    if not text or text == "default":
                        continue
                    try:
                        current = ipaddress.ip_network(
                            text if "/" in str(text) else f"{text}/32", strict=False
                        )
                    except ValueError:
                        continue
                    if isinstance(current, ipaddress.IPv4Network):
                        _require(
                            not proposed.overlaps(current),
                            f"publish_network_{reason}_overlap",
                        )
        self.runner.run(
            [
                "/usr/bin/docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--subnet",
                expected["subnet"],
                "--gateway",
                expected["gateway"],
                "--label",
                "com.smartscan.environment=uat",
                "--label",
                "com.smartscan.managed-by=smartscan-uatctl",
                "--label",
                "com.smartscan.role=loopback-publish",
                "smartscan-uat-publish",
            ]
        )
        _require(
            self._inspect_publish_network(expected), "publish_network_create_verification_failed"
        )
        _atomic_json(self.paths.publish_network_evidence, expected)

    @staticmethod
    def _verify_uploaded_archive(
        image: dict[str, Any], record: dict[str, Any], archive: Path
    ) -> None:
        with tarfile.open(archive, "r") as bundle:
            members: dict[str, tarfile.TarInfo] = {}
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                _require(
                    not path.is_absolute() and ".." not in path.parts,
                    "archive_member_path_invalid",
                )
                _require(member.isfile(), "archive_special_member_rejected")
                _require(member.name not in members, "archive_duplicate_member")
                members[member.name] = member
            source_digest = str(image["source"]).rsplit("@", 1)[-1]
            platform_digest = str(record.get("platform_manifest", ""))
            config_digest = str(record.get("config_digest", ""))
            layers = record.get("layers")
            _require(
                all(
                    value.startswith("sha256:") and SHA256.fullmatch(value[7:])
                    for value in (source_digest, platform_digest, config_digest)
                ),
                "archive_descriptor_digest_invalid",
            )
            _require(isinstance(layers, list) and layers, "archive_layers_invalid")
            layer_digests = [str(item.get("digest", "")) for item in layers]
            _require(
                all(
                    value.startswith("sha256:") and SHA256.fullmatch(value[7:])
                    for value in layer_digests
                ),
                "archive_layer_digest_invalid",
            )
            _require(
                record.get("archive_format") == "docker-image-archive-v1",
                "archive_format_invalid",
            )
            config_name = f"{config_digest[7:]}.json"
            layer_names = [f"layers/{value[7:]}.tar.gz" for value in layer_digests]
            expected = {
                "manifest.json",
                config_name,
                "smartscan-evidence/source.json",
                "smartscan-evidence/platform-manifest.json",
                *layer_names,
            }
            _require(set(members) == expected, "archive_member_set_invalid")
            docker_manifest = _tar_json_list(
                bundle, members["manifest.json"], "archive_docker_manifest_invalid"
            )
            _require(
                len(docker_manifest) == 1
                and docker_manifest[0].get("Config") == config_name
                and docker_manifest[0].get("RepoTags") == [image["local_tag"]]
                and docker_manifest[0].get("Layers") == layer_names,
                "archive_docker_manifest_unbound",
            )
            source = _tar_json(
                bundle,
                members["smartscan-evidence/source.json"],
                "archive_source_invalid",
            )
            source_stream = bundle.extractfile(members["smartscan-evidence/source.json"])
            _require(source_stream is not None, "archive_source_missing")
            _require(
                _stream_sha256(source_stream) == source_digest[7:],
                "archive_source_digest_invalid",
            )
            source_media_type = str(source.get("mediaType", ""))
            if source_digest != platform_digest:
                _require(source_media_type in INDEX_MEDIA_TYPES, "archive_source_index_required")
                matches = [
                    item
                    for item in source.get("manifests", [])
                    if isinstance(item, dict)
                    and item.get("digest") == platform_digest
                    and item.get("platform", {}).get("os") == "linux"
                    and item.get("platform", {}).get("architecture") == "amd64"
                    and item.get("platform", {}).get("variant") in {None, ""}
                ]
                _require(len(matches) == 1, "archive_source_platform_unbound")
            else:
                _require(
                    source_media_type in MANIFEST_MEDIA_TYPES, "archive_source_manifest_invalid"
                )
            platform = _tar_json(
                bundle,
                members["smartscan-evidence/platform-manifest.json"],
                "archive_platform_manifest_invalid",
            )
            platform_stream = bundle.extractfile(
                members["smartscan-evidence/platform-manifest.json"]
            )
            _require(platform_stream is not None, "archive_platform_manifest_missing")
            _require(
                _stream_sha256(platform_stream) == platform_digest[7:],
                "archive_platform_manifest_digest_invalid",
            )
            _require(
                platform.get("config", {}).get("digest") == config_digest,
                "archive_config_unbound",
            )
            _require(
                [item.get("digest") for item in platform.get("layers", [])] == layer_digests,
                "archive_layers_unbound",
            )
            config = _tar_json(bundle, members[config_name], "archive_config_invalid")
            config_stream = bundle.extractfile(members[config_name])
            _require(config_stream is not None, "archive_config_missing")
            _require(
                _stream_sha256(config_stream) == config_digest[7:],
                "archive_config_digest_invalid",
            )
            _require(
                config.get("os") == "linux" and config.get("architecture") == "amd64",
                "archive_config_platform_invalid",
            )
            _require(
                config.get("rootfs", {}).get("diff_ids")
                == [item.get("diff_id") for item in layers],
                "archive_diff_ids_unbound",
            )
            for item, name in zip(layers, layer_names, strict=True):
                stream = bundle.extractfile(members[name])
                _require(stream is not None, "archive_layer_missing")
                _require(
                    members[name].size == int(item.get("size", -1)),
                    "archive_layer_size_invalid",
                )
                _require(
                    _stream_sha256(stream) == str(item.get("digest"))[7:],
                    "archive_layer_digest_invalid",
                )

    def status(self) -> dict[str, Any]:
        state = self._state()
        return {
            "status": "passed",
            "completed": state.get("completed", []),
            "next_required": self._next_required(state),
            "secrets_included": False,
        }

    @staticmethod
    def _next_required(state: dict[str, Any]) -> str:
        completed = set(state.get("completed", []))
        sequence = (
            "preflight",
            "storage_verified",
            "models_verified",
            "config_verified",
            "release_accepted",
            "images_imported",
            "images_verified",
            "identities_verified",
            "ownership_applied",
            "database_started",
            "database_verified",
            "migrations_completed",
            "core_started",
            "core_verified",
            "nginx_staged",
            "nginx_activated",
            "basic_uat_verified",
        )
        return next((item for item in sequence if item not in completed), "complete")

    def preflight(self) -> dict[str, Any]:
        for path in (self.paths.config_root, self.paths.data_root, self.paths.upload_root):
            _require(
                path.is_dir() and not path.is_symlink(), f"fixed_directory_invalid:{path.name}"
            )
        if os.name != "nt":
            upload = self.paths.upload_root.stat()
            _require(
                upload.st_uid == self.deploy_uid and stat.S_IMODE(upload.st_mode) == 0o700,
                "upload_directory_permissions_invalid",
            )
        installed_assets = {
            self.paths.compose_file: FixedFilePolicy.PUBLIC_ROOT_ASSET_0644,
            self.paths.nginx_template: FixedFilePolicy.PUBLIC_ROOT_ASSET_0644,
            self.paths.validator_module: FixedFilePolicy.PUBLIC_ROOT_ASSET_0644,
        }
        for path, policy in installed_assets.items():
            try:
                _verify_fixed_file(
                    path,
                    policy,
                    expected_root_uid=self.root_uid,
                    expected_deploy_uid=self.deploy_uid,
                )
            except ControllerError as exc:
                raise ControllerError(f"installed_asset_invalid:{path.name}:{exc}") from exc
            _require(
                path.name in INSTALLED_ASSET_SHA256,
                f"installed_asset_digest_unpinned:{path.name}",
            )
            expected = INSTALLED_ASSET_SHA256[path.name]
            _require(
                not expected.startswith("REPLACE_"),
                f"installed_asset_digest_unpinned:{path.name}",
            )
            _require(_sha256(path) == expected, f"installed_asset_digest_mismatch:{path.name}")
        networks = self.runner.run(["/usr/bin/docker", "network", "ls", "--format", "{{.Name}}"])
        for name in ("smartscan-uat-data", "smartscan-uat-edge", "smartscan-uat-egress"):
            _require(name in networks.splitlines(), f"fixed_network_missing:{name}")
        return self._record("preflight")

    def verify_storage(self) -> dict[str, Any]:
        self._require_steps("preflight")
        return self._run_native_validation(self.validator.verify_storage, "storage_verified")

    def verify_models(self) -> dict[str, Any]:
        self._require_steps("storage_verified")
        return self._run_native_validation(self.validator.verify_models, "models_verified")

    def verify_config(self) -> dict[str, Any]:
        self._require_steps("models_verified")
        return self._run_native_validation(self.validator.verify_config, "config_verified")

    def accept_release(self) -> dict[str, Any]:
        self._require_steps("preflight", "storage_verified", "models_verified", "config_verified")
        if self._completed("release_accepted"):
            state = self._state()
            pending = state.get("pending_release_update")
            if pending:
                _require(
                    isinstance(pending, dict)
                    and pending.get("status") in {"accepted", "verified", "activated"},
                    "incremental_release_state_invalid",
                )
                return self.status()
            self._require_steps("migrations_completed")
            release, _mapping = self._candidate_release()
            changed_services = release["changed_services"]
            if changed_services == ["worker"]:
                _require(not self._completed("core_started"), "incremental_core_already_started")
            else:
                _require(
                    self._completed("core_started") and not self._completed("core_verified"),
                    "web_update_checkpoint_invalid",
                )
            state["pending_release_update"] = {
                "status": "accepted",
                "release_id": release["release_id"],
                "manifest_sha256": _sha256(self.paths.candidate_release),
                "map_sha256": _sha256(
                    self.paths.upload_root / release["release_id"] / "release-map.json"
                ),
                "changed_services": changed_services,
                "secrets_included": False,
            }
            state["history"] = [
                *state.get("history", []),
                {
                    "step": "incremental_release_accepted",
                    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            ][-100:]
            _atomic_json(self.paths.state_file, state)
            return {
                "status": "passed",
                "step": "incremental_release_accepted",
                "release_id": release["release_id"],
                "secrets_included": False,
            }
        release, _mapping = self._fixed_release(uploaded=True)
        for name in ("release-manifest.json", "release-map.json"):
            source = self.paths.upload_root / name
            destination = self.paths.config_root / name
            _require(
                not destination.exists() and not destination.is_symlink(), "accepted_release_exists"
            )
            temporary = destination.with_suffix(".tmp")
            shutil.copyfile(source, temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        return self._record(
            "release_accepted",
            {
                "release_id": release.get("release_id"),
                "map_sha256": _sha256(self.paths.installed_map),
            },
        )

    def _compose(self, *arguments: str) -> str:
        return self.runner.run(self._compose_command(*arguments))

    def _compose_command(self, *arguments: str) -> list[str]:
        return [
            "/usr/bin/docker",
            "compose",
            "--project-name",
            PROJECT,
            "--env-file",
            str(self.paths.deploy_env),
            "--env-file",
            str(self.paths.local_images_env),
            "-f",
            str(self.paths.compose_file),
            *arguments,
        ]

    @staticmethod
    def _migration_failure_summary(result: CommandResult) -> tuple[str, str]:
        """从内存中的有限输出提取白名单错误类别，不返回原始文本。"""

        combined = f"{result.stdout[-32768:]}\n{result.stderr[-32768:]}"
        exception_type = "UnknownError"
        allowed_types = (
            "ModuleNotFoundError",
            "ImportError",
            "PermissionError",
            "OSError",
            "OperationalError",
            "ProgrammingError",
            "IntegrityError",
            "CommandError",
            "ResolutionError",
            "RuntimeError",
        )
        for candidate in allowed_types:
            if re.search(rf"(?:^|[.: ]){re.escape(candidate)}(?:$|[: ])", combined, re.MULTILINE):
                exception_type = candidate
                break
        lowered = combined.casefold()
        if "read-only file system" in lowered:
            reason = "migration_storage_read_only"
        elif "modulenotfounderror" in lowered or "importerror" in lowered:
            reason = "migration_module_import_failed"
        elif any(
            marker in lowered
            for marker in ("connection refused", "could not connect", "operationalerror")
        ):
            reason = "migration_database_unavailable"
        elif any(
            marker in lowered
            for marker in (
                "can't locate revision",
                "resolutionerror",
                "alembic.util.exc.commanderror",
            )
        ):
            reason = "migration_revision_error"
        else:
            reason = "migration_process_failed"
        return reason, exception_type

    def _record_migration_failure(self, result: CommandResult) -> tuple[str, str]:
        reason, exception_type = self._migration_failure_summary(result)
        _atomic_json(
            self.paths.migration_failure,
            {
                "schema_version": "1.0",
                "status": "failed",
                "reason_code": reason,
                "exception_type": exception_type,
                "exit_code": max(1, min(int(result.returncode), 255)),
                "target_revision": MIGRATION_TARGET,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "raw_output_retained": False,
                "secrets_included": False,
            },
        )
        return reason, exception_type

    @staticmethod
    def _expected_runtime_descriptor(record: dict[str, Any], archive: Path) -> tuple[str, int]:
        """重算 Docker load 在 containerd image store 中生成的 schema2 manifest。"""

        config_digest = _normalize_sha256(
            record.get("config_digest"), "runtime_config_digest_invalid"
        )
        layers = record.get("layers")
        _require(isinstance(layers, list) and layers, "runtime_layers_invalid")
        with tarfile.open(archive, "r") as bundle:
            config_name = f"{config_digest[7:]}.json"
            try:
                config_size = bundle.getmember(config_name).size
            except KeyError as exc:
                raise ControllerError("runtime_archive_config_missing") from exc
        document = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "digest": config_digest,
                "size": config_size,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "digest": _normalize_sha256(item.get("digest"), "runtime_layer_digest_invalid"),
                    "size": int(item.get("size", -1)),
                }
                for item in layers
                if isinstance(item, dict)
            ],
        }
        _require(len(document["layers"]) == len(layers), "runtime_layers_invalid")
        _require(
            all(item["size"] >= 0 for item in document["layers"]),
            "runtime_layer_size_invalid",
        )
        raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(raw).hexdigest()}", len(raw)

    def _inspect_runtime_image(
        self,
        image: dict[str, Any],
        record: dict[str, Any],
        archive: Path | None = None,
    ) -> RuntimeImageIdentity:
        service, tag = str(image["service"]), str(image["local_tag"])

        def field(template: str) -> str:
            return self.runner.run(
                ["/usr/bin/docker", "image", "inspect", "--format", template, tag]
            )

        runtime_image_id = _normalize_sha256(
            field("{{.Id}}"), f"runtime_image_id_invalid:{service}"
        )
        repo_tags = _json_command_output(
            field("{{json .RepoTags}}"), f"runtime_repo_tags_invalid:{service}"
        )
        _require(
            isinstance(repo_tags, list)
            and all(isinstance(item, str) for item in repo_tags)
            and [item for item in repo_tags if item.startswith("smartscan-uat-")] == [tag],
            f"runtime_local_tag_not_unique:{service}",
        )
        repo_digests_value = _json_command_output(
            field("{{json .RepoDigests}}"), f"runtime_repo_digests_invalid:{service}"
        )
        _require(
            repo_digests_value is None
            or (
                isinstance(repo_digests_value, list)
                and all(isinstance(item, str) for item in repo_digests_value)
            ),
            f"runtime_repo_digests_invalid:{service}",
        )
        repo_digests = tuple(repo_digests_value or [])
        _require(field("{{.Os}}") == "linux", f"runtime_os_invalid:{service}")
        _require(field("{{.Architecture}}") == "amd64", f"runtime_architecture_invalid:{service}")
        config_user = _json_command_output(
            field("{{json .Config.User}}"), f"runtime_config_user_invalid:{service}"
        )
        _require(
            isinstance(config_user, str) and config_user == str(record.get("config_user", "")),
            f"runtime_config_user_mismatch:{service}",
        )
        revision = field(
            '{{with .Config.Labels}}{{index . "org.opencontainers.image.revision"}}{{end}}'
        )
        version = field(
            '{{with .Config.Labels}}{{index . "org.opencontainers.image.version"}}{{end}}'
        )
        _require(
            revision == str(record.get("revision", "")), f"runtime_revision_mismatch:{service}"
        )
        _require(version == str(record.get("version", "")), f"runtime_version_mismatch:{service}")
        rootfs_value = _json_command_output(
            field("{{json .RootFS.Layers}}"), f"runtime_rootfs_invalid:{service}"
        )
        _require(isinstance(rootfs_value, list), f"runtime_rootfs_invalid:{service}")
        rootfs_diff_ids = tuple(
            _normalize_sha256(value, f"runtime_diff_id_invalid:{service}") for value in rootfs_value
        )
        expected_diff_ids = tuple(
            _normalize_sha256(item.get("diff_id"), "release_diff_id_invalid")
            for item in record.get("layers", [])
            if isinstance(item, dict)
        )
        _require(
            rootfs_diff_ids == expected_diff_ids and len(rootfs_diff_ids) > 0,
            f"runtime_rootfs_mismatch:{service}",
        )

        config_digest = _normalize_sha256(
            record.get("config_digest"), "release_config_digest_invalid"
        )
        descriptor_output = self.runner.run(
            [
                "/usr/bin/docker",
                "image",
                "inspect",
                "--format",
                "{{json .Descriptor}}",
                tag,
            ],
            check=False,
        )
        descriptor_value = (
            _json_command_output(descriptor_output, f"runtime_descriptor_invalid:{service}")
            if descriptor_output
            else None
        )
        if runtime_image_id == config_digest:
            # 传统 image store 以配置摘要作为 Image ID；Descriptor 可能为空。
            descriptor_digest = config_digest
            descriptor_size = 0
            identity_kind = "legacy_config_digest"
            if descriptor_value is not None:
                _require(
                    isinstance(descriptor_value, dict), f"runtime_descriptor_invalid:{service}"
                )
        else:
            _require(isinstance(descriptor_value, dict), f"runtime_descriptor_required:{service}")
            expected_digest, expected_size = self._expected_runtime_descriptor(
                record, archive or self.paths.upload_root / str(image["archive_name"])
            )
            descriptor_digest = _normalize_sha256(
                descriptor_value.get("digest"), f"runtime_descriptor_digest_invalid:{service}"
            )
            descriptor_size = descriptor_value.get("size")
            _require(
                descriptor_value.get("mediaType")
                == "application/vnd.docker.distribution.manifest.v2+json",
                f"runtime_descriptor_media_type_invalid:{service}",
            )
            _require(
                descriptor_digest == runtime_image_id == expected_digest,
                f"runtime_descriptor_digest_mismatch:{service}",
            )
            _require(
                isinstance(descriptor_size, int) and descriptor_size == expected_size,
                f"runtime_descriptor_size_mismatch:{service}",
            )
            identity_kind = "containerd_schema2_descriptor"
        return RuntimeImageIdentity(
            runtime_image_id=runtime_image_id,
            runtime_descriptor_digest=descriptor_digest,
            runtime_descriptor_size=descriptor_size,
            runtime_identity_kind=identity_kind,
            repo_digests=repo_digests,
            rootfs_diff_ids=rootfs_diff_ids,
        )

    def import_images(self) -> dict[str, Any]:
        self._require_steps("release_accepted")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        identities: dict[str, Any] = {}
        for image in release["images"]:
            service, tag = image["service"], image["local_tag"]
            current = self.runner.run(
                ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", tag], check=False
            )
            if not current:
                self.runner.run(
                    [
                        "/usr/bin/docker",
                        "load",
                        "--input",
                        str(self.paths.upload_root / image["archive_name"]),
                    ]
                )
            identity = self._inspect_runtime_image(
                image, by_service[service], self._archive_path(release, image)
            )
            identities[service] = identity.evidence()
        return self._record("images_imported", {"runtime_identities": identities})

    def verify_images(self) -> dict[str, Any]:
        self._require_steps("images_imported")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        lines: list[str] = []
        identities: dict[str, Any] = {}
        for image in release["images"]:
            service, tag, runtime_key = image["service"], image["local_tag"], image["runtime_key"]
            identity = self._inspect_runtime_image(
                image, by_service[service], self._archive_path(release, image)
            )
            identities[service] = identity.evidence()
            lines.append(f"{runtime_key}={tag}")
        _atomic_text(self.paths.local_images_env, "\n".join(lines) + "\n")
        # AI Profile 在基础 UAT 中保持关闭，但离线发布映射必须覆盖已接受的六个镜像。
        # 显式包含固定 Profile 只解析配置，不会创建或启动 AI 容器。
        config = self._compose("--profile", "ai", "config", "--images")
        _require(
            all(image["local_tag"] in config.splitlines() for image in release["images"]),
            "compose_offline_mapping_invalid",
        )
        return self._record("images_verified", {"runtime_identities": identities})

    def _probe(self, service: str, tag: str, selector: str) -> int:
        output = self.runner.run(
            [
                "/usr/bin/docker",
                "run",
                "--rm",
                "--name",
                f"smartscan-uat-identity-{service}-{selector}",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--cpus",
                "0.10",
                "--memory",
                "32m",
                "--pids-limit",
                "16",
                "--entrypoint",
                "/usr/bin/id",
                tag,
                f"-{selector}",
            ]
        )
        _require(output.isdigit(), f"identity_probe_invalid:{service}:{selector}")
        return int(output)

    def probe_identities(self) -> dict[str, Any]:
        self._require_steps("images_verified")
        if self._completed("identities_verified"):
            document = _load_json(
                self.paths.image_identities,
                policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
                expected_root_uid=self.root_uid,
            )
            _require(
                document.get("schema_version") == "1.1" and document.get("platform") == PLATFORM,
                "identity_evidence_changed",
            )
            return self._record("identities_verified")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        images: dict[str, Any] = {}
        for image in release["images"]:
            service, record = image["service"], by_service[image["service"]]
            runtime_identity = self._inspect_runtime_image(
                image, record, self._archive_path(release, image)
            )
            user = str(record.get("config_user", ""))
            match = re.fullmatch(r"([0-9]+):([0-9]+)", user)
            if match:
                uid, gid, method = int(match.group(1)), int(match.group(2)), "static_config_user"
            else:
                uid = self._probe(service, image["local_tag"], "u")
                gid = self._probe(service, image["local_tag"], "g")
                method = "networkless_controlled_probe"
            images[image["deploy_key"]] = {
                "reference": image["source"],
                "repo_digest_verified": False,
                "source_digest_verified": True,
                "offline_mapping_verified": True,
                "source_digest": image["source"],
                "platform_manifest": record["platform_manifest"],
                "config_digest": record["config_digest"],
                "layer_digests": [item["digest"] for item in record["layers"]],
                "rootfs_diff_ids": [item["diff_id"] for item in record["layers"]],
                "local_tag": image["local_tag"],
                "archive_sha256": record["archive_sha256"],
                **runtime_identity.evidence(),
                "config_user": user,
                "runtime_uid": uid,
                "runtime_gid": gid,
                "identity_method": method,
            }
        document = {
            "schema_version": "1.1",
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": PLATFORM,
            "images": images,
            "secrets_included": False,
        }
        _atomic_json(self.paths.image_identities, document)
        return self._record("identities_verified")

    def apply_ownership(self) -> dict[str, Any]:
        self._require_steps("identities_verified")
        document = _load_json(
            self.paths.image_identities,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        _require(document.get("schema_version") == "1.1", "identity_schema_invalid")
        _require(document.get("platform") == PLATFORM, "identity_platform_invalid")
        images = document.get("images")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        _require(isinstance(images, dict), "identity_images_invalid")
        identities: dict[str, tuple[int, int]] = {}
        for image in release["images"]:
            key, service = image["deploy_key"], image["service"]
            record = images.get(key)
            expected = by_service[service]
            runtime_identity = self._inspect_runtime_image(
                image, expected, self._archive_path(release, image)
            )
            valid_mapping = (
                isinstance(record, dict)
                and record.get("reference") == image["source"]
                and record.get("repo_digest_verified") is False
                and record.get("source_digest_verified") is True
                and record.get("offline_mapping_verified") is True
                and record.get("archive_sha256") == expected["archive_sha256"]
                and record.get("platform_manifest") == expected["platform_manifest"]
                and record.get("config_digest") == expected["config_digest"]
                and record.get("layer_digests") == [item["digest"] for item in expected["layers"]]
                and record.get("rootfs_diff_ids")
                == [item["diff_id"] for item in expected["layers"]]
                and record.get("runtime_image_id") == runtime_identity.runtime_image_id
                and record.get("runtime_descriptor_digest")
                == runtime_identity.runtime_descriptor_digest
                and record.get("runtime_descriptor_size")
                == runtime_identity.runtime_descriptor_size
                and record.get("runtime_identity_kind") == runtime_identity.runtime_identity_kind
                and record.get("repo_digests") == list(runtime_identity.repo_digests)
                and record.get("local_tag") == image["local_tag"]
            )
            _require(valid_mapping, f"identity_mapping_invalid:{service}")
            uid, gid = record.get("runtime_uid"), record.get("runtime_gid")
            _require(
                isinstance(uid, int) and isinstance(gid, int) and uid >= 0 and gid >= 0,
                f"identity_uid_gid_invalid:{service}",
            )
            identities[key] = (uid, gid)
        _require(
            identities["SMARTSCAN_UAT_POSTGRES_IMAGE"] == (70, 70),
            "postgres_identity_must_be_70_70",
        )
        _require(
            identities["SMARTSCAN_UAT_API_IMAGE"] == identities["SMARTSCAN_UAT_WORKER_IMAGE"],
            "api_worker_identity_mismatch",
        )
        postgres = self.paths.data_root / "postgres"
        data = self.paths.data_root / "data"
        models = self.paths.data_root / "models" / "ocr"
        targets = {
            postgres: (*identities["SMARTSCAN_UAT_POSTGRES_IMAGE"], 0o700),
            data: (*identities["SMARTSCAN_UAT_API_IMAGE"], 0o750),
            models: (self.root_uid, self.root_uid, 0o755),
        }
        for path in targets:
            _require(
                path.is_dir() and not path.is_symlink(), f"ownership_target_invalid:{path.name}"
            )
        if self._completed("ownership_applied"):
            for path, (uid, gid, mode) in targets.items():
                info = path.stat()
                _require(
                    (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode),
                    f"ownership_state_changed:{path.name}",
                )
            return self._record("ownership_applied")
        _require(not any(postgres.iterdir()), "postgres_directory_not_empty")
        _require(not any(data.iterdir()), "data_directory_not_empty")
        for path, (uid, gid, mode) in targets.items():
            os.chown(path, uid, gid)
            os.chmod(path, mode)
            info = path.stat()
            _require(
                (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode),
                f"ownership_verification_failed:{path.name}",
            )
        return self._record("ownership_applied")

    def _verify_incremental_data_ownership(self) -> None:
        info = (self.paths.data_root / "data").stat()
        _require(
            (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (10001, 10001, 0o750),
            "incremental_data_ownership_changed",
        )

    def _save_one_step_rollback(self, backup_pairs: tuple[tuple[Path, Path], ...]) -> None:
        """原子保存当前活动发布，固定只保留最近一次可验证回滚证据。"""

        for source, backup in backup_pairs:
            _verify_fixed_file(
                source,
                FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
                expected_root_uid=self.root_uid,
            )
            if backup.exists() or backup.is_symlink():
                _verify_fixed_file(
                    backup,
                    FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
                    expected_root_uid=self.root_uid,
                )
            temporary = backup.with_name(f".{backup.name}.next.tmp")
            _require(
                not temporary.exists() and not temporary.is_symlink(),
                f"incremental_backup_temp_exists:{backup.name}",
            )
            shutil.copyfile(source, temporary)
            if hasattr(os, "chown"):
                os.chown(temporary, self.root_uid, self.root_uid)
            os.chmod(temporary, 0o600)
            os.replace(temporary, backup)

    def _activate_pending_worker_release(self) -> dict[str, Any]:
        """验证并原子切换单Worker候选；失败时保留旧发布为活动发布。"""

        state = self._state()
        pending = state.get("pending_release_update")
        _require(
            isinstance(pending, dict) and pending.get("status") in {"accepted", "verified"},
            "incremental_release_not_accepted",
        )
        _require(not self._completed("core_started"), "incremental_core_already_started")
        candidate, mapping = self._candidate_release()
        _require(
            pending.get("release_id") == candidate.get("release_id")
            and pending.get("manifest_sha256") == _sha256(self.paths.candidate_release),
            "incremental_release_state_mismatch",
        )
        worker = next(item for item in candidate["images"] if item["service"] == "worker")
        worker_record = next(item for item in mapping["images"] if item["service"] == "worker")
        archive = self._archive_path(candidate, worker)
        current = self.runner.run(
            [
                "/usr/bin/docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                worker["local_tag"],
            ],
            check=False,
        )
        if not current:
            self.runner.run(["/usr/bin/docker", "load", "--input", str(archive)])
        runtime_identity = self._inspect_runtime_image(worker, worker_record, archive)
        user = str(worker_record.get("config_user", ""))
        match = re.fullmatch(r"([0-9]+):([0-9]+)", user)
        if match:
            uid, gid, method = int(match.group(1)), int(match.group(2)), "static_config_user"
        else:
            uid = self._probe("worker-update", worker["local_tag"], "u")
            gid = self._probe("worker-update", worker["local_tag"], "g")
            method = "networkless_controlled_probe"
        _require((uid, gid) == (10001, 10001), "incremental_worker_identity_changed")
        identities = _load_json(
            self.paths.image_identities,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        images = identities.get("images")
        _require(isinstance(images, dict), "identity_images_invalid")
        old_worker = images.get("SMARTSCAN_UAT_WORKER_IMAGE")
        _require(
            isinstance(old_worker, dict)
            and (old_worker.get("runtime_uid"), old_worker.get("runtime_gid")) == (10001, 10001),
            "previous_worker_identity_invalid",
        )
        self._verify_incremental_data_ownership()
        images["SMARTSCAN_UAT_WORKER_IMAGE"] = {
            "reference": worker["source"],
            "repo_digest_verified": False,
            "source_digest_verified": True,
            "offline_mapping_verified": True,
            "source_digest": worker["source"],
            "platform_manifest": worker_record["platform_manifest"],
            "config_digest": worker_record["config_digest"],
            "layer_digests": [item["digest"] for item in worker_record["layers"]],
            "rootfs_diff_ids": [item["diff_id"] for item in worker_record["layers"]],
            "local_tag": worker["local_tag"],
            "archive_sha256": worker_record["archive_sha256"],
            **runtime_identity.evidence(),
            "config_user": user,
            "runtime_uid": uid,
            "runtime_gid": gid,
            "identity_method": method,
        }
        lines = [f"{item['runtime_key']}={item['local_tag']}" for item in candidate["images"]]

        backup_pairs = (
            (self.paths.installed_release, self.paths.previous_release),
            (self.paths.installed_map, self.paths.previous_map),
            (self.paths.local_images_env, self.paths.previous_local_images),
            (self.paths.image_identities, self.paths.previous_identities),
        )
        self._save_one_step_rollback(backup_pairs)
        pending["status"] = "verified"
        pending["worker_runtime_id"] = runtime_identity.runtime_image_id
        pending["worker_uid"] = uid
        pending["worker_gid"] = gid
        _atomic_json(self.paths.state_file, state)

        candidate_map = self.paths.upload_root / candidate["release_id"] / "release-map.json"
        try:
            _atomic_text(
                self.paths.installed_release,
                self.paths.candidate_release.read_text(encoding="utf-8"),
            )
            _atomic_text(
                self.paths.installed_map,
                candidate_map.read_text(encoding="utf-8"),
            )
            _atomic_text(self.paths.local_images_env, "\n".join(lines) + "\n")
            _atomic_json(self.paths.image_identities, identities)
            active_release, active_map = self._fixed_release()
            _require(
                active_release == candidate and active_map == mapping,
                "incremental_activation_verification_failed",
            )
            self._inspect_runtime_image(worker, worker_record, archive)
            state = self._state()
            state["pending_release_update"]["status"] = "activated"
            state["pending_release_update"]["activated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            state["history"] = [
                *state.get("history", []),
                {
                    "step": "incremental_worker_release_activated",
                    "recorded_at": state["pending_release_update"]["activated_at"],
                },
            ][-100:]
            _atomic_json(self.paths.state_file, state)
        except (ControllerError, OSError, UnicodeError):
            for active, backup in backup_pairs:
                shutil.copyfile(backup, active)
                if hasattr(os, "chown"):
                    os.chown(active, self.root_uid, self.root_uid)
                os.chmod(active, 0o600)
            raise ControllerError("incremental_activation_rolled_back") from None
        return {
            "status": "passed",
            "step": "incremental_worker_release_activated",
            "secrets_included": False,
        }

    def _activate_pending_web_release(self) -> dict[str, Any]:
        """从core_started断点只替换Web镜像，并增加受限回环代理。"""

        state = self._state()
        pending = state.get("pending_release_update")
        _require(
            isinstance(pending, dict)
            and pending.get("status") in {"accepted", "verified"}
            and pending.get("changed_services") == ["web"],
            "incremental_web_release_not_accepted",
        )
        _require(
            self._completed("core_started") and not self._completed("core_verified"),
            "web_update_checkpoint_invalid",
        )
        candidate, mapping = self._candidate_release()
        _require(
            pending.get("release_id") == candidate.get("release_id")
            and pending.get("manifest_sha256") == _sha256(self.paths.candidate_release),
            "incremental_release_state_mismatch",
        )
        web = next(item for item in candidate["images"] if item["service"] == "web")
        web_record = next(item for item in mapping["images"] if item["service"] == "web")
        archive = self._archive_path(candidate, web)
        current = self.runner.run(
            ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", web["local_tag"]],
            check=False,
        )
        if not current:
            self.runner.run(["/usr/bin/docker", "load", "--input", str(archive)])
        runtime_identity = self._inspect_runtime_image(web, web_record, archive)
        user = str(web_record.get("config_user", ""))
        match = re.fullmatch(r"([0-9]+):([0-9]+)", user)
        if match:
            uid, gid, method = int(match.group(1)), int(match.group(2)), "static_config_user"
        else:
            uid = self._probe("web-update", web["local_tag"], "u")
            gid = self._probe("web-update", web["local_tag"], "g")
            method = "networkless_controlled_probe"
        identities = _load_json(
            self.paths.image_identities,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        images = identities.get("images")
        _require(isinstance(images, dict), "identity_images_invalid")
        _require(
            isinstance(images.get("SMARTSCAN_UAT_WEB_IMAGE"), dict),
            "previous_web_identity_invalid",
        )
        images["SMARTSCAN_UAT_WEB_IMAGE"] = {
            "reference": web["source"],
            "repo_digest_verified": False,
            "source_digest_verified": True,
            "offline_mapping_verified": True,
            "source_digest": web["source"],
            "platform_manifest": web_record["platform_manifest"],
            "config_digest": web_record["config_digest"],
            "layer_digests": [item["digest"] for item in web_record["layers"]],
            "rootfs_diff_ids": [item["diff_id"] for item in web_record["layers"]],
            "local_tag": web["local_tag"],
            "archive_sha256": web_record["archive_sha256"],
            **runtime_identity.evidence(),
            "config_user": user,
            "runtime_uid": uid,
            "runtime_gid": gid,
            "identity_method": method,
        }
        self._ensure_publish_network(candidate)
        lines = [f"{item['runtime_key']}={item['local_tag']}" for item in candidate["images"]]
        backup_pairs = (
            (self.paths.installed_release, self.paths.previous_web_release),
            (self.paths.installed_map, self.paths.previous_web_map),
            (self.paths.local_images_env, self.paths.previous_web_local_images),
            (self.paths.image_identities, self.paths.previous_web_identities),
        )
        self._save_one_step_rollback(backup_pairs)
        unchanged_ids = {
            service: self._compose("ps", "-q", service).strip()
            for service in ("postgres", "api", "worker-cpu-1", "worker-cpu-2")
        }
        pending["status"] = "verified"
        pending["web_runtime_id"] = runtime_identity.runtime_image_id
        pending["web_uid"] = uid
        pending["web_gid"] = gid
        _atomic_json(self.paths.state_file, state)
        candidate_map = self.paths.upload_root / candidate["release_id"] / "release-map.json"
        try:
            # 先只切换Compose运行引用并验证新Web/代理；活动发布映射仍保持
            # 旧值。全部运行门禁通过后才原子写入活动清单和身份。
            _atomic_text(self.paths.local_images_env, "\n".join(lines) + "\n")
            self._compose(
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "nginx",
                "loopback-proxy",
            )
            for service, expected_id in unchanged_ids.items():
                _require(
                    expected_id and self._compose("ps", "-q", service).strip() == expected_id,
                    f"unchanged_core_recreated:{service}",
                )
            self._wait_core_health()
            _atomic_text(
                self.paths.installed_release,
                self.paths.candidate_release.read_text(encoding="utf-8"),
            )
            _atomic_text(self.paths.installed_map, candidate_map.read_text(encoding="utf-8"))
            _atomic_json(self.paths.image_identities, identities)
            active_release, active_map = self._fixed_release()
            _require(
                active_release == candidate and active_map == mapping,
                "incremental_activation_verification_failed",
            )
            state = self._state()
            state["pending_release_update"]["status"] = "activated"
            state["pending_release_update"]["activated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            state["history"] = [
                *state.get("history", []),
                {
                    "step": "incremental_web_release_activated",
                    "recorded_at": state["pending_release_update"]["activated_at"],
                },
            ][-100:]
            _atomic_json(self.paths.state_file, state)
        except (ControllerError, OSError, UnicodeError):
            for active, backup in backup_pairs:
                shutil.copyfile(backup, active)
                if hasattr(os, "chown"):
                    os.chown(active, self.root_uid, self.root_uid)
                os.chmod(active, 0o600)
            # 失败时只恢复旧Web；数据库、API和Worker保持原容器不动。
            self.runner.run_result(self._compose_command("stop", "loopback-proxy"))
            self.runner.run_result(
                self._compose_command("up", "-d", "--no-deps", "--force-recreate", "nginx")
            )
            raise ControllerError("incremental_web_activation_rolled_back") from None
        return {
            "status": "passed",
            "step": "incremental_web_release_activated",
            "secrets_included": False,
        }

    def _activate_pending_release(self) -> dict[str, Any]:
        pending = self._state().get("pending_release_update")
        _require(isinstance(pending, dict), "incremental_release_not_accepted")
        if pending.get("changed_services") == ["worker"]:
            return self._activate_pending_worker_release()
        if pending.get("changed_services") == ["web"]:
            return self._activate_pending_web_release()
        raise ControllerError("incremental_scope_invalid")

    def start_database(self) -> dict[str, Any]:
        self._require_steps("ownership_applied")
        if self._completed("database_started"):
            return self.verify_database()
        self._compose("up", "-d", "--no-deps", "postgres")
        return self._record("database_started")

    def verify_database(self) -> dict[str, Any]:
        self._require_steps("database_started")
        last_error: ControllerError | None = None
        for _ in range(30):
            try:
                self._compose(
                    "exec", "-T", "postgres", "pg_isready", "-U", "smartscan", "-d", "smartscan"
                )
                last_error = None
                break
            except ControllerError as exc:
                last_error = exc
                time.sleep(2)
        if last_error is not None:
            raise ControllerError("database_health_timeout") from last_error
        return self._record("database_verified")

    def run_migrations(self) -> dict[str, Any]:
        self._require_steps("database_verified")
        if self._completed("migrations_completed"):
            self.verify_database()
            return self._record("migrations_completed")
        result = self.runner.run_result(
            self._compose_command(
                "up",
                "--no-deps",
                "--abort-on-container-exit",
                "--exit-code-from",
                "migrate",
                "migrate",
            ),
            timeout_seconds=1800,
        )
        if result.returncode != 0:
            reason, exception_type = self._record_migration_failure(result)
            raise ControllerError(f"migration_failed:{reason}:{exception_type}")
        current = self._compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "smartscan",
            "-d",
            "smartscan",
            "-Atqc",
            "SELECT version_num FROM alembic_version",
        ).strip()
        _require(current == MIGRATION_TARGET, "migration_target_mismatch")
        latest_object = self._compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "smartscan",
            "-d",
            "smartscan",
            "-Atqc",
            "SELECT to_regclass('public.ai_media_grants')::text",
        ).strip()
        _require(latest_object == "ai_media_grants", "migration_latest_object_missing")
        self.verify_database()
        return self._record(
            "migrations_completed",
            {
                "target_revision": MIGRATION_TARGET,
                "storage_root": MIGRATION_STORAGE_ROOT,
                "real_business_storage_mounted": False,
                "raw_output_retained": False,
            },
        )

    def start_core(self) -> dict[str, Any]:
        self._require_steps("migrations_completed")
        candidate = _load_json(
            self.paths.candidate_release,
            policy=FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600,
            expected_deploy_uid=self.deploy_uid,
        )
        active, _ = self._fixed_release()
        changed_service = candidate["changed_services"][0]
        expected_image = next(
            item for item in candidate["images"] if item["service"] == changed_service
        )
        active_image = next(item for item in active["images"] if item["service"] == changed_service)
        _require(active_image == expected_image, f"repaired_{changed_service}_release_not_active")
        if self._completed("core_started"):
            return self.verify_core()
        self._compose(
            "up",
            "-d",
            "--no-deps",
            "api",
            "worker-cpu-1",
            "worker-cpu-2",
            "nginx",
            "loopback-proxy",
        )
        result = self._record("core_started")
        state = self._state()
        state.pop("core_stop_checkpoint", None)
        _atomic_json(self.paths.state_file, state)
        return result

    def _wait_core_health(self) -> None:
        """验证核心运行时，不推进状态；供增量激活和显式门禁复用。"""

        required = {
            "postgres",
            "api",
            "worker-cpu-1",
            "worker-cpu-2",
            "nginx",
            "loopback-proxy",
        }
        last_reason = "core_services_not_running"
        for _ in range(90):
            try:
                running = set(self._compose("ps", "--status", "running", "--services").splitlines())
                _require(required.issubset(running), "core_services_not_running")
                _require(
                    "worker-ai" not in running and "ai-gateway" not in running,
                    "ai_profile_started",
                )
                worker_count = self._compose(
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "smartscan",
                    "-d",
                    "smartscan",
                    "-Atqc",
                    "SELECT count(*) FROM worker_heartbeats "
                    "WHERE heartbeat_at >= CURRENT_TIMESTAMP - INTERVAL '120 seconds'",
                ).strip()
                _require(worker_count.isdigit() and int(worker_count) >= 2, "worker_health_pending")
                proxy_id = self._compose("ps", "-q", "loopback-proxy").strip()
                web_id = self._compose("ps", "-q", "nginx").strip()
                _require(proxy_id and web_id, "web_runtime_missing")
                proxy_runtime = json.loads(
                    self.runner.run(["/usr/bin/docker", "inspect", proxy_id])
                )[0]
                web_runtime = json.loads(self.runner.run(["/usr/bin/docker", "inspect", web_id]))[0]
                _require(
                    proxy_runtime["NetworkSettings"]["Ports"].get("8080/tcp")
                    == [{"HostIp": "127.0.0.1", "HostPort": "18082"}],
                    "loopback_port_not_published",
                )
                _require(
                    set(web_runtime["NetworkSettings"]["Networks"]) == {"smartscan-uat-edge"},
                    "web_network_boundary_invalid",
                )
                _require(
                    set(proxy_runtime["NetworkSettings"]["Networks"])
                    == {"smartscan-uat-edge", "smartscan-uat-publish"},
                    "loopback_proxy_network_boundary_invalid",
                )
                _require(
                    proxy_runtime["HostConfig"]["ReadonlyRootfs"] is True
                    and proxy_runtime["HostConfig"]["CapDrop"] == ["ALL"]
                    and proxy_runtime["Config"]["User"] == "101:101"
                    and proxy_runtime.get("Mounts") == [],
                    "loopback_proxy_hardening_invalid",
                )
                _require(
                    web_runtime["HostConfig"]["ReadonlyRootfs"] is True
                    and not web_runtime["HostConfig"].get("PortBindings")
                    and web_runtime["HostConfig"]["NanoCpus"] == 250_000_000
                    and web_runtime["HostConfig"]["Memory"] == 128 * 1024**2
                    and web_runtime["HostConfig"]["PidsLimit"] == 64,
                    "web_resource_contract_invalid",
                )
                _require(
                    proxy_runtime["HostConfig"]["NanoCpus"] == 100_000_000
                    and proxy_runtime["HostConfig"]["Memory"] == 64 * 1024**2
                    and proxy_runtime["HostConfig"]["PidsLimit"] == 32
                    and set(proxy_runtime["HostConfig"].get("Tmpfs", {})) == {"/tmp"}
                    and proxy_runtime["HostConfig"]["LogConfig"]
                    == {"Type": "json-file", "Config": {"max-file": "3", "max-size": "10m"}},
                    "loopback_proxy_resource_contract_invalid",
                )
                for service in ("api", "worker-cpu-1", "worker-cpu-2", "nginx", "loopback-proxy"):
                    container_id = self._compose("ps", "-q", service).strip()
                    runtime = json.loads(
                        self.runner.run(["/usr/bin/docker", "inspect", container_id])
                    )[0]
                    _require(
                        runtime.get("State", {}).get("Health", {}).get("Status") == "healthy",
                        f"core_service_health_pending:{service}",
                    )
                sensitive_names = ("PASSWORD", "SECRET", "TOKEN", "DATABASE_URL")
                _require(
                    not any(
                        any(name in item.split("=", 1)[0].upper() for name in sensitive_names)
                        for item in proxy_runtime["Config"].get("Env", [])
                    ),
                    "loopback_proxy_secret_exposure",
                )
                processes = self.runner.run(
                    ["/usr/bin/docker", "top", web_id, "-eo", "comm"]
                ).splitlines()
                _require(1 < len(processes) <= 5, "web_process_count_invalid")
                memory_text = self.runner.run(
                    [
                        "/usr/bin/docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{.MemPerc}}",
                        web_id,
                    ]
                ).strip()
                _require(memory_text.endswith("%"), "web_memory_metric_invalid")
                _require(float(memory_text[:-1]) < 80.0, "web_memory_headroom_insufficient")
                log_result = self.runner.run_result(
                    ["/usr/bin/docker", "logs", "--since", "5m", web_id]
                )
                recent_logs = f"{log_result.stdout}\n{log_result.stderr}"
                _require("sendmsg() failed" not in recent_logs, "web_sendmsg_failure_detected")
                published = self.runner.run(
                    ["/usr/bin/docker", "port", proxy_id, "8080/tcp"]
                ).strip()
                _require(published == "127.0.0.1:18082", "loopback_port_binding_invalid")
                with urllib.request.urlopen("http://127.0.0.1:18082/", timeout=5) as response:
                    _require(response.status < 500, "core_http_failed")
                last_reason = ""
                break
            except (ControllerError, OSError) as exc:
                last_reason = str(exc) if isinstance(exc, ControllerError) else "core_http_pending"
                time.sleep(2)
        _require(not last_reason, f"core_health_timeout:{last_reason}")

    def verify_core(self) -> dict[str, Any]:
        self._require_steps("core_started")
        self._wait_core_health()
        return self._record("core_verified")

    def stage_nginx(self) -> dict[str, Any]:
        self._require_steps("core_verified")
        _require(
            self.paths.nginx_template.is_file() and not self.paths.nginx_template.is_symlink(),
            "nginx_template_invalid",
        )
        if self.paths.staged_nginx.exists():
            _require(
                _sha256(self.paths.staged_nginx) == _sha256(self.paths.nginx_template),
                "staged_nginx_changed",
            )
        else:
            shutil.copyfile(self.paths.nginx_template, self.paths.staged_nginx)
            os.chmod(self.paths.staged_nginx, 0o600)
        return self._record("nginx_staged")

    def activate_nginx(self) -> dict[str, Any]:
        self._require_steps("nginx_staged")
        plan = _load_json(
            self.paths.activation_plan,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        _require(plan.get("confirmed") is True, "nginx_confirmation_missing")
        target = Path(str(plan.get("server_config", "")))
        _require(
            target.is_absolute() and target != Path("/etc/nginx/nginx.conf"),
            "nginx_target_invalid",
        )
        _require(Path("/etc/nginx") in target.parents, "nginx_target_outside_fixed_root")
        _require(target.is_file() and not target.is_symlink(), "nginx_target_invalid")
        target_info = target.stat()
        _require(
            target_info.st_uid == self.root_uid
            and target_info.st_gid == self.root_uid
            and stat.S_IMODE(target_info.st_mode) & 0o022 == 0,
            "nginx_target_permissions_invalid",
        )
        _require(
            SHA256.fullmatch(str(plan.get("current_sha256", ""))) is not None,
            "nginx_current_digest_invalid",
        )
        _require(
            SHA256.fullmatch(str(plan.get("updated_sha256", ""))) is not None,
            "nginx_updated_digest_invalid",
        )
        _require(
            self.paths.prepared_nginx_config.is_file()
            and not self.paths.prepared_nginx_config.is_symlink(),
            "nginx_prepared_config_invalid",
        )
        prepared = self.paths.prepared_nginx_config
        prepared_info = prepared.stat()
        _require(
            prepared_info.st_uid == self.root_uid
            and prepared_info.st_gid == self.root_uid
            and stat.S_IMODE(prepared_info.st_mode) == 0o600
            and prepared_info.st_nlink == 1,
            "nginx_prepared_config_permissions_invalid",
        )
        _require(
            _sha256(prepared) == plan["updated_sha256"],
            "nginx_updated_digest_mismatch",
        )
        include_line = "include /etc/nginx/snippets/smartscan-uat-8077.locations.conf;"
        _require(
            prepared.read_text(encoding="utf-8").count(include_line) == 1,
            "nginx_include_binding_invalid",
        )
        if self._completed("nginx_activated"):
            _require(
                _sha256(target) == plan["updated_sha256"]
                and self.paths.active_nginx.is_file()
                and not self.paths.active_nginx.is_symlink()
                and _sha256(self.paths.active_nginx) == _sha256(self.paths.nginx_template),
                "nginx_active_state_changed",
            )
            self.runner.run(["/usr/sbin/nginx", "-t"])
            return self._record("nginx_activated")
        _require(_sha256(target) == plan["current_sha256"], "nginx_current_digest_mismatch")
        _require(
            not self.paths.active_nginx.exists() and not self.paths.active_nginx.is_symlink(),
            "nginx_target_exists",
        )
        _require(
            not self.paths.nginx_backup.exists() and not self.paths.nginx_backup.is_symlink(),
            "nginx_backup_exists",
        )
        _require(
            self.paths.active_nginx.parent.is_dir()
            and not self.paths.active_nginx.parent.is_symlink(),
            "nginx_snippet_directory_invalid",
        )
        shutil.copyfile(target, self.paths.nginx_backup)
        os.chown(self.paths.nginx_backup, self.root_uid, self.root_uid)
        os.chmod(self.paths.nginx_backup, 0o600)
        replacement = target.with_name(f".{target.name}.smartscan-uat.tmp")
        _require(not replacement.exists() and not replacement.is_symlink(), "nginx_temp_exists")
        try:
            shutil.copyfile(self.paths.staged_nginx, self.paths.active_nginx)
            os.chown(self.paths.active_nginx, self.root_uid, self.root_uid)
            os.chmod(self.paths.active_nginx, 0o644)
            shutil.copyfile(prepared, replacement)
            os.chown(replacement, target_info.st_uid, target_info.st_gid)
            os.chmod(replacement, stat.S_IMODE(target_info.st_mode))
            os.replace(replacement, target)
            self.runner.run(["/usr/sbin/nginx", "-t"])
            self.runner.run(["/usr/sbin/nginx", "-s", "reload"])
        except (ControllerError, OSError, subprocess.SubprocessError):
            replacement.unlink(missing_ok=True)
            shutil.copyfile(self.paths.nginx_backup, replacement)
            os.chown(replacement, target_info.st_uid, target_info.st_gid)
            os.chmod(replacement, stat.S_IMODE(target_info.st_mode))
            os.replace(replacement, target)
            self.paths.active_nginx.unlink(missing_ok=True)
            self.runner.run(["/usr/sbin/nginx", "-t"])
            self.runner.run(["/usr/sbin/nginx", "-s", "reload"])
            raise ControllerError("nginx_activation_rolled_back") from None
        return self._record("nginx_activated")

    def verify_uat(self) -> dict[str, Any]:
        self._require_steps("nginx_activated")
        with urllib.request.urlopen("http://127.0.0.1:8077/smartscan/", timeout=10) as response:
            _require(response.status < 500, "shared_entry_failed")
        return self._record("basic_uat_verified")

    def stop_core(self) -> dict[str, Any]:
        _require(not self._completed("nginx_activated"), "shared_nginx_already_activated")
        self._compose(
            "stop",
            "loopback-proxy",
            "nginx",
            "worker-cpu-2",
            "worker-cpu-1",
            "api",
        )
        state = self._state()
        completed = state.get("completed", [])
        _require(isinstance(completed, list), "state_completed_invalid")
        state["completed"] = [
            item for item in completed if item not in {"core_started", "core_verified"}
        ]
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["core_stop_checkpoint"] = {
            "status": "passed",
            "recorded_at": recorded_at,
            "database_preserved": True,
            "migrations_preserved": True,
            "active_release_preserved": True,
        }
        state["history"] = [
            *state.get("history", []),
            {
                "step": "core_stopped",
                "recorded_at": recorded_at,
                "database_preserved": True,
                "migrations_preserved": True,
                "active_release_preserved": True,
            },
        ][-100:]
        _atomic_json(self.paths.state_file, state)
        return {
            "status": "passed",
            "step": "core_stopped",
            "next_required": "core_started",
            "secrets_included": False,
        }

    def rollback_images(self) -> dict[str, Any]:
        state = self._state()
        checkpoint = state.get("core_stop_checkpoint")
        _require(
            isinstance(checkpoint, dict)
            and checkpoint.get("status") == "passed"
            and not self._completed("core_started"),
            "core_stop_checkpoint_missing",
        )
        pending = state.get("pending_release_update")
        web_update = (
            isinstance(pending, dict)
            and pending.get("changed_services") == ["web"]
            and pending.get("status") == "activated"
        )
        if web_update:
            rollback_paths = (
                self.paths.previous_web_release,
                self.paths.previous_web_map,
                self.paths.previous_web_local_images,
                self.paths.previous_web_identities,
            )
        else:
            rollback_paths = (
                self.paths.previous_release,
                self.paths.previous_map,
                self.paths.previous_local_images,
                self.paths.previous_identities,
            )
        previous_release_path, previous_map_path, previous_env_path, previous_identities_path = (
            rollback_paths
        )
        previous_release = _load_json(
            previous_release_path,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        previous_map = _load_json(
            previous_map_path,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        previous_identities = _load_json(
            previous_identities_path,
            policy=FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=self.root_uid,
        )
        _require(previous_release.get("platform") == PLATFORM, "previous_release_platform_invalid")
        _require(previous_map.get("platform") == PLATFORM, "previous_release_map_platform_invalid")
        by_service = {
            item.get("service"): item
            for item in previous_map.get("images", [])
            if isinstance(item, dict)
        }
        identities = previous_identities.get("images")
        _require(
            set(by_service) == EXPECTED_SERVICES and isinstance(identities, dict),
            "previous_release_evidence_invalid",
        )
        expected_env: list[str] = []
        for image in previous_release.get("images", []):
            _require(isinstance(image, dict), "previous_release_invalid")
            service = image.get("service")
            record = by_service.get(service)
            identity_record = identities.get(image.get("deploy_key"))
            _require(
                service in EXPECTED_SERVICES
                and isinstance(record, dict)
                and isinstance(identity_record, dict),
                "previous_release_invalid",
            )
            runtime = self._inspect_runtime_image(
                image,
                record,
                self.paths.upload_root / str(image["archive_name"]),
            )
            _require(
                identity_record.get("runtime_image_id") == runtime.runtime_image_id
                and identity_record.get("runtime_descriptor_digest")
                == runtime.runtime_descriptor_digest
                and identity_record.get("local_tag") == image.get("local_tag"),
                f"previous_release_image_missing:{service}",
            )
            expected_env.append(f"{image['runtime_key']}={image['local_tag']}")
        _require(
            previous_env_path.read_text(encoding="utf-8") == "\n".join(expected_env) + "\n",
            "previous_release_env_invalid",
        )
        for source, destination in (
            (previous_release_path, self.paths.installed_release),
            (previous_map_path, self.paths.installed_map),
            (previous_env_path, self.paths.local_images_env),
            (previous_identities_path, self.paths.image_identities),
        ):
            temporary = destination.with_name(f".{destination.name}.rollback.tmp")
            _require(not temporary.exists() and not temporary.is_symlink(), "rollback_temp_exists")
            shutil.copyfile(source, temporary)
            if hasattr(os, "chown"):
                os.chown(temporary, self.root_uid, self.root_uid)
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        if isinstance(pending, dict):
            pending["status"] = "rolled_back"
            pending["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _atomic_json(self.paths.state_file, state)
        return self._record("images_rolled_back", {"core_restart_allowed": False})

    def resume_basic_uat(self) -> dict[str, Any]:
        steps = (
            ("preflight", self.preflight),
            ("storage_verified", self.verify_storage),
            ("models_verified", self.verify_models),
            ("config_verified", self.verify_config),
            ("release_accepted", self.accept_release),
            ("images_imported", self.import_images),
            ("images_verified", self.verify_images),
            ("identities_verified", self.probe_identities),
            ("ownership_applied", self.apply_ownership),
            ("database_started", self.start_database),
            ("database_verified", self.verify_database),
        )
        for name, action in steps:
            if not self._completed(name):
                action()
        if not self._completed("migrations_completed"):
            return {
                "status": "waiting_confirmation",
                "next_required": "run-migrations",
                "secrets_included": False,
            }
        pending = self._state().get("pending_release_update")
        if isinstance(pending, dict) and pending.get("status") in {"accepted", "verified"}:
            self._activate_pending_release()
        for name, action in (
            ("core_started", self.start_core),
            ("core_verified", self.verify_core),
        ):
            if not self._completed(name):
                action()
        return {"status": "passed", "next_required": "stage-nginx", "secrets_included": False}

    def execute(self, command: str) -> dict[str, Any]:
        actions = {
            "status": self.status,
            "preflight": self.preflight,
            "verify-storage": self.verify_storage,
            "verify-models": self.verify_models,
            "verify-config": self.verify_config,
            "accept-release": self.accept_release,
            "import-images": self.import_images,
            "verify-images": self.verify_images,
            "probe-identities": self.probe_identities,
            "apply-ownership": self.apply_ownership,
            "start-database": self.start_database,
            "verify-database": self.verify_database,
            "run-migrations": self.run_migrations,
            "start-core": self.start_core,
            "verify-core": self.verify_core,
            "stage-nginx": self.stage_nginx,
            "activate-nginx": self.activate_nginx,
            "verify-uat": self.verify_uat,
            "stop-core": self.stop_core,
            "rollback-images": self.rollback_images,
            "resume-basic-uat": self.resume_basic_uat,
        }
        return actions[command]()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in COMMANDS:
        print("status=failed\nreason=command_not_allowed", file=sys.stderr)
        return 64
    try:
        result = Controller().execute(arguments[0])
    except (
        ControllerError,
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        print(
            json.dumps(
                {"status": "failed", "reason": str(exc), "secrets_included": False},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
