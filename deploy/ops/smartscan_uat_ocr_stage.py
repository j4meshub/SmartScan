from __future__ import annotations

import json
import os
import stat
import tarfile
from pathlib import Path

try:
    import pwd
except ImportError:  # pragma: no cover - 生产暂存器仅运行于Linux
    pwd = None  # type: ignore[assignment]

try:  # 安装后的固定模块路径
    from smartscan_ocr_layer_contract import (
        ARCHIVE_PREFIX,
        LAYER_SHA256,
        LAYER_SIZE,
        LayerContractError,
        inspect_layer_members,
        verify_layer_archive,
    )
    from smartscan_uat_ocr_model import InstallError, verify_tree
except ImportError:  # 仓库测试路径
    from deploy.ops.smartscan_ocr_layer_contract import (
        ARCHIVE_PREFIX,
        LAYER_SHA256,
        LAYER_SIZE,
        LayerContractError,
        inspect_layer_members,
        verify_layer_archive,
    )
    from deploy.ops.smartscan_uat_ocr_model import InstallError, verify_tree

UPLOAD_LAYER = Path(
    "/home/szhzx/smartscan-ocr-offline-transfer/smartscan-ocr-layer-fdae8d61585e.tar.gz"
)
STAGING_ROOT = Path("/mnt/data/smartscan/uat/models/.ocr-staging/PP-OCRv6-small-v1")
PARTIAL_ROOT = STAGING_ROOT.with_name(f"{STAGING_ROOT.name}.partial")


class StageError(RuntimeError):
    pass


def _deploy_uid() -> int:
    if pwd is None:
        raise StageError("posix_identity_unavailable")
    return pwd.getpwnam("szhzx").pw_uid


def verify_upload(
    upload: Path = UPLOAD_LAYER,
    *,
    expected_uid: int | None = None,
    enforce_permissions: bool = True,
    expected_sha256: str = LAYER_SHA256,
    expected_size: int = LAYER_SIZE,
) -> dict[str, object]:
    owner = _deploy_uid() if expected_uid is None and enforce_permissions else expected_uid
    return verify_layer_archive(
        upload,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        expected_uid=owner if enforce_permissions else None,
        required_mode=0o600 if enforce_permissions else None,
    )


def _validate_staging_parent(parent: Path, *, root_uid: int) -> None:
    base = parent.parent
    if base.is_symlink() or not base.is_dir():
        raise StageError("staging_base_invalid")
    if os.name != "nt":
        base_info = base.stat(follow_symlinks=False)
        if (
            base_info.st_uid != root_uid
            or base_info.st_gid != root_uid
            or stat.S_IMODE(base_info.st_mode) & 0o022
        ):
            raise StageError("staging_base_permissions")
    if parent.is_symlink():
        raise StageError("staging_parent_invalid")
    if not parent.exists():
        parent.mkdir(mode=0o755)
        if os.name != "nt":
            os.chown(parent, root_uid, root_uid)
        return
    if not parent.is_dir():
        raise StageError("staging_parent_invalid")
    if os.name != "nt":
        info = parent.stat(follow_symlinks=False)
        if info.st_uid != root_uid or info.st_gid != root_uid or stat.S_IMODE(info.st_mode) & 0o022:
            raise StageError("staging_parent_permissions")


def _copy_member(bundle: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    source = bundle.extractfile(member)
    if source is None:
        raise StageError("tar_member_unreadable")
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o400,
    )
    copied = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                stream.write(chunk)
                copied += len(chunk)
    finally:
        source.close()
    if copied != member.size:
        raise StageError("tar_member_truncated")


def _lock_tree(root: Path, *, root_uid: int) -> None:
    for directory in [root, *[item for item in root.rglob("*") if item.is_dir()]]:
        if directory.is_symlink():
            raise StageError("staging_symlink_rejected")
        if os.name != "nt":
            os.chown(directory, root_uid, root_uid)
        directory.chmod(0o755)
    for path in [item for item in root.rglob("*") if item.is_file()]:
        if path.is_symlink() or path.stat(follow_symlinks=False).st_nlink != 1:
            raise StageError("staging_file_invalid")
        if os.name != "nt":
            os.chown(path, root_uid, root_uid)
        path.chmod(0o444)


def _verify_locked_tree(root: Path, *, root_uid: int) -> dict[str, object]:
    result = verify_tree(root, installed=True, expected_uid=root_uid)
    for path in [item for item in root.rglob("*") if item.is_file()]:
        if stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) != 0o444:
            raise StageError("staging_file_mode_invalid")
    return result


def stage_fixed(
    upload: Path = UPLOAD_LAYER,
    staging: Path = STAGING_ROOT,
    *,
    expected_uid: int | None = None,
    enforce_upload_permissions: bool = True,
    root_uid: int = 0,
    expected_sha256: str = LAYER_SHA256,
    expected_size: int = LAYER_SIZE,
) -> dict[str, object]:
    verify_upload(
        upload,
        expected_uid=expected_uid,
        enforce_permissions=enforce_upload_permissions,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
    )
    partial = staging.with_name(f"{staging.name}.partial")
    for path in (staging, partial):
        if path.is_symlink() or path.exists():
            raise StageError("staging_state_not_empty")
    _validate_staging_parent(staging.parent, root_uid=root_uid)
    partial.mkdir(mode=0o700)
    try:
        members = inspect_layer_members(upload)
        prefix = ARCHIVE_PREFIX.as_posix() + "/"
        with tarfile.open(upload, mode="r:gz") as bundle:
            for member in members:
                if not member.isreg():
                    continue
                relative = member.name.rstrip("/").removeprefix(prefix)
                _copy_member(bundle, member, partial / relative)
        _lock_tree(partial, root_uid=root_uid)
        result = _verify_locked_tree(partial, root_uid=root_uid)
        os.replace(partial, staging)
        return {**result, "staged": True}
    except Exception as exc:
        raise StageError("partial_stage_requires_separate_cleanup_authorization") from exc


def verify_fixed(
    upload: Path = UPLOAD_LAYER,
    staging: Path = STAGING_ROOT,
    *,
    expected_uid: int | None = None,
    enforce_upload_permissions: bool = True,
    root_uid: int = 0,
    expected_sha256: str = LAYER_SHA256,
    expected_size: int = LAYER_SIZE,
) -> dict[str, object]:
    layer = verify_upload(
        upload,
        expected_uid=expected_uid,
        enforce_permissions=enforce_upload_permissions,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
    )
    tree = _verify_locked_tree(staging, root_uid=root_uid)
    return {"status": "passed", "layer": layer, "staging": tree}


def status_fixed(
    upload: Path = UPLOAD_LAYER,
    staging: Path = STAGING_ROOT,
    *,
    expected_uid: int | None = None,
    enforce_upload_permissions: bool = True,
    root_uid: int = 0,
    expected_sha256: str = LAYER_SHA256,
    expected_size: int = LAYER_SIZE,
) -> dict[str, str]:
    try:
        verify_upload(
            upload,
            expected_uid=expected_uid,
            enforce_permissions=enforce_upload_permissions,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
        upload_status = "valid"
    except (LayerContractError, StageError):
        upload_status = "missing" if not upload.exists() else "invalid"
    partial = staging.with_name(f"{staging.name}.partial")
    if partial.exists() or partial.is_symlink():
        staging_status = "partial_or_invalid"
    elif not staging.exists():
        staging_status = "missing"
    else:
        try:
            _verify_locked_tree(staging, root_uid=root_uid)
            staging_status = "complete"
        except (InstallError, StageError, OSError):
            staging_status = "partial_or_invalid"
    return {"upload_layer": upload_status, "staging": staging_status}


def render(result: dict[str, object]) -> str:
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
