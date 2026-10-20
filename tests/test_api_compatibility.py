from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.main import app
from tools.api_compatibility import validate_compatibility

CONTRACTS = Path(__file__).parents[1] / "packages" / "contracts"


def load(name: str) -> dict[str, object]:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_current_openapi_is_compatible_with_previous_client_baseline() -> None:
    assert (
        validate_compatibility(
            load("openapi-baseline.json"),
            load("openapi.json"),
            load("compatibility-policy.json"),
        )
        == []
    )


def test_compatibility_checker_rejects_removal_required_field_and_enum_change() -> None:
    baseline = load("openapi-baseline.json")
    policy = load("compatibility-policy.json")

    removed_operation = deepcopy(baseline)
    del removed_operation["paths"]["/v1/projects"]["get"]
    assert any(
        "删除了受支持操作" in error
        for error in validate_compatibility(baseline, removed_operation, policy)
    )

    required_field = deepcopy(baseline)
    required_field["components"]["schemas"]["ProjectView"]["required"].append("new_required_field")
    assert any(
        "新增了必填字段" in error
        for error in validate_compatibility(baseline, required_field, policy)
    )

    enum_change = deepcopy(baseline)
    enum_change["components"]["schemas"]["UploadStatus"]["enum"].append("new_state")
    assert any(
        "修改了枚举值" in error for error in validate_compatibility(baseline, enum_change, policy)
    )


def test_api_responses_publish_major_and_contract_revision_headers() -> None:
    policy = load("compatibility-policy.json")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-smartscan-api-version"] == policy["api_major"]
    assert response.headers["x-smartscan-contract-revision"] == policy["current_contract_revision"]
