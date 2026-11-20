from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_ARTIFACT_BYTES = 4 * 1024**3
MODEL_DIRS = ("PP-OCRv6_small_det", "PP-OCRv6_small_rec")
EVIDENCE_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM_MODEL_DESCRIPTION.md",
    "source-lock.json",
)


class ArtifactError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"JSON无效：{path}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"JSON根节点必须是对象：{path}")
    return value


def _regular_files(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ArtifactError(f"拒绝符号链接：{path}")
        if path.is_file():
            result.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ArtifactError(f"拒绝异常文件类型：{path}")
    return result


def _verify_source_lock(lock: dict[str, Any]) -> None:
    if lock.get("schema_version") != 1 or lock.get("artifact_version") != "PP-OCRv6-small-v1":
        raise ArtifactError("来源锁定文件版本无效")
    runtime = lock.get("runtime")
    if runtime != {
        "backend": "paddle_static",
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
    }:
        raise ArtifactError("OCR运行时契约无效")
    upstream = lock.get("upstream")
    if not isinstance(upstream, dict) or upstream.get("license") != "Apache-2.0":
        raise ArtifactError("来源许可证证据无效")
    models = lock.get("models")
    if not isinstance(models, dict) or set(models) != {"detection", "recognition"}:
        raise ArtifactError("来源模型集合无效")
    for model in models.values():
        if not isinstance(model, dict) or not isinstance(model.get("files"), dict):
            raise ArtifactError("来源模型文件清单无效")
        if set(model["files"]) != {"inference.json", "inference.pdiparams", "inference.yml"}:
            raise ArtifactError("来源模型文件集合无效")


def _extract_model(archive: Path, model: dict[str, Any], target: Path) -> None:
    if (
        archive.stat().st_size != model["archive_size"]
        or sha256_file(archive) != model["archive_sha256"]
    ):
        raise ArtifactError(f"上游归档摘要或大小不一致：{archive.name}")
    expected = {
        f"{model['archive_root']}/{name}": metadata for name, metadata in model["files"].items()
    }
    with tarfile.open(archive, "r:") as bundle:
        members = bundle.getmembers()
        regular: dict[str, tarfile.TarInfo] = {}
        for member in members:
            name = PurePosixPath(member.name).as_posix().lstrip("./")
            if (
                member.issym()
                or member.islnk()
                or name.startswith("/")
                or ".." in PurePosixPath(name).parts
            ):
                raise ArtifactError("上游归档含不安全路径或链接")
            if member.isfile():
                if name in regular:
                    raise ArtifactError("上游归档含重复文件")
                regular[name] = member
            elif not member.isdir():
                raise ArtifactError("上游归档含异常文件类型")
        if set(regular) != set(expected):
            raise ArtifactError("上游归档文件集合与锁定清单不一致")
        target.mkdir(parents=True, exist_ok=False)
        for archive_name, metadata in sorted(expected.items()):
            source = bundle.extractfile(regular[archive_name])
            if source is None:
                raise ArtifactError("无法读取上游归档文件")
            destination = target / PurePosixPath(archive_name).name
            with destination.open("xb") as output:
                shutil.copyfileobj(source, output)
            if (
                destination.stat().st_size != metadata["size"]
                or sha256_file(destination) != metadata["sha256"]
            ):
                raise ArtifactError(f"上游模型文件校验失败：{archive_name}")


def assemble(lock_path: Path, det_archive: Path, rec_archive: Path, output: Path) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ArtifactError("输出目录必须不存在")
    lock = load_json(lock_path)
    _verify_source_lock(lock)
    output.mkdir(parents=True, mode=0o755)
    try:
        _extract_model(det_archive, lock["models"]["detection"], output / MODEL_DIRS[0])
        _extract_model(rec_archive, lock["models"]["recognition"], output / MODEL_DIRS[1])
        evidence_root = lock_path.parent
        for name in EVIDENCE_FILES:
            source = lock_path if name == "source-lock.json" else evidence_root / name
            if not source.is_file() or source.is_symlink():
                raise ArtifactError(f"许可证或来源证据缺失：{name}")
            shutil.copy2(source, output / name)
        files = {
            path.relative_to(output).as_posix(): {
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
            for directory in MODEL_DIRS
            for path in sorted((output / directory).iterdir())
        }
        evidence = {
            name: {"sha256": sha256_file(output / name), "size": (output / name).stat().st_size}
            for name in EVIDENCE_FILES
        }
        manifest = {
            "schema_version": 1,
            "artifact_kind": "smartscan-offline-ocr-models",
            "artifact_version": lock["artifact_version"],
            "backend": "paddle_static",
            "paddleocr_version": "3.7.0",
            "paddlepaddle_version": "3.3.1",
            "model_version": lock["artifact_version"],
            "license": "Apache-2.0",
            "source": "PaddlePaddle/PaddleOCR@v3.7.0",
            "source_commit": lock["upstream"]["commit"],
            "conversion": {"performed": False, "description": "仅规范化目录名，模型字节未修改"},
            "text_detection_dir": MODEL_DIRS[0],
            "text_recognition_dir": MODEL_DIRS[1],
            "files": {name: metadata["sha256"] for name, metadata in files.items()},
            "file_metadata": files,
            "evidence_files": evidence,
            "total_model_bytes": sum(item["size"] for item in files.values()),
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        verify(output)
        return manifest
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def verify(root: Path, *, require_root_owned: bool = False) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise ArtifactError("模型制品根目录无效")
    manifest = load_json(root / "manifest.json")
    required = {
        "schema_version": 1,
        "artifact_kind": "smartscan-offline-ocr-models",
        "artifact_version": "PP-OCRv6-small-v1",
        "backend": "paddle_static",
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": "PP-OCRv6-small-v1",
        "license": "Apache-2.0",
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ArtifactError("模型manifest版本或运行时契约无效")
    if manifest.get("conversion", {}).get("performed") is not False:
        raise ArtifactError("本制品不允许未声明的模型转换")
    files = manifest.get("files")
    file_metadata = manifest.get("file_metadata")
    evidence = manifest.get("evidence_files")
    if (
        not isinstance(files, dict)
        or not isinstance(file_metadata, dict)
        or not isinstance(evidence, dict)
    ):
        raise ArtifactError("模型或证据清单无效")
    if set(evidence) != set(EVIDENCE_FILES):
        raise ArtifactError("许可证或来源证据清单不完整")
    expected = set(files) | set(evidence) | {"manifest.json"}
    if _regular_files(root) != expected:
        raise ArtifactError("模型制品存在缺失或多余文件")
    total = 0
    if files != {name: metadata.get("sha256") for name, metadata in file_metadata.items()}:
        raise ArtifactError("兼容摘要清单与文件元数据不一致")
    for relative, metadata in {**file_metadata, **evidence}.items():
        path = root / relative
        if not isinstance(metadata, dict) or path.is_symlink() or not path.is_file():
            raise ArtifactError("模型文件清单无效")
        if path.stat().st_size != metadata.get("size") or sha256_file(path) != metadata.get(
            "sha256"
        ):
            raise ArtifactError(f"模型文件摘要或大小不一致：{relative}")
        total += path.stat().st_size
        if require_root_owned and os.name != "nt":
            info = path.stat()
            if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise ArtifactError(f"已安装模型所有者或权限无效：{relative}")
    if total > MAX_ARTIFACT_BYTES or manifest.get("total_model_bytes") != sum(
        item["size"] for item in file_metadata.values()
    ):
        raise ArtifactError("模型制品大小超限或清单不一致")
    return {"status": "passed", "artifact_version": manifest["artifact_version"], "bytes": total}


def main() -> None:
    parser = argparse.ArgumentParser(description="组装和验证SmartScan离线OCR模型制品")
    subparsers = parser.add_subparsers(dest="command", required=True)
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--lock", type=Path, required=True)
    assemble_parser.add_argument("--detection-archive", type=Path, required=True)
    assemble_parser.add_argument("--recognition-archive", type=Path, required=True)
    assemble_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "assemble":
        result = assemble(args.lock, args.detection_archive, args.recognition_archive, args.output)
        summary = {"status": "passed", "artifact_version": result["artifact_version"]}
    else:
        summary = verify(args.root)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
