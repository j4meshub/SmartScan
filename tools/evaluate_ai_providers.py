"""离线比较可选视觉 AI 与基线系统的固定数据集结果。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_GATEWAY_ROOT = PROJECT_ROOT / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

from app.evaluation import evaluate_runs


def _percent(value: float) -> str:
    return f"{value:.2%}"


def markdown_report(report: dict[str, Any]) -> str:
    rows = [
        "# 可选视觉 AI 固定评估报告",
        "",
        f"- 数据集：`{report['dataset']['id']}` / `{report['dataset']['version']}`",
        f"- 数据集 SHA-256：`{report['dataset']['sha256']}`",
        f"- 评估器版本：`{report['evaluator_version']}`",
        f"- test 样本：{report['dataset']['test_samples']}",
        f"- 评估时间：`{report['evaluated_at']}`",
        f"- 四类系统覆盖：{'完整' if report['comparison_complete'] else '不完整'}",
        f"- 总门禁：{'通过' if report['all_systems_passed'] else '未通过'}",
        "",
        "| 系统 | 类型 | 准确率 | 幻觉率 | 结构化成功率 | P50 / P95 ms | 平均成本 μUSD | 门禁 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["systems"]:
        metrics = item["overall"]
        rows.append(
            f"| {item['system']['system_id']} | {item['system']['kind']} | "
            f"{_percent(metrics['accuracy'])} | {_percent(metrics['hallucination_rate'])} | "
            f"{_percent(metrics['structured_success_rate'])} | "
            f"{metrics['latency_ms_p50']:.3f} / {metrics['latency_ms_p95']:.3f} | "
            f"{metrics['average_cost_microusd']:.3f} | "
            f"{'通过' if item['gate']['passed'] else '未通过'} |"
        )
    if report["missing_system_kinds"]:
        rows.extend(
            ["", f"缺少系统类型：`{', '.join(report['missing_system_kinds'])}`，总门禁保持关闭。"]
        )
    rows.extend(["", report["notice"], "真实门禁结论只接受已授权数据集和实际 API 运行结果。", ""])
    return "\n".join(rows)


def write_reports(report: dict[str, Any], output: Path) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "ai-evaluation-report.json"
    markdown_path = output / "ai-evaluation-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="离线评估 SmartScan 可选视觉 AI")
    parser.add_argument("manifest", type=Path, help="已授权固定数据集清单")
    parser.add_argument(
        "--run", type=Path, action="append", required=True, help="实际运行结果，可重复"
    )
    parser.add_argument("--output", type=Path, default=Path("reports/ai-evaluation"))
    parser.add_argument("--fail-below-target", action="store_true")
    args = parser.parse_args()
    report = evaluate_runs(args.manifest, args.run)
    json_path, markdown_path = write_reports(report, args.output)
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{markdown_path}")
    print(f"总门禁：{'通过' if report['all_systems_passed'] else '未通过'}")
    return 2 if args.fail_below_target and not report["all_systems_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
