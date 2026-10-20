from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} 必须包含 JSON 对象")
    return payload


def _operations(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, path_item in schema.get("paths", {}).items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    }


def _compare_schema(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    location: str,
    errors: list[str],
) -> None:
    for key in ("type", "format", "$ref", "nullable"):
        if key in baseline and current.get(key) != baseline[key]:
            errors.append(f"{location} 修改了 {key}: {baseline[key]!r} -> {current.get(key)!r}")
    if "enum" in baseline and current.get("enum") != baseline["enum"]:
        errors.append(f"{location} 修改了枚举值")
    baseline_required = set(baseline.get("required", []))
    current_required = set(current.get("required", []))
    removed_required = baseline_required - current_required
    if removed_required:
        errors.append(f"{location} 删除了必填字段声明：{sorted(removed_required)}")
    added_required = current_required - baseline_required
    if added_required:
        errors.append(f"{location} 新增了必填字段：{sorted(added_required)}")
    baseline_properties = baseline.get("properties", {})
    current_properties = current.get("properties", {})
    for name, property_schema in baseline_properties.items():
        if name not in current_properties:
            errors.append(f"{location} 删除了字段 {name}")
            continue
        _compare_schema(
            property_schema,
            current_properties[name],
            location=f"{location}.{name}",
            errors=errors,
        )
    if "items" in baseline:
        if "items" not in current:
            errors.append(f"{location} 删除了数组 items")
        else:
            _compare_schema(
                baseline["items"], current["items"], location=f"{location}[]", errors=errors
            )


def validate_compatibility(
    baseline: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    baseline_operations = _operations(baseline)
    current_operations = _operations(current)
    for key, operation in current_operations.items():
        if not operation.get("operationId"):
            errors.append(f"操作缺少 operationId：{key[0]} {key[1]}")
        if not any(str(status).startswith("2") for status in operation.get("responses", {})):
            errors.append(f"操作缺少成功响应：{key[0]} {key[1]}")
    for key, old_operation in baseline_operations.items():
        if key not in current_operations:
            errors.append(f"删除了受支持操作 {key[0]} {key[1]}")
            continue
        new_operation = current_operations[key]
        old_responses = old_operation.get("responses", {})
        new_responses = new_operation.get("responses", {})
        for status in old_responses:
            if status not in new_responses:
                errors.append(f"{key[0]} {key[1]} 删除了响应状态 {status}")
                continue
            old_content = old_responses[status].get("content", {})
            new_content = new_responses[status].get("content", {})
            for media_type, old_media in old_content.items():
                if media_type not in new_content:
                    errors.append(f"{key[0]} {key[1]} {status} 删除了媒体类型 {media_type}")
                    continue
                _compare_schema(
                    old_media.get("schema", {}),
                    new_content[media_type].get("schema", {}),
                    location=f"{key[0]} {key[1]} {status} {media_type}",
                    errors=errors,
                )
        old_parameters = {
            (item.get("in"), item.get("name")): item for item in old_operation.get("parameters", [])
        }
        new_parameters = {
            (item.get("in"), item.get("name")): item for item in new_operation.get("parameters", [])
        }
        for parameter_key, old_parameter in old_parameters.items():
            if parameter_key not in new_parameters:
                errors.append(f"{key[0]} {key[1]} 删除了参数 {parameter_key}")
                continue
            new_parameter = new_parameters[parameter_key]
            if old_parameter.get("required") != new_parameter.get("required"):
                errors.append(f"{key[0]} {key[1]} 修改了参数必填性 {parameter_key}")
            _compare_schema(
                old_parameter.get("schema", {}),
                new_parameter.get("schema", {}),
                location=f"{key[0]} {key[1]} 参数 {parameter_key}",
                errors=errors,
            )
        for parameter_key, new_parameter in new_parameters.items():
            if parameter_key not in old_parameters and new_parameter.get("required"):
                errors.append(f"{key[0]} {key[1]} 新增了必填参数 {parameter_key}")
        old_body = old_operation.get("requestBody", {})
        new_body = new_operation.get("requestBody", {})
        if not old_body.get("required") and new_body.get("required"):
            errors.append(f"{key[0]} {key[1]} 把请求体改为必填")
        old_ids = old_operation.get("operationId")
        if old_ids != new_operation.get("operationId"):
            errors.append(f"{key[0]} {key[1]} 修改了 operationId")

    baseline_schemas = baseline.get("components", {}).get("schemas", {})
    current_schemas = current.get("components", {}).get("schemas", {})
    for name, old_schema in baseline_schemas.items():
        if name not in current_schemas:
            errors.append(f"删除了受支持模型 {name}")
            continue
        _compare_schema(old_schema, current_schemas[name], location=f"模型 {name}", errors=errors)

    operation_ids = {
        operation.get("operationId") for operation in current_operations.values() if operation
    }
    if policy.get("api_major") != "v1":
        errors.append("兼容策略 api_major 必须为 v1")
    if policy.get("supported_client_generations") != ["current", "previous"]:
        errors.append("必须同时支持 current 和 previous 两代客户端")
    if policy.get("current_contract_revision") == policy.get("previous_contract_revision"):
        errors.append("当前与上一契约修订号不能相同")
    for client, client_policy in policy.get("clients", {}).items():
        for operation_id in client_policy.get("consumed_operation_ids", []):
            if operation_id not in operation_ids:
                errors.append(f"客户端 {client} 引用不存在的 operationId：{operation_id}")

    minimum_days = int(policy.get("minimum_deprecation_days", 90))
    registered = {
        (item.get("method", "").upper(), item.get("path")): item
        for item in policy.get("deprecations", [])
    }
    for key, operation in current_operations.items():
        if not operation.get("deprecated"):
            continue
        entry = registered.get(key)
        if entry is None:
            errors.append(f"已弃用操作未登记：{key[0]} {key[1]}")
            continue
        try:
            announced = date.fromisoformat(entry["announced_on"])
            sunset = date.fromisoformat(entry["sunset_on"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"弃用登记日期无效：{key[0]} {key[1]}")
            continue
        if (sunset - announced).days < minimum_days:
            errors.append(f"弃用窗口不足 {minimum_days} 天：{key[0]} {key[1]}")
        if not entry.get("replacement"):
            errors.append(f"弃用登记缺少替代方案：{key[0]} {key[1]}")
    for key in registered:
        if key not in current_operations or not current_operations[key].get("deprecated"):
            errors.append(f"弃用登记与 OpenAPI 不一致：{key[0]} {key[1]}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="检查当前 OpenAPI 对上一代客户端的兼容性")
    parser.add_argument("--contracts", type=Path, default=Path("packages/contracts"))
    args = parser.parse_args()
    baseline = _load(args.contracts / "openapi-baseline.json")
    current = _load(args.contracts / "openapi.json")
    policy = _load(args.contracts / "compatibility-policy.json")
    errors = validate_compatibility(baseline, current, policy)
    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print("OpenAPI 当前契约兼容上一代客户端基线")


if __name__ == "__main__":
    main()
