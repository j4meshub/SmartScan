from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

try:
    import pwd
except ImportError:  # pragma: no cover - 生产安装器仅运行于Linux
    pwd = None  # type: ignore[assignment]

STAGING_ROOT = Path("/mnt/data/smartscan/uat/models/.ocr-staging/PP-OCRv6-small-v1")
TARGET_ROOT = Path("/mnt/data/smartscan/uat/models/ocr")
MAX_ARTIFACT_BYTES = 4 * 1024**3
EXPECTED_DIRS = ("PP-OCRv6_small_det", "PP-OCRv6_small_rec")
EXPECTED_EVIDENCE = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM_MODEL_DESCRIPTION.md",
    "source-lock.json",
)


class InstallError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _load_manifest(root: Path) -> dict[str, object]:
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise InstallError("manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError("manifest_invalid") from exc
    required = {
        "schema_version": 1,
        "artifact_kind": "smartscan-offline-ocr-models",
        "artifact_version": "PP-OCRv6-small-v1",
        "backend": "paddle_static",
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": "PP-OCRv6-small-v1",
        "license": "Apache-2.0",
        "text_detection_dir": EXPECTED_DIRS[0],
        "text_recognition_dir": EXPECTED_DIRS[1],
    }
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in required.items()
    ):
        raise InstallError("manifest_contract_invalid")
    return manifest


def verify_tree(root: Path, *, installed: bool, expected_uid: int = 0) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise InstallError("root_invalid")
    manifest = _load_manifest(root)
    files = manifest.get("files")
    file_metadata = manifest.get("file_metadata")
    evidence = manifest.get("evidence_files")
    if (
        not isinstance(files, dict)
        or not isinstance(file_metadata, dict)
        or not isinstance(evidence, dict)
    ):
        raise InstallError("manifest_files_invalid")
    if set(evidence) != set(EXPECTED_EVIDENCE):
        raise InstallError("evidence_incomplete")
    expected = set(files) | set(evidence) | {"manifest.json"}
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InstallError("symlink_rejected")
        if path.is_file():
            if path.stat(follow_symlinks=False).st_nlink != 1:
                raise InstallError("hardlink_rejected")
            relative = path.relative_to(root).as_posix()
            if relative in actual:
                raise InstallError("duplicate_file")
            actual.add(relative)
        elif not path.is_dir():
            raise InstallError("special_file_rejected")
    if actual != expected:
        raise InstallError("file_set_mismatch")
    total = 0
    if files != {name: metadata.get("sha256") for name, metadata in file_metadata.items()}:
        raise InstallError("manifest_compatibility_mismatch")
    for relative, metadata in {**file_metadata, **evidence}.items():
        if not isinstance(relative, str) or not isinstance(metadata, dict):
            raise InstallError("manifest_entry_invalid")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise InstallError("file_invalid")
        if path.stat().st_size != metadata.get("size") or _digest(path) != metadata.get("sha256"):
            raise InstallError("checksum_mismatch")
        total += path.stat().st_size
    if total > MAX_ARTIFACT_BYTES:
        raise InstallError("artifact_too_large")
    if installed and os.name != "nt":
        for path in [root, *root.rglob("*")]:
            info = path.stat()
            if (
                info.st_uid != expected_uid
                or info.st_gid != expected_uid
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise InstallError("installed_permissions_invalid")
    return {"status": "passed", "artifact_version": "PP-OCRv6-small-v1", "bytes": total}


def _verify_staging_permissions(root: Path, deploy_uid: int | None = None) -> None:
    if pwd is None:
        raise InstallError("posix_identity_unavailable")
    allowed_uids = {0, pwd.getpwnam("szhzx").pw_uid if deploy_uid is None else deploy_uid}
    for path in [root, *root.rglob("*")]:
        info = path.stat(follow_symlinks=False)
        if info.st_uid not in allowed_uids or stat.S_IMODE(info.st_mode) & 0o022:
            raise InstallError("staging_permissions_invalid")


def _copy_regular_no_follow(source: Path, destination: Path) -> None:
    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise InstallError("source_changed_during_install")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o400,
        )
        try:
            with (
                os.fdopen(os.dup(source_fd), "rb") as source_stream,
                os.fdopen(os.dup(destination_fd), "wb") as destination_stream,
            ):
                shutil.copyfileobj(source_stream, destination_stream)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def install_fixed(
    staging: Path = STAGING_ROOT,
    target: Path = TARGET_ROOT,
    *,
    deploy_uid: int | None = None,
    target_uid: int = 0,
) -> dict[str, object]:
    verify_tree(staging, installed=False)
    if os.name != "nt":
        _verify_staging_permissions(staging, deploy_uid)
    if target.is_symlink() or not target.is_dir():
        raise InstallError("target_invalid")
    if any(target.iterdir()):
        raise InstallError("target_not_empty")
    manifest = _load_manifest(staging)
    listed = sorted(set(manifest["files"]) | set(manifest["evidence_files"]) | {"manifest.json"})
    try:
        for relative in listed:
            source = staging / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_regular_no_follow(source, destination)
        for directory in [target, *[item for item in target.rglob("*") if item.is_dir()]]:
            os.chown(directory, 0, 0)
            directory.chmod(0o755)
        for path in [item for item in target.rglob("*") if item.is_file()]:
            os.chown(path, 0, 0)
            path.chmod(0o444)
        return verify_tree(target, installed=True, expected_uid=target_uid)
    except Exception as exc:
        raise InstallError("partial_install_requires_separate_cleanup_authorization") from exc


def status_fixed(target: Path = TARGET_ROOT) -> dict[str, object]:
    if target.is_symlink() or not target.is_dir():
        return {"status": "absent_or_invalid", "installed": False}
    if not any(target.iterdir()):
        return {"status": "empty", "installed": False}
    try:
        result = verify_tree(target, installed=True)
    except InstallError as exc:
        return {"status": "partial_or_invalid", "installed": False, "reason": str(exc)}
    return {**result, "installed": True}
