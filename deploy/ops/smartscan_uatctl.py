#!/usr/bin/env python3
"""SmartScan UAT 单用途、状态机式部署控制器。

控制器没有通用命令入口；所有路径、Compose 项目、服务和外部命令均固定。
它只输出脱敏 JSON，任何失败都保留现场并停止，不执行清理或 prune。
"""

from __future__ import annotations

import hashlib
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
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

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
EXPECTED_SERVICES = {"postgres", "api", "worker", "ai-gateway", "web", "ops"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LOCAL_TAG = re.compile(r"^smartscan-uat-[a-z0-9-]+:sha256-[0-9a-f]{12}$")
ARCHIVE_NAME = re.compile(r"^smartscan-[a-z0-9-]+-[0-9a-f]{12}-linux-amd64\.oci\.tar$")
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
INSTALLED_ASSET_SHA256 = {
    "docker-compose.uat.yml": "50e60e56c9c1652fe7bbdefbabee83e7af5e0efd93ff620b4d8b26ac0252883c",
    "shared-8077-smartscan-location.conf": "8f640d848623f51518130b687520a255e26b79f8625ccd3fdc48995b1d14edec",
    "smartscan-uat-config": "58e750bd3217bf1c3fae6ac30c5d6cc50829b72d563016c580e2ad9d229787ab",
}


class ControllerError(RuntimeError):
    """状态或固定对象不满足失败关闭条件。"""


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
    deploy_env: Path = Path("/etc/smartscan/uat/deploy.env")
    runtime_env: Path = Path("/etc/smartscan/uat/runtime.env")
    activation_plan: Path = Path("/etc/smartscan/uat/nginx-activation.json")
    staged_nginx: Path = Path("/etc/smartscan/uat/nginx-smartscan-8077.locations.conf")
    prepared_nginx_config: Path = Path("/etc/smartscan/uat/nginx-8077-server.updated.conf")
    nginx_backup: Path = Path("/etc/smartscan/uat/nginx-8077-server.original.conf")
    active_nginx: Path = Path("/etc/nginx/snippets/smartscan-uat-8077.locations.conf")
    compose_file: Path = Path("/usr/local/libexec/smartscan/docker-compose.uat.yml")
    nginx_template: Path = Path("/usr/local/libexec/smartscan/shared-8077-smartscan-location.conf")
    config_helper: Path = Path("/usr/local/libexec/smartscan/smartscan-uat-config")
    loop_executor: Path = Path("/usr/local/libexec/smartscan/smartscan-uat-loop-storage")
    model_executor: Path = Path("/usr/local/libexec/smartscan/smartscan-uat-ocr-model")


class Runner(Protocol):
    def run(self, arguments: list[str], *, check: bool = True) -> str: ...


class SubprocessRunner:
    def run(self, arguments: list[str], *, check: bool = True) -> str:
        process = subprocess.run(arguments, text=True, capture_output=True, check=False)
        if check and process.returncode != 0:
            raise ControllerError(f"command_failed:{Path(arguments[0]).name}")
        return process.stdout.strip()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ControllerError(reason)


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


def _load_json(
    path: Path, *, root_owned: bool = True, expected_root_uid: int = 0
) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"fixed_json_invalid:{path.name}")
    if os.name != "nt":
        info = path.stat()
        if root_owned:
            _require(
                info.st_uid == expected_root_uid and info.st_gid == expected_root_uid,
                f"fixed_json_owner_invalid:{path.name}",
            )
        _require(stat.S_IMODE(info.st_mode) == 0o600, f"fixed_json_mode_invalid:{path.name}")
        _require(info.st_nlink == 1, f"fixed_json_links_invalid:{path.name}")
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
    ) -> None:
        self.paths = paths
        self.runner = runner or SubprocessRunner()
        self.root_uid = root_uid
        self.deploy_uid = deploy_uid

    def _state(self) -> dict[str, Any]:
        if not self.paths.state_file.exists():
            return _initial_state()
        return _load_json(self.paths.state_file, expected_root_uid=self.root_uid)

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

    def _fixed_release(self, *, uploaded: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata_root = self.paths.upload_root if uploaded else self.paths.config_root
        release = _load_json(
            metadata_root / "release-manifest.json",
            root_owned=not uploaded,
            expected_root_uid=self.root_uid,
        )
        mapping = _load_json(
            metadata_root / "release-map.json",
            root_owned=not uploaded,
            expected_root_uid=self.root_uid,
        )
        if uploaded and os.name != "nt":
            for name in ("release-manifest.json", "release-map.json"):
                _require(
                    (metadata_root / name).stat().st_uid == self.deploy_uid,
                    f"uploaded_metadata_owner_invalid:{name}",
                )
        _require(release.get("schema_version") == "1.0", "release_schema_invalid")
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
            archive = self.paths.upload_root / archive_name
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
            expected = {"oci-layout", "index.json"} | {
                f"blobs/sha256/{value[7:]}"
                for value in {source_digest, platform_digest, config_digest, *layer_digests}
            }
            _require(set(members) == expected, "archive_member_set_invalid")
            index = _tar_json(bundle, members["index.json"], "archive_index_invalid")
            descriptors = index.get("manifests")
            _require(
                isinstance(descriptors, list)
                and len(descriptors) == 1
                and descriptors[0].get("digest") == platform_digest
                and descriptors[0].get("annotations", {}).get("org.opencontainers.image.ref.name")
                == image["local_tag"],
                "archive_index_binding_invalid",
            )
            for digest in {source_digest, platform_digest, config_digest, *layer_digests}:
                name = f"blobs/sha256/{digest[7:]}"
                stream = bundle.extractfile(members[name])
                _require(stream is not None, "archive_blob_missing")
                _require(_stream_sha256(stream) == digest[7:], "archive_blob_digest_invalid")
            source = _tar_json(
                bundle,
                members[f"blobs/sha256/{source_digest[7:]}"],
                "archive_source_invalid",
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
                members[f"blobs/sha256/{platform_digest[7:]}"],
                "archive_platform_manifest_invalid",
            )
            _require(
                platform.get("config", {}).get("digest") == config_digest,
                "archive_config_unbound",
            )
            _require(
                [item.get("digest") for item in platform.get("layers", [])] == layer_digests,
                "archive_layers_unbound",
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
        for path in (self.paths.compose_file, self.paths.nginx_template, self.paths.config_helper):
            _require(
                path.is_file() and not path.is_symlink(), f"installed_asset_invalid:{path.name}"
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
        output = self.runner.run([str(self.paths.loop_executor), "verify"])
        _require(
            "status=passed" in output or '"status":"passed"' in output, "storage_verify_failed"
        )
        return self._record("storage_verified")

    def verify_models(self) -> dict[str, Any]:
        output = self.runner.run([str(self.paths.model_executor), "verify"])
        _require("status=passed" in output or '"status":"passed"' in output, "model_verify_failed")
        return self._record("models_verified")

    def verify_config(self) -> dict[str, Any]:
        output = self.runner.run(["/usr/bin/python3", str(self.paths.config_helper), "verify"])
        document = json.loads(output)
        _require(document.get("status") == "passed", "config_verify_failed")
        return self._record("config_verified")

    def accept_release(self) -> dict[str, Any]:
        self._require_steps("preflight", "storage_verified", "models_verified", "config_verified")
        release, mapping = self._fixed_release(uploaded=True)
        if self._completed("release_accepted"):
            installed_release, installed_map = self._fixed_release(uploaded=False)
            _require(
                installed_release == release and installed_map == mapping,
                "accepted_release_changed",
            )
            return self.status()
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
        return self.runner.run(
            [
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
        )

    def import_images(self) -> dict[str, Any]:
        self._require_steps("release_accepted")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        for image in release["images"]:
            service, tag = image["service"], image["local_tag"]
            expected = by_service[service]["image_id"]
            current = self.runner.run(
                ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", tag], check=False
            )
            if current:
                _require(current == expected, f"local_tag_collision:{service}")
                continue
            self.runner.run(
                [
                    "/usr/bin/docker",
                    "load",
                    "--input",
                    str(self.paths.upload_root / image["archive_name"]),
                ]
            )
            actual = self.runner.run(
                ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", tag]
            )
            _require(actual == expected, f"imported_image_id_mismatch:{service}")
        return self._record("images_imported")

    def verify_images(self) -> dict[str, Any]:
        self._require_steps("images_imported")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        lines: list[str] = []
        for image in release["images"]:
            service, tag, runtime_key = image["service"], image["local_tag"], image["runtime_key"]
            actual = self.runner.run(
                ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", tag]
            )
            _require(
                actual == by_service[service]["image_id"], f"local_tag_image_id_mismatch:{service}"
            )
            lines.append(f"{runtime_key}={tag}")
        _atomic_text(self.paths.local_images_env, "\n".join(lines) + "\n")
        config = self._compose("config", "--images")
        _require(
            all(image["local_tag"] in config.splitlines() for image in release["images"]),
            "compose_offline_mapping_invalid",
        )
        return self._record("images_verified")

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
            document = _load_json(self.paths.image_identities, expected_root_uid=self.root_uid)
            _require(
                document.get("schema_version") == "1.0" and document.get("platform") == PLATFORM,
                "identity_evidence_changed",
            )
            return self._record("identities_verified")
        release, mapping = self._fixed_release()
        by_service = {item["service"]: item for item in mapping["images"]}
        images: dict[str, Any] = {}
        for image in release["images"]:
            service, record = image["service"], by_service[image["service"]]
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
                "local_tag": image["local_tag"],
                "image_id": record["image_id"],
                "archive_sha256": record["archive_sha256"],
                "config_user": user,
                "runtime_uid": uid,
                "runtime_gid": gid,
                "identity_method": method,
            }
        document = {
            "schema_version": "1.0",
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": PLATFORM,
            "images": images,
            "secrets_included": False,
        }
        _atomic_json(self.paths.image_identities, document)
        return self._record("identities_verified")

    def apply_ownership(self) -> dict[str, Any]:
        self._require_steps("identities_verified")
        document = _load_json(self.paths.image_identities, expected_root_uid=self.root_uid)
        _require(document.get("schema_version") == "1.0", "identity_schema_invalid")
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
            valid_mapping = (
                isinstance(record, dict)
                and record.get("reference") == image["source"]
                and record.get("repo_digest_verified") is False
                and record.get("source_digest_verified") is True
                and record.get("offline_mapping_verified") is True
                and record.get("archive_sha256") == expected["archive_sha256"]
                and record.get("image_id") == expected["image_id"]
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

    def start_database(self) -> dict[str, Any]:
        self._require_steps("ownership_applied")
        if self._completed("database_started"):
            return self.verify_database()
        self._compose("up", "-d", "--no-deps", "postgres")
        return self._record("database_started")

    def verify_database(self) -> dict[str, Any]:
        self._require_steps("database_started")
        self._compose("exec", "-T", "postgres", "pg_isready", "-U", "smartscan", "-d", "smartscan")
        return self._record("database_verified")

    def run_migrations(self) -> dict[str, Any]:
        self._require_steps("database_verified")
        if self._completed("migrations_completed"):
            self.verify_database()
            return self._record("migrations_completed")
        self._compose("run", "--rm", "--no-deps", "migrate")
        return self._record("migrations_completed")

    def start_core(self) -> dict[str, Any]:
        self._require_steps("migrations_completed")
        if self._completed("core_started"):
            return self.verify_core()
        self._compose("up", "-d", "--no-deps", "api", "worker-cpu-1", "worker-cpu-2", "nginx")
        return self._record("core_started")

    def verify_core(self) -> dict[str, Any]:
        self._require_steps("core_started")
        self._compose("ps", "--status", "running", "--services")
        with urllib.request.urlopen("http://127.0.0.1:18082/", timeout=5) as response:
            _require(response.status < 500, "core_http_failed")
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
        plan = _load_json(self.paths.activation_plan, expected_root_uid=self.root_uid)
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
        self._compose("stop", "nginx", "worker-cpu-2", "worker-cpu-1", "api")
        return self._record("core_stopped")

    def rollback_images(self) -> dict[str, Any]:
        self._require_steps("core_stopped")
        previous = self.paths.config_root / "previous-release-map.json"
        document = _load_json(previous, expected_root_uid=self.root_uid)
        _require(document.get("platform") == PLATFORM, "previous_release_platform_invalid")
        for item in document.get("images", []):
            _require(
                isinstance(item, dict) and LOCAL_TAG.fullmatch(str(item.get("local_tag", ""))),
                "previous_release_invalid",
            )
            current = self.runner.run(
                [
                    "/usr/bin/docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    str(item["local_tag"]),
                ]
            )
            _require(current == item.get("image_id"), "previous_release_image_missing")
        return self._record("images_rolled_back")

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
