from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

AI_GATEWAY_ROOT = Path(__file__).parents[1] / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

main = importlib.import_module("app.main")
providers = importlib.import_module("app.providers")
tasks = importlib.import_module("app.tasks")
mock = importlib.import_module("app.mock")

TASK_ID = "10000000-0000-4000-8000-000000000001"
PAGE_ID = "20000000-0000-4000-8000-000000000002"
ASSET_ID = "30000000-0000-4000-8000-000000000003"


def task_payload(task_type: str, parameters: dict | None = None) -> dict:
    payload = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "task_type": task_type,
        "context": {
            "page_id": PAGE_ID,
            "source_result_version": 2,
            "media": {
                "asset_id": ASSET_ID,
                "sha256": "a" * 64,
                "mime_type": "image/jpeg",
                "width": 1200,
                "height": 1800,
            },
            "locale": "zh-CN",
        },
        "constraints": {"temperature": 0.0, "max_output_tokens": 1024},
    }
    if parameters is not None:
        payload["parameters"] = parameters
    return payload


def result_payload(task_type: str) -> dict:
    common = {
        "schema_version": "1.0",
        "task_id": TASK_ID,
        "task_type": task_type,
        "confidence": 0.96,
    }
    variants = {
        "classify_page": {
            "label": "exam",
            "evidence_codes": ["dense_question_layout", "answer_regions"],
        },
        "detect_orientation": {
            "rotation_degrees": 90,
            "evidence_codes": ["text_direction"],
        },
        "extract_title": {
            "candidates": [{"text": "高等数学", "confidence": 0.94, "source": "header"}]
        },
        "extract_page_number": {
            "status": "detected",
            "normalized_number": 12,
            "raw_label": "12",
            "style": "arabic",
        },
        "ocr_formula": {
            "blocks": [
                {
                    "block_type": "formula",
                    "block_id": "formula-1",
                    "box": {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.4},
                    "confidence": 0.93,
                    "latex_candidate": "x^2+y^2=z^2",
                }
            ]
        },
        "review_cleanup_mask": {
            "decisions": [
                {
                    "region_id": "region-1",
                    "region_type": "handwriting",
                    "action": "remove",
                    "confidence": 0.95,
                }
            ]
        },
        "review_book_split": {
            "decision": "double_page",
            "reading_order": "ltr",
            "gutter_x": 0.48,
            "left_box": {"x0": 0.0, "y0": 0.0, "x1": 0.47, "y1": 1.0},
            "right_box": {"x0": 0.49, "y0": 0.0, "x1": 1.0, "y1": 1.0},
        },
    }
    return common | variants[task_type]


def parameters_for(task_type: str) -> dict | None:
    return {
        "review_cleanup_mask": {
            "candidates": [
                {
                    "region_id": "region-1",
                    "box": {"x0": 0.1, "y0": 0.1, "x1": 0.3, "y1": 0.3},
                    "deterministic_hint": "color_mark",
                }
            ]
        },
        "review_book_split": {
            "reading_order": "ltr",
            "deterministic_gutter_x": 0.5,
            "deterministic_confidence": 0.61,
        },
    }.get(task_type)


@pytest.mark.parametrize("task_type", [item.value for item in tasks.TaskType])
def test_all_seven_task_and_result_contracts_validate(task_type: str) -> None:
    task = tasks.validate_task(task_payload(task_type, parameters_for(task_type)))
    result, disposition = tasks.validate_result(task, result_payload(task_type))

    assert task.task_type.value == task_type
    assert result.task_type.value == task_type
    assert disposition == tasks.ResultDisposition.CANDIDATE


@pytest.mark.parametrize("task_type", [item.value for item in tasks.TaskType])
def test_local_mock_returns_deterministic_valid_result_for_all_tasks(task_type: str) -> None:
    task = tasks.validate_task(task_payload(task_type, parameters_for(task_type)))

    first = mock.deterministic_mock_result(task)
    second = mock.deterministic_mock_result(task)
    result, _ = tasks.validate_result(task, first)

    assert first == second
    assert result.task_type.value == task_type
    if task_type == "ocr_formula":
        assert len(first["blocks"]) == 3
        assert "Mock" in first["blocks"][0]["latex_candidate"]


def test_schema_catalog_has_versioned_digest_for_every_task() -> None:
    catalog = tasks.task_schema_catalog()

    assert [item["task_type"].value for item in catalog] == [item.value for item in tasks.TaskType]
    assert len(catalog) == 7
    assert all(item["schema_version"] == "1.0" for item in catalog)
    assert all(len(item["result_schema_sha256"]) == 64 for item in catalog)
    assert all(item["task_schema"]["additionalProperties"] is False for item in catalog)
    assert all(item["result_schema"]["additionalProperties"] is False for item in catalog)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"unexpected": True}, "extra_forbidden"),
        ({"schema_version": "2.0"}, "literal_error"),
        ({"constraints": {"temperature": 0.2, "max_output_tokens": 1024}}, "literal_error"),
    ],
)
def test_task_contract_fails_closed(change: dict, expected: str) -> None:
    payload = task_payload("classify_page") | change

    with pytest.raises(ValidationError) as raised:
        tasks.validate_task(payload)
    assert expected in str(raised.value)


def test_normalized_boxes_require_positive_area() -> None:
    payload = task_payload(
        "review_cleanup_mask",
        {
            "candidates": [
                {
                    "region_id": "region-1",
                    "box": {"x0": 0.5, "y0": 0.1, "x1": 0.4, "y1": 0.3},
                }
            ]
        },
    )

    with pytest.raises(ValidationError, match="positive area"):
        tasks.validate_task(payload)


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        ('```json\n{"task_type":"classify_page"}\n```', "provider_output_invalid_json"),
        ('{"task_type":"classify_page","task_type":"extract_title"}', "duplicate_key"),
        ('{"confidence":NaN}', "non_finite_number"),
        ("[]", "must_be_object"),
        (b"\xff", "invalid_utf8"),
        ("x" * (tasks.MAX_PROVIDER_OUTPUT_BYTES + 1), "too_large"),
    ],
    ids=["markdown", "duplicate-key", "nan", "array", "invalid-utf8", "oversized"],
)
def test_provider_output_parser_rejects_non_strict_json(raw: bytes | str, error_code: str) -> None:
    with pytest.raises(tasks.StructuredTaskError, match=error_code):
        tasks.parse_provider_output(raw)


def test_result_must_match_original_task_identity() -> None:
    task = tasks.validate_task(task_payload("classify_page"))
    result = result_payload("classify_page")
    result["task_id"] = str(uuid.uuid4())

    with pytest.raises(tasks.StructuredTaskError, match="task_mismatch"):
        tasks.validate_result(task, result)


def test_page_number_never_invents_value_for_not_detected() -> None:
    task = tasks.validate_task(task_payload("extract_page_number"))
    result = result_payload("extract_page_number") | {
        "status": "not_detected",
        "normalized_number": 12,
    }

    with pytest.raises(ValidationError, match="must not invent"):
        tasks.validate_result(task, result)


def test_title_candidate_limit_and_low_confidence_require_review() -> None:
    task = tasks.validate_task(task_payload("extract_title", {"max_candidates": 1}))
    too_many = result_payload("extract_title")
    too_many["candidates"].append({"text": "第二候选", "confidence": 0.92, "source": "body"})
    with pytest.raises(tasks.StructuredTaskError, match="candidate_limit"):
        tasks.validate_result(task, too_many)

    low_confidence = result_payload("extract_title")
    low_confidence["candidates"][0]["confidence"] = 0.6
    _, disposition = tasks.validate_result(task, low_confidence)
    assert disposition == tasks.ResultDisposition.REVIEW


@pytest.mark.parametrize(
    "decision",
    [
        {
            "region_id": "region-1",
            "region_type": "printed_content",
            "action": "remove",
            "confidence": 0.99,
        },
        {
            "region_id": "region-1",
            "region_type": "handwriting",
            "action": "remove",
            "confidence": 0.89,
        },
    ],
)
def test_cleanup_never_removes_printed_or_low_confidence_region(decision: dict) -> None:
    task = tasks.validate_task(
        task_payload("review_cleanup_mask", parameters_for("review_cleanup_mask"))
    )
    result = result_payload("review_cleanup_mask")
    result["decisions"] = [decision]

    with pytest.raises(tasks.StructuredTaskError, match="cleanup_remove"):
        tasks.validate_result(task, result)


def test_cleanup_result_must_cover_exact_candidate_set() -> None:
    task = tasks.validate_task(
        task_payload("review_cleanup_mask", parameters_for("review_cleanup_mask"))
    )
    result = result_payload("review_cleanup_mask")
    result["decisions"][0]["region_id"] = "invented-region"

    with pytest.raises(tasks.StructuredTaskError, match="region_set_mismatch"):
        tasks.validate_result(task, result)


def test_formula_result_cannot_return_unrequested_block_type() -> None:
    task = tasks.validate_task(task_payload("ocr_formula", {"requested_blocks": ["table"]}))

    with pytest.raises(tasks.StructuredTaskError, match="not_requested"):
        tasks.validate_result(task, result_payload("ocr_formula"))


def test_book_split_requires_geometry_and_matching_reading_order() -> None:
    task = tasks.validate_task(
        task_payload("review_book_split", parameters_for("review_book_split"))
    )
    missing_geometry = result_payload("review_book_split")
    missing_geometry["left_box"] = None
    with pytest.raises(ValidationError, match="requires gutter"):
        tasks.validate_result(task, missing_geometry)

    wrong_order = result_payload("review_book_split") | {"reading_order": "rtl"}
    with pytest.raises(tasks.StructuredTaskError, match="reading_order_mismatch"):
        tasks.validate_result(task, wrong_order)


def provider_adapter(api_style: str, capabilities: list[str] | None = None):
    definition = providers.ProviderDefinition.model_validate(
        {
            "id": f"test-{api_style.replace('_', '-')}",
            "display_name": "测试 Provider",
            "kind": "public_vlm",
            "api_style": api_style,
            "enabled": True,
            "base_url": "https://vision.example/v1",
            "api_key_env": "VISION_API_KEY",
            "model": "vision-1",
            "capabilities": capabilities
            or ["document_understanding", "image_classification", "ocr"],
        }
    )
    return providers.create_adapter(definition, {"VISION_API_KEY": "never-return-this-secret"})


@pytest.mark.parametrize(
    ("api_style", "endpoint_path"),
    [
        ("openai_responses", "/responses"),
        ("openai_chat", "/chat/completions"),
        ("custom", "/tasks"),
    ],
)
def test_provider_plans_are_deterministic_and_not_network_ready(
    api_style: str, endpoint_path: str
) -> None:
    task = tasks.validate_task(task_payload("classify_page"))
    adapter = provider_adapter(api_style)

    plan = tasks.build_provider_request_plan(adapter, task)
    serialized = plan.model_dump_json()
    assert plan.endpoint_path == endpoint_path
    assert plan.network_ready is False
    assert plan.media_placeholder == "$SMARTSCAN_MEDIA"
    assert plan.request_body["temperature"] == 0
    assert "never-return-this-secret" not in serialized
    assert "vision.example" not in serialized
    assert PAGE_ID not in serialized
    assert ASSET_ID not in serialized
    assert "$SMARTSCAN_MEDIA" in serialized
    assert plan.response_schema["properties"]["task_id"]["const"] == TASK_ID
    assert TASK_ID in json.dumps(plan.request_body)


def test_provider_plan_requires_declared_capability() -> None:
    task = tasks.validate_task(task_payload("ocr_formula"))
    adapter = provider_adapter("custom", ["document_understanding"])

    with pytest.raises(tasks.StructuredTaskError, match="capability_missing"):
        tasks.build_provider_request_plan(adapter, task)


def test_result_evidence_requires_ready_capable_provider() -> None:
    task = tasks.validate_task(task_payload("ocr_formula"))
    result, disposition = tasks.validate_result(task, result_payload("ocr_formula"))
    adapter = provider_adapter("custom", ["document_understanding"])

    with pytest.raises(tasks.StructuredTaskError, match="capability_missing"):
        tasks.build_result_evidence(adapter, task, result, disposition)


def test_gateway_endpoints_validate_without_business_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = provider_adapter("openai_responses").definition
    registry = providers.ProviderRegistry(
        [definition], {"VISION_API_KEY": "never-return-this-secret"}
    )
    monkeypatch.setattr(main, "get_registry", lambda: registry)
    task = task_payload("classify_page")

    with TestClient(main.create_app()) as client:
        schemas = client.get("/v1/task-schemas")
        validated_task = client.post("/v1/tasks/validate", json=task)
        plan = client.post(f"/v1/tasks/{definition.id}/plan", json=task)
        validated_result = client.post(
            f"/v1/results/{definition.id}/validate",
            json={
                "task": task,
                "provider_output": json.dumps(result_payload("classify_page")),
            },
        )

    assert schemas.status_code == 200
    assert len(schemas.json()["items"]) == 7
    assert validated_task.json()["note"] == "validation_only_no_network_request"
    assert plan.status_code == 200
    assert plan.json()["network_ready"] is False
    evidence = validated_result.json()["evidence"]
    assert evidence["disposition"] == "candidate"
    assert evidence["business_mutation_allowed"] is False
    assert evidence["model_version"] == "vision-1"
    assert evidence["source_result_version"] == 2
    assert "never-return-this-secret" not in validated_result.text
    assert "vision.example" not in validated_result.text


def test_gateway_returns_stable_errors_for_invalid_or_disabled_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = providers.default_provider_definitions()[1]
    registry = providers.ProviderRegistry([disabled], {})
    monkeypatch.setattr(main, "get_registry", lambda: registry)

    with TestClient(main.create_app()) as client:
        invalid = client.post("/v1/tasks/validate", json={"task_type": "unknown"})
        disabled_plan = client.post(
            f"/v1/tasks/{disabled.id}/plan", json=task_payload("classify_page")
        )
        bad_result = client.post(
            f"/v1/results/{disabled.id}/validate",
            json={"task": task_payload("classify_page")},
        )

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "structured_task_invalid"
    assert disabled_plan.status_code == 409
    assert disabled_plan.json()["detail"] == "provider_disabled"
    assert bad_result.status_code == 422
    assert bad_result.json()["detail"] == "result_validation_envelope_invalid"


def test_openai_plan_embeds_strict_json_schema_not_free_text_format() -> None:
    task = tasks.validate_task(task_payload("extract_page_number"))
    plan = tasks.build_provider_request_plan(provider_adapter("openai_responses"), task)
    response_format = plan.request_body["text"]["format"]

    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["schema"]["additionalProperties"] is False
    assert json.dumps(response_format, sort_keys=True)
