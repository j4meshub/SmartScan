from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path


def safe_relative_directory(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError("模型目录必须相对于模型包根目录")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if resolved_root not in resolved.parents or not resolved.is_dir():
        raise ValueError(f"模型目录不存在或越界：{value}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    root: Path,
    *,
    detection_dir: str,
    recognition_dir: str,
    paddleocr_version: str,
    paddlepaddle_version: str,
    model_version: str,
) -> dict[str, object]:
    root = root.resolve()
    safe_relative_directory(root, detection_dir)
    safe_relative_directory(root, recognition_dir)
    files: dict[str, str] = {}
    for directory_name in (detection_dir, recognition_dir):
        directory = safe_relative_directory(root, directory_name)
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            files[relative] = sha256_file(path)
    if not files:
        raise ValueError("模型目录中没有可校验文件")
    return {
        "schema_version": 1,
        "paddleocr_version": paddleocr_version,
        "paddlepaddle_version": paddlepaddle_version,
        "model_version": model_version,
        "text_detection_dir": Path(detection_dir).as_posix(),
        "text_recognition_dir": Path(recognition_dir).as_posix(),
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="为离线 OCR 模型包生成版本与 SHA-256 清单")
    parser.add_argument("root", type=Path, help="模型包根目录")
    parser.add_argument("--detection-dir", default="PP-OCRv6_small_det")
    parser.add_argument("--recognition-dir", default="PP-OCRv6_small_rec")
    parser.add_argument("--paddleocr-version", default="3.7.0")
    parser.add_argument("--paddlepaddle-version", default="3.3.1")
    parser.add_argument("--model-version", default="PP-OCRv6-small-v1")
    args = parser.parse_args()
    manifest = build_manifest(
        args.root,
        detection_dir=args.detection_dir,
        recognition_dir=args.recognition_dir,
        paddleocr_version=args.paddleocr_version,
        paddlepaddle_version=args.paddlepaddle_version,
        model_version=args.model_version,
    )
    destination = args.root.resolve() / "manifest.json"
    incoming = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.incoming")
    incoming.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(incoming, destination)
    print(f"已生成 OCR 模型清单：{destination}（{len(manifest['files'])} 个文件）")


if __name__ == "__main__":
    main()
