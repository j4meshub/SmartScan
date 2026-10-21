"""可选视觉 AI 的固定数据集离线评估框架。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .tasks import (
    StructuredTaskError,
    TaskType,
    result_schema_digest,
    validate_result,
    validate_task,
)

SCHEMA_VERSION = 1
EVALUATOR_VERSION = "1.0.0"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UNVERSIONED = re.compile(r"^(latest|current|unknown|unspecified|n/a)$", re.IGNORECASE)
REQUIRED_SYSTEM_KINDS = {
    "baseline_ocr",
    "professional_ocr",
    "public_vlm",
    "custom_vlm",
}


class EvaluationInputError(ValueError):
    """评估输入未满足安全或可复现要求。"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Authorization(StrictModel):
    approved: Literal[True]
    deidentified: Literal[True]
    license: str = Field(min_length=1)
    consent_reference: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class SplitPolicy(StrictModel):
    group_by: Literal["source_group"]
    reviewed: Literal[True]
    review_reference: str = Field(min_length=1)


class Thresholds(StrictModel):
    minimum_test_samples: int = Field(ge=1)
    minimum_accuracy: float = Field(ge=0, le=1)
    minimum_structured_success_rate: float = Field(ge=0, le=1)
    maximum_hallucination_rate: float = Field(ge=0, le=1)
    maximum_latency_ms_p95: float = Field(gt=0)
    maximum_average_cost_microusd: float = Field(ge=0)
    approved_by: str = Field(min_length=1)
    approval_reference: str = Field(min_length=1)


class CoreFlowEvidence(StrictModel):
    external_ai_disabled: Literal[True]
    sample_count: int = Field(ge=1)
    completion_rate: float = Field(ge=0, le=1)
    evidence_reference: str = Field(min_length=1)
    reviewed: Literal[True]


class EvaluationSample(StrictModel):
    id: str
    source_group: str
    split: Literal["train", "validation", "test"]
    category: str = Field(min_length=1)
    language: Literal["zh-CN", "en", "mixed"]
    path: str = Field(min_length=1)
    sha256: str
    task: dict[str, Any]
    expected: dict[str, Any]

    @field_validator("id", "source_group")
    @classmethod
    def validate_safe_id(cls, value: str) -> str:
        if SAFE_ID.fullmatch(value) is None:
            raise ValueError("必须是安全标识符")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("SHA-256 无效")
        return value


class EvaluationManifest(StrictModel):
    schema_version: Literal[1]
    dataset_id: str
    dataset_version: str
    authorization: Authorization
    split_policy: SplitPolicy
    thresholds: Thresholds
    core_flow_evidence: CoreFlowEvidence
    samples: list[EvaluationSample] = Field(min_length=1)

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, value: str) -> str:
        if SAFE_ID.fullmatch(value) is None:
            raise ValueError("数据集 ID 必须是安全标识符")
        return value

    @field_validator("dataset_version")
    @classmethod
    def validate_dataset_version(cls, value: str) -> str:
        _require_version(value, "dataset_version")
        return value

    @model_validator(mode="after")
    def validate_unique_samples_and_splits(self) -> EvaluationManifest:
        ids = [sample.id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("样本 ID 不得重复")
        group_splits: dict[str, set[str]] = defaultdict(set)
        for sample in self.samples:
            group_splits[sample.source_group].add(sample.split)
        leaked = sorted(group for group, splits in group_splits.items() if len(splits) > 1)
        if leaked:
            raise ValueError(f"同一来源组跨越多个数据切分：{', '.join(leaked)}")
        if not any(sample.split == "test" for sample in self.samples):
            raise ValueError("固定数据集必须包含 test 样本")
        return self


class SystemMetadata(StrictModel):
    system_id: str
    kind: Literal["baseline_ocr", "professional_ocr", "public_vlm", "custom_vlm"]
    model_version: str
    framework_version: str
    prompt_version: str
    adapter_version: str
    quantization_version: str
    execution_mode: Literal["actual_api", "local_baseline"]
    configuration_sha256: str
    pricing_reference: str = Field(min_length=1)
    data_policy_reference: str = Field(min_length=1)

    @field_validator("system_id")
    @classmethod
    def validate_system_id(cls, value: str) -> str:
        if SAFE_ID.fullmatch(value) is None:
            raise ValueError("系统 ID 必须是安全标识符")
        return value

    @field_validator(
        "model_version",
        "framework_version",
        "prompt_version",
        "adapter_version",
        "quantization_version",
    )
    @classmethod
    def validate_version(cls, value: str, info: Any) -> str:
        _require_version(value, info.field_name)
        return value

    @field_validator("configuration_sha256")
    @classmethod
    def validate_configuration_digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("configuration_sha256 无效")
        return value

    @model_validator(mode="after")
    def validate_execution_mode(self) -> SystemMetadata:
        if self.kind == "baseline_ocr" and self.execution_mode != "local_baseline":
            raise ValueError("基础 OCR 必须记录为 local_baseline")
        if self.kind != "baseline_ocr" and self.execution_mode != "actual_api":
            raise ValueError("外部 Provider 必须来自 actual_api，不能用网页演示或 Mock")
        return self


class RunObservation(StrictModel):
    sample_id: str
    status: Literal[
        "success", "timeout", "provider_error", "transport_error", "parse_error", "skipped"
    ]
    raw_output: str | dict[str, Any] | None = None
    duration_ms: float = Field(ge=0)
    cost_microusd: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_output(self) -> RunObservation:
        if self.status == "success" and self.raw_output is None:
            raise ValueError("成功观察必须包含 raw_output")
        if self.status != "success" and self.raw_output is not None:
            raise ValueError("失败观察不得携带未经验证的 raw_output")
        return self


class EvaluationRun(StrictModel):
    schema_version: Literal[1]
    run_id: str
    dataset_id: str
    dataset_sha256: str
    system: SystemMetadata
    observations: list[RunObservation] = Field(min_length=1)

    @field_validator("run_id", "dataset_id")
    @classmethod
    def validate_safe_id(cls, value: str) -> str:
        if SAFE_ID.fullmatch(value) is None:
            raise ValueError("必须是安全标识符")
        return value

    @field_validator("dataset_sha256")
    @classmethod
    def validate_dataset_digest(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("dataset_sha256 无效")
        return value

    @model_validator(mode="after")
    def validate_unique_observations(self) -> EvaluationRun:
        ids = [item.sample_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("运行结果中的样本 ID 不得重复")
        return self


def _require_version(value: str, field: str) -> None:
    if not value.strip() or UNVERSIONED.fullmatch(value.strip()):
        raise ValueError(f"{field} 必须是固定版本，不能使用 latest 或占位值")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationInputError(f"无法读取{label}") from exc
    if not isinstance(payload, dict):
        raise EvaluationInputError(f"{label}根节点必须是对象")
    return payload


def _digest_file(path: Path, *, maximum_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            total += len(block)
            if maximum_bytes is not None and total > maximum_bytes:
                raise EvaluationInputError(f"文件超过 {maximum_bytes} 字节上限")
            digest.update(block)
    return digest.hexdigest()


def _manifest_digest(path: Path) -> str:
    return _digest_file(path)


def _resolve_image(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EvaluationInputError("样本路径越出数据集目录") from exc
    if not candidate.is_file():
        raise EvaluationInputError(f"样本文件不存在：{relative_path}")
    if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise EvaluationInputError(f"样本格式不受支持：{relative_path}")
    return candidate


def _validate_expected(task_type: TaskType, expected: dict[str, Any]) -> None:
    required: dict[TaskType, set[str]] = {
        TaskType.CLASSIFY_PAGE: {"label"},
        TaskType.DETECT_ORIENTATION: {"rotation_degrees"},
        TaskType.EXTRACT_TITLE: {"accepted_titles"},
        TaskType.EXTRACT_PAGE_NUMBER: {"status", "normalized_number", "style"},
        TaskType.OCR_FORMULA: {"required_claims", "allowed_claims"},
        TaskType.REVIEW_CLEANUP_MASK: {"decisions"},
        TaskType.REVIEW_BOOK_SPLIT: {"decision", "reading_order"},
    }
    missing = required[task_type] - set(expected)
    if missing:
        raise EvaluationInputError(
            f"{task_type.value} 的期望标注缺少字段：{', '.join(sorted(missing))}"
        )
    allowed_fields = {
        TaskType.CLASSIFY_PAGE: {"label"},
        TaskType.DETECT_ORIENTATION: {"rotation_degrees"},
        TaskType.EXTRACT_TITLE: {"accepted_titles"},
        TaskType.EXTRACT_PAGE_NUMBER: {"status", "normalized_number", "style"},
        TaskType.OCR_FORMULA: {"required_claims", "allowed_claims"},
        TaskType.REVIEW_CLEANUP_MASK: {"decisions"},
        TaskType.REVIEW_BOOK_SPLIT: {
            "decision",
            "reading_order",
            "gutter_x",
            "left_box",
            "right_box",
            "gutter_tolerance",
            "minimum_iou",
        },
    }
    unknown = set(expected) - allowed_fields[task_type]
    if unknown:
        raise EvaluationInputError(
            f"{task_type.value} 的期望标注包含未知字段：{', '.join(sorted(unknown))}"
        )
    if task_type == TaskType.CLASSIFY_PAGE:
        if expected["label"] not in {"ordinary_document", "exam", "book_page", "cover"}:
            raise EvaluationInputError("分类期望标签无效")
    elif task_type == TaskType.DETECT_ORIENTATION:
        if expected["rotation_degrees"] not in {0, 90, 180, 270}:
            raise EvaluationInputError("方向期望值无效")
    elif task_type == TaskType.EXTRACT_TITLE:
        titles = expected["accepted_titles"]
        if not isinstance(titles, list) or any(not isinstance(item, str) for item in titles):
            raise EvaluationInputError("accepted_titles 必须是字符串数组")
    elif task_type == TaskType.OCR_FORMULA:
        required_claims = expected["required_claims"]
        allowed_claims = expected["allowed_claims"]
        if not isinstance(required_claims, list) or not isinstance(allowed_claims, list):
            raise EvaluationInputError("OCR claims 必须是数组")
        if not set(required_claims) <= set(allowed_claims):
            raise EvaluationInputError("required_claims 必须包含在 allowed_claims 中")
    elif task_type == TaskType.REVIEW_CLEANUP_MASK:
        if not isinstance(expected["decisions"], list):
            raise EvaluationInputError("decisions 必须是数组")
        for item in expected["decisions"]:
            if not isinstance(item, dict) or set(item) != {"region_id", "region_type", "action"}:
                raise EvaluationInputError("净化期望决策格式无效")
    elif task_type == TaskType.REVIEW_BOOK_SPLIT:
        decision = expected["decision"]
        if decision not in {"double_page", "single_page", "uncertain"}:
            raise EvaluationInputError("双页期望决策无效")
        if expected["reading_order"] not in {"ltr", "rtl"}:
            raise EvaluationInputError("阅读顺序无效")
        geometry = ("gutter_x", "left_box", "right_box")
        if decision == "double_page" and any(field not in expected for field in geometry):
            raise EvaluationInputError("双页期望标注缺少几何信息")


def load_manifest(path: Path) -> tuple[EvaluationManifest, str]:
    path = path.resolve()
    try:
        manifest = EvaluationManifest.model_validate(_read_json(path, "评估清单"))
    except ValueError as exc:
        raise EvaluationInputError(f"评估清单无效：{exc}") from exc
    for sample in manifest.samples:
        image_path = _resolve_image(path.parent, sample.path)
        if _digest_file(image_path, maximum_bytes=MAX_IMAGE_BYTES) != sample.sha256:
            raise EvaluationInputError(f"样本 {sample.id} 的 SHA-256 不匹配")
        try:
            with Image.open(image_path) as image:
                image.verify()
                width, height = image.size
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise EvaluationInputError(f"无法解码样本 {sample.id}") from exc
        if width * height > MAX_IMAGE_PIXELS:
            raise EvaluationInputError(f"样本 {sample.id} 超过像素上限")
        try:
            task = validate_task(sample.task)
        except ValueError as exc:
            raise EvaluationInputError(f"样本 {sample.id} 的结构化任务无效") from exc
        if task.context.media.sha256 != sample.sha256:
            raise EvaluationInputError(f"样本 {sample.id} 的任务媒体摘要不匹配")
        if (task.context.media.width, task.context.media.height) != (width, height):
            raise EvaluationInputError(f"样本 {sample.id} 的任务媒体尺寸不匹配")
        _validate_expected(task.task_type, sample.expected)
    return manifest, _manifest_digest(path)


def _normalize_text(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _box_iou(left: dict[str, float], right: dict[str, float]) -> float:
    x0, y0 = max(left["x0"], right["x0"]), max(left["y0"], right["y0"])
    x1, y1 = min(left["x1"], right["x1"]), min(left["y1"], right["y1"])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = (left["x1"] - left["x0"]) * (left["y1"] - left["y0"])
    right_area = (right["x1"] - right["x0"]) * (right["y1"] - right["y0"])
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union


def _ocr_claims(result: dict[str, Any]) -> set[str]:
    claims: set[str] = set()
    for block in result["blocks"]:
        if block["block_type"] == "formula":
            claims.add(f"formula:{_normalize_text(block['latex_candidate'])}")
        elif block["block_type"] == "table":
            cells = sorted(
                (cell["row"], cell["column"], _normalize_text(cell["text_candidate"]))
                for cell in block["cells"]
            )
            claims.add("table:" + json.dumps(cells, ensure_ascii=False, separators=(",", ":")))
        else:
            claims.add(f"layout:{block['role']}:{_normalize_text(block.get('text_candidate'))}")
    return claims


def score_result(
    task_type: TaskType, result: dict[str, Any], expected: dict[str, Any]
) -> tuple[float, int, int]:
    """返回准确率分值、预测声明数、无依据声明数。"""
    if task_type == TaskType.CLASSIFY_PAGE:
        correct = result["label"] == expected["label"]
        return float(correct), 1, int(not correct)
    if task_type == TaskType.DETECT_ORIENTATION:
        correct = result["rotation_degrees"] == expected["rotation_degrees"]
        return float(correct), 1, int(not correct)
    if task_type == TaskType.EXTRACT_TITLE:
        allowed = {_normalize_text(item) for item in expected["accepted_titles"]}
        predicted = [_normalize_text(item["text"]) for item in result["candidates"]]
        correct = (not allowed and not predicted) or any(item in allowed for item in predicted)
        return float(correct), len(predicted), sum(item not in allowed for item in predicted)
    if task_type == TaskType.EXTRACT_PAGE_NUMBER:
        fields = ("status", "normalized_number", "style")
        correct = all(result.get(field) == expected.get(field) for field in fields)
        predicted = int(result["status"] == "detected")
        unsupported = int(predicted and not correct)
        return float(correct), predicted, unsupported
    if task_type == TaskType.OCR_FORMULA:
        predicted_claims = _ocr_claims(result)
        required = set(expected["required_claims"])
        allowed = set(expected["allowed_claims"])
        true_positive = len(predicted_claims & required)
        precision = true_positive / len(predicted_claims) if predicted_claims else int(not required)
        recall = true_positive / len(required) if required else 1.0
        score = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        return score, len(predicted_claims), len(predicted_claims - allowed)
    if task_type == TaskType.REVIEW_CLEANUP_MASK:
        expected_by_id = {item["region_id"]: item for item in expected["decisions"]}
        decisions = result["decisions"]
        correct = sum(
            item["region_id"] in expected_by_id
            and item["region_type"] == expected_by_id[item["region_id"]]["region_type"]
            and item["action"] == expected_by_id[item["region_id"]]["action"]
            for item in decisions
        )
        denominator = max(len(expected_by_id), len(decisions), 1)
        return correct / denominator, len(decisions), len(decisions) - correct

    components = [result["decision"] == expected["decision"]]
    components.append(result["reading_order"] == expected["reading_order"])
    if expected["decision"] == "double_page":
        tolerance = float(expected.get("gutter_tolerance", 0.03))
        minimum_iou = float(expected.get("minimum_iou", 0.8))
        components.extend(
            [
                result.get("gutter_x") is not None
                and abs(result["gutter_x"] - expected["gutter_x"]) <= tolerance,
                result.get("left_box") is not None
                and _box_iou(result["left_box"], expected["left_box"]) >= minimum_iou,
                result.get("right_box") is not None
                and _box_iou(result["right_box"], expected["right_box"]) >= minimum_iou,
            ]
        )
    correct = sum(components)
    return correct / len(components), len(components), len(components) - correct


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _metric_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [item["duration_ms"] for item in records]
    predicted = sum(item["predicted_claims"] for item in records)
    unsupported = sum(item["unsupported_claims"] for item in records)
    return {
        "samples": len(records),
        "accuracy": round(statistics.fmean(item["accuracy"] for item in records), 6),
        "structured_success_rate": round(
            sum(item["structured_success"] for item in records) / len(records), 6
        ),
        "hallucination_rate": round(unsupported / predicted, 6) if predicted else 0.0,
        "predicted_claims": predicted,
        "unsupported_claims": unsupported,
        "latency_ms_p50": round(statistics.median(durations), 3),
        "latency_ms_p95": round(_percentile(durations, 0.95), 3),
        "average_cost_microusd": round(
            statistics.fmean(item["cost_microusd"] for item in records), 3
        ),
        "total_cost_microusd": sum(item["cost_microusd"] for item in records),
    }


def _gate(metrics: dict[str, Any], thresholds: Thresholds) -> dict[str, bool]:
    checks = {
        "sample_count": metrics["samples"] >= thresholds.minimum_test_samples,
        "accuracy": metrics["accuracy"] >= thresholds.minimum_accuracy,
        "structured_success_rate": metrics["structured_success_rate"]
        >= thresholds.minimum_structured_success_rate,
        "hallucination_rate": metrics["hallucination_rate"]
        <= thresholds.maximum_hallucination_rate,
        "latency_ms_p95": metrics["latency_ms_p95"] <= thresholds.maximum_latency_ms_p95,
        "average_cost_microusd": metrics["average_cost_microusd"]
        <= thresholds.maximum_average_cost_microusd,
    }
    return {**checks, "passed": all(checks.values())}


def evaluate_runs(manifest_path: Path, run_paths: list[Path]) -> dict[str, Any]:
    if not run_paths:
        raise EvaluationInputError("至少需要一个运行结果文件")
    manifest, manifest_digest = load_manifest(manifest_path)
    test_samples = {sample.id: sample for sample in manifest.samples if sample.split == "test"}
    systems: list[dict[str, Any]] = []
    seen_systems: set[str] = set()
    for run_path in run_paths:
        try:
            run = EvaluationRun.model_validate(_read_json(run_path.resolve(), "运行结果"))
        except ValueError as exc:
            raise EvaluationInputError(f"运行结果无效：{exc}") from exc
        if run.dataset_id != manifest.dataset_id or run.dataset_sha256 != manifest_digest:
            raise EvaluationInputError(f"运行 {run.run_id} 与固定数据集版本不匹配")
        if run.system.system_id in seen_systems:
            raise EvaluationInputError(f"系统 ID 重复：{run.system.system_id}")
        seen_systems.add(run.system.system_id)
        observations = {item.sample_id: item for item in run.observations}
        if set(observations) != set(test_samples):
            missing = sorted(set(test_samples) - set(observations))
            extra = sorted(set(observations) - set(test_samples))
            raise EvaluationInputError(
                f"运行 {run.run_id} 未完整覆盖 test 集；缺少={missing}，多余={extra}"
            )
        records: list[dict[str, Any]] = []
        for sample_id, sample in test_samples.items():
            observation = observations[sample_id]
            structured_success = False
            score, predicted, unsupported = 0.0, 0, 0
            error_code = observation.status if observation.status != "success" else None
            if observation.status == "success":
                task = validate_task(sample.task)
                try:
                    result, _ = validate_result(task, observation.raw_output or {})
                    structured_success = True
                    score, predicted, unsupported = score_result(
                        task.task_type,
                        result.model_dump(mode="json"),
                        sample.expected,
                    )
                except (StructuredTaskError, ValueError):
                    error_code = "structured_validation_failed"
            records.append(
                {
                    "sample_id": sample_id,
                    "task_type": sample.task["task_type"],
                    "status": observation.status,
                    "structured_success": structured_success,
                    "error_code": error_code,
                    "accuracy": round(score, 6),
                    "predicted_claims": predicted,
                    "unsupported_claims": unsupported,
                    "duration_ms": observation.duration_ms,
                    "cost_microusd": observation.cost_microusd,
                }
            )
        overall = _metric_summary(records)
        by_task = {
            task_type: _metric_summary(
                [record for record in records if record["task_type"] == task_type]
            )
            for task_type in sorted({record["task_type"] for record in records})
        }
        gate = _gate(overall, manifest.thresholds)
        gate["core_flow_completion"] = manifest.core_flow_evidence.completion_rate == 1.0
        gate["passed"] = all(value for name, value in gate.items() if name != "passed")
        systems.append(
            {
                "run_id": run.run_id,
                "system": run.system.model_dump(mode="json"),
                "overall": overall,
                "by_task": by_task,
                "gate": gate,
                "samples": records,
            }
        )
    observed_kinds = {system["system"]["kind"] for system in systems}
    missing_system_kinds = sorted(REQUIRED_SYSTEM_KINDS - observed_kinds)
    comparison_complete = not missing_system_kinds
    return {
        "schema_version": 1,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "id": manifest.dataset_id,
            "version": manifest.dataset_version,
            "sha256": manifest_digest,
            "test_samples": len(test_samples),
            "thresholds": manifest.thresholds.model_dump(mode="json"),
            "core_flow_evidence": manifest.core_flow_evidence.model_dump(mode="json"),
            "result_schema_sha256": {
                task_type.value: result_schema_digest(task_type)
                for task_type in sorted(
                    {TaskType(sample.task["task_type"]) for sample in test_samples.values()},
                    key=lambda item: item.value,
                )
            },
        },
        "systems": systems,
        "comparison_complete": comparison_complete,
        "missing_system_kinds": missing_system_kinds,
        "all_systems_passed": comparison_complete
        and all(system["gate"]["passed"] for system in systems),
        "notice": "报告不包含图片、原始路径、原始模型输出、凭据或个人数据。",
    }


def schema_bundle() -> dict[str, Any]:
    return {
        "contract": "SmartScan 可选视觉 AI 固定评估输入",
        "schema_version": SCHEMA_VERSION,
        "manifest": EvaluationManifest.model_json_schema(),
        "run": EvaluationRun.model_json_schema(),
    }
