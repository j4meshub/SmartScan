from __future__ import annotations

import hashlib
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath

INDEX_DIGEST = "sha256:0fc7f95eb14f18996c6f22d71b4873b28e79ea0afde8a66ddea6b6c095740c13"
MANIFEST_DIGEST = "sha256:7c5dccfc9b5cb3175718344b913d0993b13ad489835fbdbc4204e11f658a15f7"
CONFIG_DIGEST = "sha256:c6344931bf46a076ebc180117988d7240e5f0e7320db647a6a98d365a74e480d"
CONFIG_SIZE = 1_877
LAYER_DIGEST = "sha256:fdae8d61585eef7d6a5c810e10847cd10039f3a8b69645d480c6d4127c1aebfb"
LAYER_SHA256 = LAYER_DIGEST.removeprefix("sha256:")
LAYER_SIZE = 26_534_130
SOURCE_COMMIT = "9be7b7c366f568d82a19341e072a3144ddd025a2"
LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"
MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
MAX_EXTRACTED_BYTES = 4 * 1024**3
ARCHIVE_PREFIX = PurePosixPath("models/ocr")

MODEL_FILE_SIZES = {
    "PP-OCRv6_small_det/inference.json": 229_307,
    "PP-OCRv6_small_det/inference.pdiparams": 9_817_888,
    "PP-OCRv6_small_det/inference.yml": 885,
    "PP-OCRv6_small_rec/inference.json": 208_004,
    "PP-OCRv6_small_rec/inference.pdiparams": 21_074_618,
    "PP-OCRv6_small_rec/inference.yml": 150_579,
}
EVIDENCE_FILES = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM_MODEL_DESCRIPTION.md",
    "source-lock.json",
    "manifest.json",
}
EXPECTED_FILES = set(MODEL_FILE_SIZES) | EVIDENCE_FILES
ALLOWED_DIRECTORIES = {
    "models",
    "models/ocr",
    "models/ocr/PP-OCRv6_small_det",
    "models/ocr/PP-OCRv6_small_rec",
}


class LayerContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _safe_member_name(raw: str) -> str:
    if not raw or "\\" in raw or raw.startswith("/"):
        raise LayerContractError("tar_path_rejected")
    path = PurePosixPath(raw.rstrip("/"))
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise LayerContractError("tar_path_rejected")
    return path.as_posix()


def inspect_layer_members(archive: Path) -> list[tarfile.TarInfo]:
    try:
        with archive.open("rb") as stream:
            if stream.read(2) != b"\x1f\x8b":
                raise LayerContractError("gzip_header_invalid")
        with tarfile.open(archive, mode="r:gz") as bundle:
            members = bundle.getmembers()
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise LayerContractError("tar_invalid") from exc

    seen: set[str] = set()
    actual_files: set[str] = set()
    total = 0
    for member in members:
        name = _safe_member_name(member.name)
        if name in seen:
            raise LayerContractError("tar_duplicate_path")
        seen.add(name)
        if member.isdir():
            if name not in ALLOWED_DIRECTORIES:
                raise LayerContractError("tar_extra_directory")
            continue
        if not member.isreg():
            raise LayerContractError("tar_special_file_rejected")
        prefix = ARCHIVE_PREFIX.as_posix() + "/"
        if not name.startswith(prefix):
            raise LayerContractError("tar_prefix_invalid")
        relative = name.removeprefix(prefix)
        if relative not in EXPECTED_FILES:
            raise LayerContractError("tar_extra_file")
        if relative in MODEL_FILE_SIZES and member.size != MODEL_FILE_SIZES[relative]:
            raise LayerContractError("tar_model_size_invalid")
        if relative in EVIDENCE_FILES and member.size > 1024 * 1024:
            raise LayerContractError("tar_evidence_size_invalid")
        actual_files.add(relative)
        total += member.size
        if total > MAX_EXTRACTED_BYTES:
            raise LayerContractError("tar_extracted_size_exceeded")
    if actual_files != EXPECTED_FILES:
        raise LayerContractError("tar_file_set_mismatch")
    return members


def verify_layer_archive(
    archive: Path,
    *,
    expected_sha256: str = LAYER_SHA256,
    expected_size: int = LAYER_SIZE,
    expected_uid: int | None = None,
    required_mode: int | None = None,
) -> dict[str, object]:
    if archive.is_symlink() or not archive.is_file():
        raise LayerContractError("layer_file_invalid")
    info = archive.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise LayerContractError("layer_file_invalid")
    if info.st_size != expected_size:
        raise LayerContractError("layer_size_invalid")
    digest = sha256_file(archive)
    if digest != expected_sha256:
        raise LayerContractError("layer_digest_invalid")
    if expected_uid is not None and os.name != "nt" and info.st_uid != expected_uid:
        raise LayerContractError("layer_owner_invalid")
    if required_mode is not None and stat.S_IMODE(info.st_mode) != required_mode:
        raise LayerContractError("layer_mode_invalid")
    members = inspect_layer_members(archive)
    try:
        with tarfile.open(archive, mode="r:gz") as bundle:
            total_read = 0
            for member in members:
                if not member.isreg():
                    continue
                stream = bundle.extractfile(member)
                if stream is None:
                    raise LayerContractError("tar_member_unreadable")
                count = 0
                while chunk := stream.read(1024 * 1024):
                    count += len(chunk)
                if count != member.size:
                    raise LayerContractError("tar_member_truncated")
                total_read += count
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise LayerContractError("tar_invalid") from exc
    return {
        "status": "passed",
        "sha256": digest,
        "compressed_bytes": info.st_size,
        "extracted_bytes": total_read,
        "files": len(EXPECTED_FILES),
    }
