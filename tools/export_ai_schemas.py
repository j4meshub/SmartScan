from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_GATEWAY_ROOT = PROJECT_ROOT / "services" / "ai-gateway"
CONTRACT_PATH = PROJECT_ROOT / "packages" / "contracts" / "ai-tasks-v1.json"


def load_tasks_module():
    sys.path.insert(0, str(AI_GATEWAY_ROOT))
    return importlib.import_module("app.tasks")


def schema_bundle() -> dict[str, Any]:
    tasks = load_tasks_module()
    items = []
    for item in tasks.task_schema_catalog():
        items.append(
            {
                **item,
                "task_type": item["task_type"].value,
            }
        )
    return {
        "contract": "SmartScan 可选视觉 AI 结构化任务",
        "schema_version": tasks.SCHEMA_VERSION,
        "tasks": items,
    }


def render_schema_bundle() -> str:
    return json.dumps(schema_bundle(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出或校验 AI 结构化任务 JSON Schema 快照")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="写入当前 Schema 快照")
    mode.add_argument("--check", action="store_true", help="检查快照是否与当前代码一致")
    args = parser.parse_args()
    expected = render_schema_bundle()
    if args.write:
        CONTRACT_PATH.write_text(expected, encoding="utf-8", newline="\n")
        print(f"已写入 {CONTRACT_PATH.relative_to(PROJECT_ROOT)}")
        return 0
    if not CONTRACT_PATH.is_file():
        print("AI Schema 快照不存在，请先执行 --write", file=sys.stderr)
        return 1
    actual = CONTRACT_PATH.read_text(encoding="utf-8")
    if actual != expected:
        print("AI Schema 快照已过期，请确认兼容性后执行 --write", file=sys.stderr)
        return 1
    print("AI 结构化任务 Schema 快照校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
