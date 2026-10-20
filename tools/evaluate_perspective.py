"""文档边缘与透视校正固定数据集评估器。"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import statistics
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import numpy as np
from PIL import Image, UnidentifiedImageError

from services.worker.app.vision import correct_document_perspective

SCHEMA_VERSION = 1
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SAFE_SAMPLE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class EvaluationManifestError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationManifestError(message)


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationManifestError("无法读取评估清单") from exc
    _require(isinstance(payload, dict), "评估清单根节点必须是对象")
    _require(
        not set(payload) - {"schema_version", "dataset_id", "authorization", "samples"},
        "评估清单包含未知字段",
    )
    _require(payload.get("schema_version") == SCHEMA_VERSION, "不支持的评估清单版本")
    _require(
        isinstance(payload.get("dataset_id"), str) and payload["dataset_id"].strip(),
        "缺少数据集 ID",
    )

    authorization = payload.get("authorization")
    _require(isinstance(authorization, dict), "缺少数据集授权信息")
    _require(
        not set(authorization)
        - {"approved", "deidentified", "license", "consent_reference", "purpose"},
        "授权信息包含未知字段",
    )
    _require(authorization.get("approved") is True, "数据集尚未获准用于评估")
    _require(authorization.get("deidentified") is True, "数据集必须先完成脱敏")
    for field in ("license", "consent_reference", "purpose"):
        _require(
            isinstance(authorization.get(field), str) and authorization[field].strip(),
            f"授权信息缺少 {field}",
        )

    samples = payload.get("samples")
    _require(isinstance(samples, list) and samples, "评估清单必须包含样本")
    seen_ids: set[str] = set()
    for sample in samples:
        _require(isinstance(sample, dict), "样本条目必须是对象")
        _require(
            not set(sample) - {"id", "path", "sha256", "category", "expected"},
            "样本条目包含未知字段",
        )
        sample_id = sample.get("id")
        _require(isinstance(sample_id, str) and sample_id.strip(), "样本缺少 ID")
        _require(SAFE_SAMPLE_ID.fullmatch(sample_id) is not None, f"样本 ID 不安全：{sample_id}")
        _require(sample_id not in seen_ids, f"样本 ID 重复：{sample_id}")
        seen_ids.add(sample_id)
        _require(
            isinstance(sample.get("path"), str) and sample["path"].strip(),
            f"样本 {sample_id} 缺少路径",
        )
        digest = sample.get("sha256")
        _require(
            isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest),
            f"样本 {sample_id} 的 SHA-256 无效",
        )
        expected = sample.get("expected")
        _require(isinstance(expected, dict), f"样本 {sample_id} 缺少期望标注")
        _require(
            not set(expected) - {"document_present", "corners_normalized"},
            f"样本 {sample_id} 的期望标注包含未知字段",
        )
        document_present = expected.get("document_present")
        _require(isinstance(document_present, bool), f"样本 {sample_id} 缺少 document_present")
        corners = expected.get("corners_normalized")
        if document_present:
            _validate_corners(corners, sample_id)
        else:
            _require(corners in (None, []), f"负样本 {sample_id} 不应标注四角")
    return payload


def _validate_corners(corners: object, sample_id: str) -> None:
    _require(isinstance(corners, list) and len(corners) == 4, f"样本 {sample_id} 必须标注四角")
    for point in corners:
        _require(isinstance(point, list) and len(point) == 2, f"样本 {sample_id} 四角格式无效")
        _require(
            all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in point),
            f"样本 {sample_id} 的归一化坐标必须位于 0 到 1",
        )


def _resolve_image(dataset_root: Path, relative_path: str) -> Path:
    root = dataset_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EvaluationManifestError("样本路径越出数据集目录") from exc
    _require(candidate.is_file(), f"样本文件不存在：{relative_path}")
    _require(candidate.suffix.lower() in SUPPORTED_SUFFIXES, f"样本格式不受支持：{relative_path}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _corner_error(
    predicted: np.ndarray,
    expected_normalized: list[list[float]],
    width: int,
    height: int,
) -> float:
    expected = np.asarray(expected_normalized, dtype=np.float32)
    expected[:, 0] *= width
    expected[:, 1] *= height
    distances = np.linalg.norm(predicted.astype(np.float32) - expected, axis=1)
    diagonal = float(np.hypot(width, height))
    return float(np.sqrt(np.mean(np.square(distances))) / diagonal)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _current_rss_bytes() -> int:
    if os.name == "nt":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        get_process_memory_info.restype = ctypes.c_int
        process = get_current_process()
        if get_process_memory_info(process, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
        return 0
    status = Path("/proc/self/status")
    if status.exists():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(usage if os.uname().sysname == "Darwin" else usage * 1024)
    except (ImportError, AttributeError, OSError):
        return 0


class _PeakMemorySampler:
    def __init__(self) -> None:
        self.peak_bytes = _current_rss_bytes()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.01):
            self.peak_bytes = max(self.peak_bytes, _current_rss_bytes())

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.peak_bytes = max(self.peak_bytes, _current_rss_bytes())
        self._stop.set()
        self._thread.join(timeout=1)


def evaluate_manifest(
    manifest_path: Path,
    *,
    corner_error_threshold: float = 0.03,
    min_usable_rate: float = 0.95,
    minimum_positive_samples: int = 100,
    max_image_pixels: int = 50_000_000,
    preview_directory: Path | None = None,
) -> dict[str, Any]:
    _require(0 < corner_error_threshold < 1, "角点误差阈值必须位于 0 到 1")
    _require(0 < min_usable_rate <= 1, "可用率门槛必须位于 0 到 1")
    _require(minimum_positive_samples >= 1, "最少正样本数量必须大于零")
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)
    dataset_root = manifest_path.parent
    if preview_directory is not None:
        preview_directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    durations: list[float] = []

    with _PeakMemorySampler() as memory:
        for sample in manifest["samples"]:
            image_path = _resolve_image(dataset_root, sample["path"])
            _require(
                _sha256(image_path) == sample["sha256"], f"样本 {sample['id']} 的 SHA-256 不匹配"
            )
            try:
                with Image.open(image_path) as source:
                    _require(
                        source.width * source.height <= max_image_pixels,
                        f"样本 {sample['id']} 超过像素上限",
                    )
                    source.load()
                    image = source.convert("RGB")
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                raise EvaluationManifestError(f"无法解码样本 {sample['id']}") from exc

            started = time.perf_counter()
            result = correct_document_perspective(image)
            duration_ms = (time.perf_counter() - started) * 1000
            durations.append(duration_ms)
            expected = sample["expected"]
            document_present = expected["document_present"]
            corner_error = None
            if result.detected and document_present and result.corners is not None:
                corner_error = _corner_error(
                    result.corners,
                    expected["corners_normalized"],
                    image.width,
                    image.height,
                )
            usable = bool(
                document_present
                and result.detected
                and corner_error is not None
                and corner_error <= corner_error_threshold
                and result.image.width >= 64
                and result.image.height >= 64
            )
            negative_correct = bool(not document_present and not result.detected)
            preview_file = None
            if preview_directory is not None:
                preview_file = f"{sample['id']}.jpg"
                result.image.save(preview_directory / preview_file, "JPEG", quality=90)
            results.append(
                {
                    "id": sample["id"],
                    "category": sample.get("category", "未分类"),
                    "document_present": document_present,
                    "detected": result.detected,
                    "confidence": round(result.confidence, 6),
                    "corner_error_normalized": None
                    if corner_error is None
                    else round(corner_error, 6),
                    "usable": usable,
                    "negative_correct": negative_correct,
                    "duration_ms": round(duration_ms, 3),
                    "input_size": [image.width, image.height],
                    "output_size": [result.image.width, result.image.height],
                    "preview_file": preview_file,
                }
            )

    positives = [item for item in results if item["document_present"]]
    negatives = [item for item in results if not item["document_present"]]
    _require(bool(positives), "固定数据集必须包含文档正样本")
    detected_positives = sum(item["detected"] for item in positives)
    usable_count = sum(item["usable"] for item in positives)
    false_positives = sum(item["detected"] for item in negatives)
    usable_rate = usable_count / len(positives)
    sample_count_sufficient = len(positives) >= minimum_positive_samples
    summary = {
        "positive_samples": len(positives),
        "negative_samples": len(negatives),
        "detection_recall": round(detected_positives / len(positives), 6),
        "usable_rate": round(usable_rate, 6),
        "false_positive_rate": None
        if not negatives
        else round(false_positives / len(negatives), 6),
        "duration_ms_p50": round(statistics.median(durations), 3),
        "duration_ms_p95": round(_percentile(durations, 0.95), 3),
        "duration_ms_max": round(max(durations), 3),
        "peak_rss_bytes": memory.peak_bytes,
        "corner_error_threshold": corner_error_threshold,
        "minimum_usable_rate": min_usable_rate,
        "minimum_positive_samples": minimum_positive_samples,
        "sample_count_sufficient": sample_count_sufficient,
        "gate_passed": sample_count_sufficient and usable_rate >= min_usable_rate,
    }
    return {
        "schema_version": 1,
        "dataset_id": manifest["dataset_id"],
        "evaluated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "samples": results,
    }


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    false_positive = summary["false_positive_rate"]
    false_positive_text = "不适用" if false_positive is None else f"{false_positive:.2%}"
    rows = [
        "# 文档透视评估报告",
        "",
        f"- 数据集：`{report['dataset_id']}`",
        f"- 评估时间：`{report['evaluated_at']}`",
        f"- 正样本：{summary['positive_samples']}",
        f"- 负样本：{summary['negative_samples']}",
        f"- 检测召回率：{summary['detection_recall']:.2%}",
        f"- 透视可用率：{summary['usable_rate']:.2%}",
        f"- 误检率：{false_positive_text}",
        f"- 耗时 P50 / P95 / 最大值：{summary['duration_ms_p50']:.3f} / {summary['duration_ms_p95']:.3f} / {summary['duration_ms_max']:.3f} ms",
        f"- 进程峰值 RSS：{summary['peak_rss_bytes'] / 1024 / 1024:.2f} MiB",
        f"- 门槛：{summary['minimum_usable_rate']:.2%}",
        f"- 最少正样本：{summary['minimum_positive_samples']}（{'满足' if summary['sample_count_sufficient'] else '不足'}）",
        f"- 结果：{'通过' if summary['gate_passed'] else '未通过'}",
        "",
        "| 样本 | 分类 | 文档 | 检测 | 角点误差 | 可用 | 耗时 ms |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for sample in report["samples"]:
        error = sample["corner_error_normalized"]
        rows.append(
            f"| {sample['id']} | {sample['category']} | {'是' if sample['document_present'] else '否'} | "
            f"{'是' if sample['detected'] else '否'} | {'—' if error is None else f'{error:.4f}'} | "
            f"{'是' if sample['usable'] or sample['negative_correct'] else '否'} | {sample['duration_ms']:.3f} |"
        )
    rows.append("")
    rows.append("本报告不包含图片、原始路径或个人数据；真实门槛结论必须基于已授权固定数据集。")
    return "\n".join(rows) + "\n"


def write_reports(report: dict[str, Any], output_directory: Path) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "perspective-report.json"
    markdown_path = output_directory / "perspective-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="评估 SmartScan 文档边缘与透视校正")
    parser.add_argument("manifest", type=Path, help="授权固定数据集 manifest.json")
    parser.add_argument("--output", type=Path, default=Path("reports/perspective"))
    parser.add_argument("--corner-error-threshold", type=float, default=0.03)
    parser.add_argument("--minimum-usable-rate", type=float, default=0.95)
    parser.add_argument("--minimum-positive-samples", type=int, default=100)
    parser.add_argument("--max-image-pixels", type=int, default=50_000_000)
    parser.add_argument("--save-previews", action="store_true")
    parser.add_argument("--fail-below-target", action="store_true")
    args = parser.parse_args()
    report = evaluate_manifest(
        args.manifest,
        corner_error_threshold=args.corner_error_threshold,
        min_usable_rate=args.minimum_usable_rate,
        minimum_positive_samples=args.minimum_positive_samples,
        max_image_pixels=args.max_image_pixels,
        preview_directory=args.output / "previews" if args.save_previews else None,
    )
    json_path, markdown_path = write_reports(report, args.output)
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{markdown_path}")
    print(f"透视可用率：{report['summary']['usable_rate']:.2%}")
    if args.fail_below_target and not report["summary"]["gate_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
