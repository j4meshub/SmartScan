from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from tools.evaluate_perspective import (
    EvaluationManifestError,
    evaluate_manifest,
    write_reports,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_synthetic_dataset(root: Path) -> tuple[Path, list[list[float]]]:
    images = root / "images"
    images.mkdir(parents=True)
    width, height = 1200, 900
    corners = np.array([[220, 110], [990, 190], [1060, 760], [150, 810]], dtype=np.int32)
    canvas = np.full((height, width, 3), 35, dtype=np.uint8)
    cv2.fillConvexPoly(canvas, corners, (245, 245, 240))
    for offset in range(0, 360, 60):
        cv2.line(canvas, (300, 260 + offset), (900, 300 + offset), (40, 40, 40), 8)
    positive = images / "document.png"
    Image.fromarray(canvas).save(positive)
    negative = images / "empty.png"
    Image.new("RGB", (800, 600), (128, 128, 128)).save(negative)
    normalized = [[x / width, y / height] for x, y in corners]

    manifest = {
        "schema_version": 1,
        "dataset_id": "synthetic-ci-v1",
        "authorization": {
            "approved": True,
            "deidentified": True,
            "license": "测试代码生成，无第三方数据",
            "consent_reference": "CI-SYNTHETIC-001",
            "purpose": "文档透视评估器回归",
        },
        "samples": [
            {
                "id": "document-001",
                "path": "images/document.png",
                "sha256": sha256(positive),
                "category": "合成倾斜文档",
                "expected": {
                    "document_present": True,
                    "corners_normalized": normalized,
                },
            },
            {
                "id": "negative-001",
                "path": "images/empty.png",
                "sha256": sha256(negative),
                "category": "无文档负样本",
                "expected": {"document_present": False},
            },
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path, normalized


def test_evaluator_reports_usable_rate_timing_memory_and_no_source_paths(tmp_path: Path) -> None:
    manifest_path, _ = write_synthetic_dataset(tmp_path)

    preview_directory = tmp_path / "previews"
    report = evaluate_manifest(
        manifest_path, minimum_positive_samples=1, preview_directory=preview_directory
    )

    summary = report["summary"]
    assert summary["positive_samples"] == 1
    assert summary["negative_samples"] == 1
    assert summary["detection_recall"] == 1.0
    assert summary["usable_rate"] == 1.0
    assert summary["false_positive_rate"] == 0.0
    assert summary["gate_passed"] is True
    assert summary["duration_ms_p50"] > 0
    assert summary["duration_ms_p95"] > 0
    assert summary["peak_rss_bytes"] > 0
    assert report["samples"][0]["corner_error_normalized"] <= 0.03
    assert (preview_directory / "document-001.jpg").is_file()
    assert (preview_directory / "negative-001.jpg").is_file()

    json_path, markdown_path = write_reports(report, tmp_path / "reports")
    report_json = json_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in report_json
    assert "透视可用率：100.00%" in markdown_path.read_text(encoding="utf-8")


def test_evaluator_keeps_gate_closed_when_corner_quality_misses_target(tmp_path: Path) -> None:
    manifest_path, _ = write_synthetic_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["expected"]["corners_normalized"] = [
        [0.0, 0.0],
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 1.0],
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = evaluate_manifest(
        manifest_path, corner_error_threshold=0.01, minimum_positive_samples=1
    )

    assert report["summary"]["detection_recall"] == 1.0
    assert report["summary"]["usable_rate"] == 0.0
    assert report["summary"]["gate_passed"] is False


def test_evaluator_keeps_gate_closed_when_sample_count_is_too_small(tmp_path: Path) -> None:
    manifest_path, _ = write_synthetic_dataset(tmp_path)

    report = evaluate_manifest(manifest_path)

    assert report["summary"]["usable_rate"] == 1.0
    assert report["summary"]["sample_count_sufficient"] is False
    assert report["summary"]["minimum_positive_samples"] == 100
    assert report["summary"]["gate_passed"] is False


def test_evaluator_rejects_unapproved_or_unverified_samples(tmp_path: Path) -> None:
    manifest_path, _ = write_synthetic_dataset(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authorization"]["approved"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(EvaluationManifestError, match="尚未获准"):
        evaluate_manifest(manifest_path)

    manifest["authorization"]["approved"] = True
    manifest["samples"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(EvaluationManifestError, match="SHA-256 不匹配"):
        evaluate_manifest(manifest_path)


def test_evaluator_rejects_path_traversal(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    manifest_path, _ = write_synthetic_dataset(dataset)
    outside = tmp_path / "outside.png"
    Image.new("RGB", (100, 100), "white").save(outside)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["path"] = "../outside.png"
    manifest["samples"][0]["sha256"] = sha256(outside)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvaluationManifestError, match="越出数据集目录"):
        evaluate_manifest(manifest_path)
