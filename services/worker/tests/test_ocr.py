from __future__ import annotations

import base64
import hashlib
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from services.api.app.config import Settings
from services.worker.app.ocr import (
    OcrConfigurationError,
    OcrLine,
    PaddleOcrEngine,
    analyze_four_orientations,
    default_document_name,
    sanitize_title_candidate,
    validate_model_pack,
)


class SequenceEngine:
    model_version = "test-ocr-v1"

    def __init__(self, results: list[list[OcrLine]]):
        self.results = iter(results)

    def recognize(self, image: Image.Image) -> list[OcrLine]:
        del image
        return next(self.results)


def line(
    text: str,
    confidence: float,
    box: tuple[int, int, int, int] = (10, 10, 180, 40),
) -> OcrLine:
    return OcrLine(text=text, confidence=confidence, box=box)


def test_four_orientation_fusion_selects_clear_text_and_safe_title() -> None:
    engine = SequenceEngine(
        [
            [line("旋转文本", 0.60, (10, 10, 40, 180))],
            [
                line("13800138000", 0.99, (10, 5, 180, 35)),
                line("项目实施方案", 0.96, (10, 45, 190, 85)),
                line("正文内容", 0.92, (10, 160, 180, 190)),
            ],
            [line("倒置文本", 0.58, (10, 10, 40, 180))],
            [],
        ]
    )
    progress: list[int] = []
    result = analyze_four_orientations(
        Image.new("RGB", (300, 200), "white"),
        engine,
        min_confidence=0.55,
        title_min_confidence=0.70,
        orientation_margin=0.04,
        on_pass=lambda index: progress.append(index) is None,
    )

    assert result.rotation_degrees == 90
    assert result.title_candidate == "项目实施方案"
    assert result.text == "13800138000\n项目实施方案\n正文内容"
    assert result.confidence > 0.9
    assert result.details["schema_version"] == 1
    assert progress == [1, 2, 3, 4]


def test_orientation_margin_keeps_zero_degree_when_scores_are_close() -> None:
    engine = SequenceEngine(
        [
            [line("正向标题", 0.90)],
            [line("略高标题", 0.92)],
            [],
            [],
        ]
    )
    result = analyze_four_orientations(
        Image.new("RGB", (300, 200), "white"),
        engine,
        min_confidence=0.55,
        title_min_confidence=0.70,
        orientation_margin=0.04,
    )
    assert result.rotation_degrees == 0
    assert result.title_candidate == "正向标题"


@pytest.mark.parametrize(
    "candidate",
    ["138 0013 8000", "11010519491231002X", "第 12 页", "Page 3 of 9", "12"],
)
def test_sensitive_identifiers_and_page_numbers_cannot_be_titles(candidate: str) -> None:
    assert sanitize_title_candidate(candidate) is None


def test_title_sanitization_and_localized_fallback() -> None:
    assert sanitize_title_candidate("  项目：计划/2026*  ") == "项目 计划 2026"
    assert sanitize_title_candidate("年度报告.PDF") == "年度报告"
    assert sanitize_title_candidate("CON") is None
    assert default_document_name("zh-CN", date(2026, 10, 20)) == "智能扫描_20261020"
    assert default_document_name("en", date(2026, 10, 20)) == "SmartScan_20261020"


def test_model_pack_requires_fixed_versions_and_checksums(tmp_path: Path) -> None:
    detection = tmp_path / "det" / "model.pdmodel"
    recognition = tmp_path / "rec" / "model.pdmodel"
    detection.parent.mkdir()
    recognition.parent.mkdir()
    detection.write_bytes(b"detector")
    recognition.write_bytes(b"recognizer")
    manifest = {
        "schema_version": 1,
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": "PP-OCRv6-small-v1",
        "text_detection_dir": "det",
        "text_recognition_dir": "rec",
        "files": {
            "det/model.pdmodel": hashlib.sha256(b"detector").hexdigest(),
            "rec/model.pdmodel": hashlib.sha256(b"recognizer").hexdigest(),
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    settings = Settings(_env_file=None, ocr_model_root=tmp_path)

    assert validate_model_pack(settings) == (tmp_path / "det", tmp_path / "rec")
    recognition.write_bytes(b"tampered")
    with pytest.raises(OcrConfigurationError, match="ocr_model_checksum_mismatch"):
        validate_model_pack(settings)


def test_paddle_adapter_uses_local_cpu_models_and_parses_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detection = tmp_path / "det" / "model.pdmodel"
    recognition = tmp_path / "rec" / "model.pdmodel"
    detection.parent.mkdir()
    recognition.parent.mkdir()
    detection.write_bytes(b"detector")
    recognition.write_bytes(b"recognizer")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paddleocr_version": "3.7.0",
                "paddlepaddle_version": "3.3.1",
                "model_version": "PP-OCRv6-small-v1",
                "text_detection_dir": "det",
                "text_recognition_dir": "rec",
                "files": {
                    "det/model.pdmodel": hashlib.sha256(b"detector").hexdigest(),
                    "rec/model.pdmodel": hashlib.sha256(b"recognizer").hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakePipeline:
        def __init__(self, **kwargs: object):
            captured["init"] = kwargs

        def predict(self, image: object, **kwargs: object) -> list[object]:
            captured["shape"] = getattr(image, "shape", None)
            captured["predict"] = kwargs
            return [
                types.SimpleNamespace(
                    json={
                        "res": {
                            "rec_texts": ["本地识别"],
                            "rec_scores": [0.98],
                            "rec_boxes": [[1, 2, 101, 42]],
                        }
                    }
                )
            ]

    fake_module = types.ModuleType("paddleocr")
    fake_module.__dict__["PaddleOCR"] = FakePipeline
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    monkeypatch.setattr(
        "services.worker.app.ocr.version",
        lambda package: {"paddleocr": "3.7.0", "paddlepaddle": "3.3.1"}[package],
    )
    settings = Settings(_env_file=None, ocr_model_root=tmp_path, ocr_cpu_threads=2)
    engine = PaddleOcrEngine(settings)
    lines = engine.recognize(Image.new("RGB", (120, 80), "white"))

    assert captured["init"] == {
        "text_detection_model_dir": str(tmp_path / "det"),
        "text_recognition_model_dir": str(tmp_path / "rec"),
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "device": "cpu",
        "engine": "paddle_static",
        "cpu_threads": 2,
        "text_rec_score_thresh": 0.55,
    }
    assert captured["shape"] == (80, 120, 3)
    assert lines == [OcrLine("本地识别", 0.98, (1, 2, 101, 42))]


def test_production_requires_local_cpu_ocr() -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        secret_key="s" * 32,
        phone_hmac_peppers={"v1": "p" * 32},
        phone_hmac_active_key_id="v1",
        phone_encryption_keys={"v1": base64.urlsafe_b64encode(b"k" * 32).decode()},
        phone_encryption_active_key_id="v1",
        superadmin_password="strong-bootstrap-password",
        sms_mode="disabled",
        wecom_mode="disabled",
        ocr_enabled=False,
    )
    with pytest.raises(RuntimeError, match="SMARTSCAN_OCR_ENABLED=true"):
        settings.validate_production()
