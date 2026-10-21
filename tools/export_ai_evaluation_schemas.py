"""导出或检查 AI 固定评估输入 JSON Schema。"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_GATEWAY_ROOT = PROJECT_ROOT / "services" / "ai-gateway"
CONTRACT_PATH = PROJECT_ROOT / "packages" / "contracts" / "ai-evaluation-v1.json"


def render() -> str:
    sys.path.insert(0, str(AI_GATEWAY_ROOT))
    module = importlib.import_module("app.evaluation")
    return json.dumps(module.schema_bundle(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出或检查 AI 固定评估输入 Schema")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.write:
        CONTRACT_PATH.write_text(expected, encoding="utf-8", newline="\n")
        print(f"已写入 {CONTRACT_PATH.relative_to(PROJECT_ROOT)}")
        return 0
    if not CONTRACT_PATH.is_file() or CONTRACT_PATH.read_text(encoding="utf-8") != expected:
        print("AI 固定评估 Schema 快照不存在或已过期", file=sys.stderr)
        return 1
    print("AI 固定评估 Schema 快照校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
