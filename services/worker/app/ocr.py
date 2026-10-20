from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from PIL import Image

from services.api.app.config import Settings


class OcrConfigurationError(RuntimeError):
    pass


class OcrInterrupted(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class OcrPass:
    rotation_degrees: int
    width: int
    height: int
    lines: tuple[OcrLine, ...]
    confidence: float
    score: float


@dataclass(frozen=True)
class OcrAnalysis:
    rotation_degrees: int
    text: str
    confidence: float
    title_candidate: str | None
    details: dict[str, object]
    model_version: str


class OcrEngine(Protocol):
    model_version: str

    def recognize(self, image: Image.Image) -> Sequence[OcrLine]: ...


def rotate_clockwise(image: Image.Image, degrees: int) -> Image.Image:
    if degrees == 0:
        return image.copy()
    return image.rotate(-degrees, expand=True)


def _safe_model_path(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise OcrConfigurationError("ocr_manifest_path_invalid")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if resolved_root not in resolved.parents:
        raise OcrConfigurationError("ocr_manifest_path_invalid")
    return resolved


def validate_model_pack(settings: Settings) -> tuple[Path, Path]:
    root = settings.ocr_model_root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise OcrConfigurationError("ocr_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OcrConfigurationError("ocr_manifest_invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise OcrConfigurationError("ocr_manifest_invalid")
    expected = {
        "paddleocr_version": settings.ocr_package_version,
        "paddlepaddle_version": settings.ocr_engine_version,
        "model_version": settings.ocr_model_version,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise OcrConfigurationError("ocr_manifest_version_mismatch")
    detection_dir = _safe_model_path(root, str(manifest.get("text_detection_dir", "")))
    recognition_dir = _safe_model_path(root, str(manifest.get("text_recognition_dir", "")))
    if not detection_dir.is_dir() or not recognition_dir.is_dir():
        raise OcrConfigurationError("ocr_model_directory_missing")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise OcrConfigurationError("ocr_manifest_files_missing")
    actual_files = {
        path.relative_to(root).as_posix()
        for directory in (detection_dir, recognition_dir)
        for path in directory.rglob("*")
        if path.is_file()
    }
    if actual_files != set(files):
        raise OcrConfigurationError("ocr_manifest_files_incomplete")
    for relative, expected_sha256 in files.items():
        if not isinstance(relative, str) or not re.fullmatch(r"[a-f0-9]{64}", str(expected_sha256)):
            raise OcrConfigurationError("ocr_manifest_files_invalid")
        model_file = _safe_model_path(root, relative)
        if not model_file.is_file():
            raise OcrConfigurationError("ocr_model_file_missing")
        digest = hashlib.sha256()
        with model_file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise OcrConfigurationError("ocr_model_checksum_mismatch")
    return detection_dir, recognition_dir


class PaddleOcrEngine:
    def __init__(self, settings: Settings):
        detection_dir, recognition_dir = validate_model_pack(settings)
        try:
            paddleocr_version = version("paddleocr")
            paddlepaddle_version = version("paddlepaddle")
        except PackageNotFoundError as exc:
            raise OcrConfigurationError("ocr_runtime_missing") from exc
        if (
            paddleocr_version != settings.ocr_package_version
            or paddlepaddle_version != settings.ocr_engine_version
        ):
            raise OcrConfigurationError("ocr_runtime_version_mismatch")
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrConfigurationError("ocr_runtime_missing") from exc

        self.model_version = settings.ocr_model_version
        self._pipeline = PaddleOCR(
            text_detection_model_dir=str(detection_dir),
            text_recognition_model_dir=str(recognition_dir),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
            engine="paddle_static",
            cpu_threads=settings.ocr_cpu_threads,
            text_rec_score_thresh=settings.ocr_min_confidence,
        )

    def recognize(self, image: Image.Image) -> Sequence[OcrLine]:
        try:
            import numpy as np
        except ImportError as exc:
            raise OcrConfigurationError("ocr_runtime_missing") from exc
        results = list(
            self._pipeline.predict(
                np.asarray(image.convert("RGB")),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        )
        if not results:
            return ()
        payload = getattr(results[0], "json", None)
        if not isinstance(payload, Mapping):
            raise OcrConfigurationError("ocr_result_invalid")
        body = payload.get("res", payload)
        if not isinstance(body, Mapping):
            raise OcrConfigurationError("ocr_result_invalid")
        texts = list(body.get("rec_texts", ()))
        scores = list(body.get("rec_scores", ()))
        boxes = list(body.get("rec_boxes", ()))
        if not (len(texts) == len(scores) == len(boxes)):
            raise OcrConfigurationError("ocr_result_invalid")
        lines: list[OcrLine] = []
        for text, score, box in zip(texts, scores, boxes, strict=True):
            if len(lines) >= 2000:
                break
            values = list(box)
            if len(values) != 4:
                continue
            confidence = float(score)
            if not math.isfinite(confidence):
                continue
            x_min, y_min, x_max, y_max = (int(value) for value in values)
            x_min = max(0, min(x_min, image.width))
            y_min = max(0, min(y_min, image.height))
            x_max = max(0, min(x_max, image.width))
            y_max = max(0, min(y_max, image.height))
            if x_max <= x_min or y_max <= y_min:
                continue
            lines.append(
                OcrLine(
                    text=str(text).strip()[:512],
                    confidence=max(0.0, min(confidence, 1.0)),
                    box=(x_min, y_min, x_max, y_max),
                )
            )
        return lines


def _pass_score(lines: Sequence[OcrLine], min_confidence: float) -> tuple[float, float]:
    accepted = [line for line in lines if line.text and line.confidence >= min_confidence]
    if not accepted:
        return 0.0, 0.0
    weights = [max(len(line.text), 1) for line in accepted]
    weighted_confidence = sum(
        line.confidence * weight for line, weight in zip(accepted, weights, strict=True)
    ) / sum(weights)
    horizontal_ratio = sum(
        1 for line in accepted if line.box[2] - line.box[0] >= line.box[3] - line.box[1]
    ) / len(accepted)
    content_bonus = min(sum(weights) / 400.0, 0.08)
    score = weighted_confidence + horizontal_ratio * 0.04 + content_bonus
    return weighted_confidence, score


def _is_sensitive_or_page_number(text: str) -> bool:
    compact = re.sub(r"[\s()-]", "", text)
    if re.search(r"(?<!\d)(?:\+?86)?1[3-9]\d{9}(?!\d)", compact):
        return True
    if re.search(r"(?<!\d)\d{17}[\dXx](?![\dXx])", compact):
        return True
    if re.fullmatch(r"(?:第\s*)?\d{1,5}\s*(?:页|/\s*\d{1,5})?", text, re.IGNORECASE):
        return True
    return bool(re.fullmatch(r"page\s*\d{1,5}(?:\s*(?:of|/)\s*\d{1,5})?", text, re.IGNORECASE))


def sanitize_title_candidate(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip(" ._-")
    if not normalized or _is_sensitive_or_page_number(normalized):
        return None
    normalized = re.sub(r"[<>:\"/\\|?*：／＼｜？＊＜＞＂\x00-\x1f]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ._-")
    normalized = re.sub(r"\.(?:pdf|jpe?g)$", "", normalized, flags=re.IGNORECASE).rstrip(" .")
    if len(normalized) < 2:
        return None
    if normalized.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }:
        return None
    return normalized[:80].rstrip(" .")


def select_title_candidate(
    lines: Sequence[OcrLine],
    *,
    image_height: int,
    min_confidence: float,
) -> str | None:
    candidates: list[tuple[float, int, int, str]] = []
    for index, line in enumerate(lines):
        if line.confidence < min_confidence or line.box[1] > image_height * 0.4:
            continue
        title = sanitize_title_candidate(line.text)
        if title is None:
            continue
        height = max(line.box[3] - line.box[1], 1)
        candidates.append((line.confidence, height, -index, title))
    if not candidates:
        return None
    return max(candidates)[3]


def analyze_four_orientations(
    image: Image.Image,
    engine: OcrEngine,
    *,
    min_confidence: float,
    title_min_confidence: float,
    orientation_margin: float,
    on_pass: Callable[[int], bool] | None = None,
) -> OcrAnalysis:
    passes: list[OcrPass] = []
    for index, degrees in enumerate((0, 90, 180, 270), start=1):
        rotated = rotate_clockwise(image, degrees)
        lines = tuple(engine.recognize(rotated))
        confidence, score = _pass_score(lines, min_confidence)
        passes.append(
            OcrPass(
                rotation_degrees=degrees,
                width=rotated.width,
                height=rotated.height,
                lines=lines,
                confidence=confidence,
                score=score,
            )
        )
        if on_pass is not None and not on_pass(index):
            raise OcrInterrupted("ocr_lease_lost")
    baseline = passes[0]
    best = max(passes, key=lambda item: (item.score, -item.rotation_degrees))
    if best.rotation_degrees and best.score < baseline.score + orientation_margin:
        best = baseline
    accepted = [line for line in best.lines if line.text and line.confidence >= min_confidence]
    title = select_title_candidate(
        accepted,
        image_height=best.height,
        min_confidence=title_min_confidence,
    )
    details: dict[str, object] = {
        "schema_version": 1,
        "passes": [
            {
                "rotation_degrees": item.rotation_degrees,
                "confidence": round(item.confidence, 6),
                "score": round(item.score, 6),
                "line_count": len(item.lines),
            }
            for item in passes
        ],
        "lines": [
            {
                "text": line.text,
                "confidence": round(line.confidence, 6),
                "box": list(line.box),
            }
            for line in accepted
        ],
    }
    return OcrAnalysis(
        rotation_degrees=best.rotation_degrees,
        text="\n".join(line.text for line in accepted),
        confidence=best.confidence,
        title_candidate=title,
        details=details,
        model_version=engine.model_version,
    )


def default_document_name(locale: str, scanned_on: date) -> str:
    prefix = "SmartScan" if locale.lower().startswith("en") else "智能扫描"
    return f"{prefix}_{scanned_on:%Y%m%d}"
