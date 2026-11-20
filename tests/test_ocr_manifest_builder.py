from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.build_ocr_manifest import build_manifest


def test_ocr_manifest_records_source_license_and_all_file_digests(tmp_path: Path) -> None:
    detection = tmp_path / "det"
    recognition = tmp_path / "rec"
    detection.mkdir()
    recognition.mkdir()
    (detection / "model.bin").write_bytes(b"det")
    (recognition / "model.bin").write_bytes(b"rec")

    manifest = build_manifest(
        tmp_path,
        detection_dir="det",
        recognition_dir="rec",
        paddleocr_version="3.7.0",
        paddlepaddle_version="3.3.1",
        model_version="PP-OCRv6-small-v1",
        source="https://official.example.invalid/fixed-model",
        license_name="已审核许可证-v1",
    )

    assert manifest["source"] == "https://official.example.invalid/fixed-model"
    assert manifest["license"] == "已审核许可证-v1"
    assert set(manifest["files"]) == {"det/model.bin", "rec/model.bin"}
    json.dumps(manifest, ensure_ascii=False)


def test_ocr_manifest_rejects_missing_provenance(tmp_path: Path) -> None:
    detection = tmp_path / "det"
    recognition = tmp_path / "rec"
    detection.mkdir()
    recognition.mkdir()
    (detection / "model.bin").write_bytes(b"det")
    (recognition / "model.bin").write_bytes(b"rec")

    with pytest.raises(ValueError, match="来源和许可证"):
        build_manifest(
            tmp_path,
            detection_dir="det",
            recognition_dir="rec",
            paddleocr_version="3.7.0",
            paddlepaddle_version="3.3.1",
            model_version="PP-OCRv6-small-v1",
            source="",
            license_name="",
        )
