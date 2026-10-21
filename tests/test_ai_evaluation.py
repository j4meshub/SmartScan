from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image

AI_GATEWAY_ROOT = Path(__file__).resolve().parents[1] / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

from app.evaluation import EvaluationInputError, evaluate_runs

from tools.evaluate_ai_providers import write_reports


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task(task_type: str, image_sha: str, width: int, height: int) -> dict:
    task_id = str(uuid4())
    payload = {
        "schema_version": "1.0",
        "task_id": task_id,
        "task_type": task_type,
        "context": {
            "page_id": str(uuid4()),
            "source_result_version": 1,
            "media": {
                "asset_id": str(uuid4()),
                "sha256": image_sha,
                "mime_type": "image/png",
                "width": width,
                "height": height,
            },
            "locale": "zh-CN",
        },
        "constraints": {"temperature": 0.0, "max_output_tokens": 1024},
        "parameters": {},
    }
    if task_type == "review_cleanup_mask":
        payload["parameters"] = {
            "candidates": [
                {
                    "region_id": "r1",
                    "box": {"x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2},
                    "deterministic_hint": "color_mark",
                }
            ]
        }
    elif task_type == "review_book_split":
        payload["parameters"] = {
            "reading_order": "ltr",
            "deterministic_gutter_x": 0.5,
            "deterministic_confidence": 0.7,
        }
    return payload


def _result(task: dict) -> tuple[dict, dict]:
    base = {
        "schema_version": "1.0",
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "confidence": 0.95,
    }
    task_type = task["task_type"]
    if task_type == "classify_page":
        return {**base, "label": "exam", "evidence_codes": ["dense_question_layout"]}, {
            "label": "exam"
        }
    if task_type == "detect_orientation":
        return {**base, "rotation_degrees": 90, "evidence_codes": ["text_direction"]}, {
            "rotation_degrees": 90
        }
    if task_type == "extract_title":
        return {
            **base,
            "candidates": [{"text": "期末  试卷", "confidence": 0.96, "source": "header"}],
        }, {"accepted_titles": ["期末 试卷"]}
    if task_type == "extract_page_number":
        return {
            **base,
            "status": "detected",
            "normalized_number": 12,
            "raw_label": "12",
            "style": "arabic",
        }, {"status": "detected", "normalized_number": 12, "style": "arabic"}
    if task_type == "ocr_formula":
        return {
            **base,
            "blocks": [
                {
                    "block_type": "formula",
                    "block_id": "f1",
                    "box": {"x0": 0.1, "y0": 0.1, "x1": 0.8, "y1": 0.3},
                    "confidence": 0.93,
                    "latex_candidate": "x ^ 2",
                }
            ],
        }, {"required_claims": ["formula:x ^ 2"], "allowed_claims": ["formula:x ^ 2"]}
    if task_type == "review_cleanup_mask":
        return {
            **base,
            "decisions": [
                {
                    "region_id": "r1",
                    "region_type": "color_mark",
                    "action": "remove",
                    "confidence": 0.95,
                }
            ],
        }, {"decisions": [{"region_id": "r1", "region_type": "color_mark", "action": "remove"}]}
    box_left = {"x0": 0.0, "y0": 0.0, "x1": 0.48, "y1": 1.0}
    box_right = {"x0": 0.52, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    return {
        **base,
        "decision": "double_page",
        "reading_order": "ltr",
        "gutter_x": 0.5,
        "left_box": box_left,
        "right_box": box_right,
    }, {
        "decision": "double_page",
        "reading_order": "ltr",
        "gutter_x": 0.5,
        "left_box": box_left,
        "right_box": box_right,
        "gutter_tolerance": 0.02,
        "minimum_iou": 0.9,
    }


def _dataset(root: Path) -> tuple[Path, Path, dict, dict]:
    images = root / "images"
    images.mkdir(parents=True)
    image_path = images / "sample.png"
    Image.new("RGB", (100, 80), "white").save(image_path)
    digest = _sha256(image_path)
    task_types = [
        "classify_page",
        "detect_orientation",
        "extract_title",
        "extract_page_number",
        "ocr_formula",
        "review_cleanup_mask",
        "review_book_split",
    ]
    samples = []
    results = {}
    for index, task_type in enumerate(task_types, start=1):
        task = _task(task_type, digest, 100, 80)
        result, expected = _result(task)
        sample_id = f"sample-{index}"
        samples.append(
            {
                "id": sample_id,
                "source_group": f"group-{index}",
                "split": "test",
                "category": task_type,
                "language": "zh-CN",
                "path": "images/sample.png",
                "sha256": digest,
                "task": task,
                "expected": expected,
            }
        )
        results[sample_id] = result
    manifest = {
        "schema_version": 1,
        "dataset_id": "synthetic-ai-ci",
        "dataset_version": "1.0.0",
        "authorization": {
            "approved": True,
            "deidentified": True,
            "license": "测试代码生成，无第三方数据",
            "consent_reference": "CI-SYNTHETIC-AI-001",
            "purpose": "固定评估框架回归",
        },
        "split_policy": {
            "group_by": "source_group",
            "reviewed": True,
            "review_reference": "CI-SPLIT-001",
        },
        "thresholds": {
            "minimum_test_samples": 7,
            "minimum_accuracy": 0.99,
            "minimum_structured_success_rate": 0.99,
            "maximum_hallucination_rate": 0.01,
            "maximum_latency_ms_p95": 1000,
            "maximum_average_cost_microusd": 1000,
            "approved_by": "测试负责人",
            "approval_reference": "CI-THRESHOLD-001",
        },
        "core_flow_evidence": {
            "external_ai_disabled": True,
            "sample_count": 7,
            "completion_rate": 1.0,
            "evidence_reference": "CI-CORE-FLOW-001",
            "reviewed": True,
        },
        "samples": samples,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    run = {
        "schema_version": 1,
        "run_id": "ci-perfect-run",
        "dataset_id": manifest["dataset_id"],
        "dataset_sha256": _sha256(manifest_path),
        "system": {
            "system_id": "baseline-ci",
            "kind": "baseline_ocr",
            "model_version": "paddleocr-3.7.0",
            "framework_version": "smartscan-1.0.0",
            "prompt_version": "no-prompt-1",
            "adapter_version": "baseline-adapter-1.0.0",
            "quantization_version": "cpu-fp32-v1",
            "execution_mode": "local_baseline",
            "configuration_sha256": "a" * 64,
            "pricing_reference": "内部 CPU 成本口径 2026-10",
            "data_policy_reference": "CI 不出网",
        },
        "observations": [
            {
                "sample_id": sample_id,
                "status": "success",
                "raw_output": result,
                "duration_ms": 10 + index,
                "cost_microusd": 1,
            }
            for index, (sample_id, result) in enumerate(results.items())
        ],
    }
    run_path = root / "run.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return manifest_path, run_path, manifest, run


def _four_system_runs(root: Path, base_run: dict) -> list[Path]:
    systems = [
        ("baseline-ci", "baseline_ocr", "local_baseline"),
        ("professional-ci", "professional_ocr", "actual_api"),
        ("public-vlm-ci", "public_vlm", "actual_api"),
        ("custom-vlm-ci", "custom_vlm", "actual_api"),
    ]
    paths = []
    for index, (system_id, kind, execution_mode) in enumerate(systems):
        run = deepcopy(base_run)
        run["run_id"] = f"run-{index}"
        run["system"]["system_id"] = system_id
        run["system"]["kind"] = kind
        run["system"]["execution_mode"] = execution_mode
        path = root / f"run-{index}.json"
        path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
        paths.append(path)
    return paths


def test_all_seven_tasks_and_four_system_kinds_pass(tmp_path: Path) -> None:
    manifest_path, _, _, run = _dataset(tmp_path)

    report = evaluate_runs(manifest_path, _four_system_runs(tmp_path, run))

    system = report["systems"][0]
    assert report["dataset"]["test_samples"] == 7
    assert report["comparison_complete"] is True
    assert report["missing_system_kinds"] == []
    assert report["all_systems_passed"] is True
    assert system["overall"]["accuracy"] == 1.0
    assert system["overall"]["structured_success_rate"] == 1.0
    assert system["overall"]["hallucination_rate"] == 0.0
    assert len(system["by_task"]) == 7
    assert system["system"]["model_version"] == "paddleocr-3.7.0"


def test_structured_failure_and_unsupported_claim_keep_gate_closed(tmp_path: Path) -> None:
    manifest_path, run_path, _, run = _dataset(tmp_path)
    run["observations"][0]["raw_output"]["label"] = "book_page"
    run["observations"][1]["raw_output"] = {"not": "the contract"}
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    report = evaluate_runs(manifest_path, [run_path])
    metrics = report["systems"][0]["overall"]

    assert metrics["accuracy"] < 1
    assert metrics["structured_success_rate"] == pytest.approx(6 / 7, abs=1e-6)
    assert metrics["hallucination_rate"] > 0
    assert report["all_systems_passed"] is False
    assert report["systems"][0]["samples"][1]["error_code"] == ("structured_validation_failed")


def test_reports_exclude_raw_output_paths_and_secrets(tmp_path: Path) -> None:
    manifest_path, run_path, _, run = _dataset(tmp_path)
    run["observations"][0]["raw_output"]["evidence_codes"] = ["ordinary_layout"]
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    report = evaluate_runs(manifest_path, [run_path])

    json_path, markdown_path = write_reports(report, tmp_path / "reports")
    rendered = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")

    assert str(tmp_path) not in rendered
    assert "raw_output" not in rendered
    assert "images/sample.png" not in rendered
    assert "token" not in rendered.casefold()


def test_partial_comparison_never_opens_overall_gate(tmp_path: Path) -> None:
    manifest_path, run_path, _, _ = _dataset(tmp_path)

    report = evaluate_runs(manifest_path, [run_path])

    assert report["systems"][0]["gate"]["passed"] is True
    assert report["comparison_complete"] is False
    assert report["missing_system_kinds"] == ["custom_vlm", "professional_ocr", "public_vlm"]
    assert report["all_systems_passed"] is False


@pytest.mark.parametrize("case", ["hash", "traversal", "leakage", "latest"])
def test_rejects_untrusted_or_non_reproducible_manifest(tmp_path: Path, case: str) -> None:
    manifest_path, run_path, manifest, run = _dataset(tmp_path)
    if case == "hash":
        manifest["samples"][0]["sha256"] = "0" * 64
    elif case == "traversal":
        outside = tmp_path.parent / f"outside-{tmp_path.name}.png"
        Image.new("RGB", (100, 80), "white").save(outside)
        manifest["samples"][0]["path"] = f"../../{outside.name}"
        manifest["samples"][0]["sha256"] = _sha256(outside)
        manifest["samples"][0]["task"]["context"]["media"]["sha256"] = _sha256(outside)
    elif case == "leakage":
        extra = deepcopy(manifest["samples"][0])
        extra["id"] = "train-copy"
        extra["split"] = "train"
        manifest["samples"].append(extra)
    else:
        manifest["dataset_version"] = "latest"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    run["dataset_sha256"] = _sha256(manifest_path)
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(EvaluationInputError):
        evaluate_runs(manifest_path, [run_path])


def test_rejects_dataset_mismatch_incomplete_coverage_and_duplicate_system(
    tmp_path: Path,
) -> None:
    manifest_path, run_path, _, run = _dataset(tmp_path)
    run["dataset_sha256"] = "f" * 64
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(EvaluationInputError, match="版本不匹配"):
        evaluate_runs(manifest_path, [run_path])

    run["dataset_sha256"] = _sha256(manifest_path)
    run["observations"].pop()
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(EvaluationInputError, match="未完整覆盖"):
        evaluate_runs(manifest_path, [run_path])

    _, run_path, _, _ = _dataset(tmp_path / "second")
    with pytest.raises(EvaluationInputError, match="系统 ID 重复"):
        evaluate_runs(tmp_path / "second" / "manifest.json", [run_path, run_path])


def test_task_id_is_uuid_and_never_leaks_as_media_identity(tmp_path: Path) -> None:
    manifest_path, run_path, manifest, _ = _dataset(tmp_path)
    report = evaluate_runs(manifest_path, [run_path])

    assert UUID(manifest["samples"][0]["task"]["task_id"])
    assert "task_id" not in json.dumps(report)


def test_external_system_requires_actual_api_and_core_flow_must_be_complete(
    tmp_path: Path,
) -> None:
    manifest_path, run_path, manifest, run = _dataset(tmp_path)
    run["system"]["kind"] = "public_vlm"
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(EvaluationInputError, match="actual_api"):
        evaluate_runs(manifest_path, [run_path])

    run["system"]["execution_mode"] = "actual_api"
    manifest["core_flow_evidence"]["completion_rate"] = 0.99
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    run["dataset_sha256"] = _sha256(manifest_path)
    run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")

    report = evaluate_runs(manifest_path, [run_path])

    assert report["systems"][0]["gate"]["core_flow_completion"] is False
    assert report["all_systems_passed"] is False
