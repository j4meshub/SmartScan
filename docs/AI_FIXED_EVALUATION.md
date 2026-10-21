# 可选视觉 AI 固定评估

## 目的与边界

AI-005 用同一份已授权固定数据集比较基础 OCR、专业 OCR、公共 VLM 和自定义 VLM，报告准确率、幻觉率、结构化成功率、P50/P95 延迟、成本和精确版本。评估器只读取本地清单与已捕获运行结果，默认不联网，也不会启用任何 Provider。

评估器可以为单个候选生成局部报告，但只有四类系统都出现时比较才完整；缺少任一类型时总门禁固定为未通过。

仓库中的合成测试只验证评估逻辑。真实 Provider、真实价格、数据处理政策和授权样本没有提供前，AI-005 保持“等待人工验收”；示例数据或 Mock 结果不能让门禁转绿。

## 输入契约

输入契约快照位于 `packages/contracts/ai-evaluation-v1.json`，由以下两部分组成：

- 固定数据集清单：数据集版本、授权与脱敏依据、按来源分组的切分策略、经批准阈值、外部 AI 全关闭时的核心流程证据，以及图片摘要、完整结构化任务和人工期望标注。
- 运行结果：数据集摘要、系统类型、实际 API/本地基线模式、模型/框架/提示词/适配器/量化精确版本、配置摘要、价格及数据政策依据，以及每个 test 样本的状态、耗时、成本和本地原始结构化输出。

评估器拒绝路径越界、图片摘要或尺寸不符、任务媒体不一致、来源组跨切分、重复样本、test 覆盖缺失、数据集摘要错配，以及 `latest`、`unknown` 等不可复现版本。运行文件可能包含扫描文本，只能保存在被忽略的 `datasets/ai-evaluation/runs/`，不得提交。

## 指标口径

- 准确率：分类和方向为精确匹配；标题使用 NFKC、大小写和空白归一化；页码比较状态、数值和样式；公式/表格/版面按人工声明集合计算 F1；净化比较每个区域的类型和动作；双页比较决策、阅读顺序、书脊容差和左右框 IoU。
- 幻觉率：模型给出的、但不在人工允许声明中的条目数除以总预测声明数。结构化校验失败不产生可采信声明，并单独降低结构化成功率。
- 延迟：完整 test 集观察的 P50 和 P95；失败和超时也计入，避免只报告成功请求。
- 成本：每页实际捕获的整数微美元，报告平均值和总值；配置上限不能代替供应商账单或价格依据。
- 门禁：清单内阈值必须有批准人和记录。v1.4 未给出一组通用 AI 准确率/幻觉率数字，因此仓库不硬编码产品阈值。

低置信或错误结果仍只作为增强候选证据，不能覆盖 CPU 基础结果、修改原图或虚构原文。所有外部 AI 关闭时，上传、处理、预览和导出的核心完成率仍必须为 100%。

## 执行流程

1. 复制 `datasets/ai-evaluation/manifest.example.json`，将真实图片放入 `images/`，替换全部占位字段并完成人工复核。
2. 用获准的内部采集流程分别执行基础 OCR、专业 OCR、公共 VLM 和自定义 VLM。采集器必须使用实际 API，而不是网页演示，并把每个系统保存为一个本地 run JSON。
3. 对每个候选系统执行同一命令；多个 `--run` 会生成横向报告：

```powershell
python tools/evaluate_ai_providers.py datasets/ai-evaluation/manifest.json `
  --run datasets/ai-evaluation/runs/baseline.json `
  --run datasets/ai-evaluation/runs/professional-ocr.json `
  --run datasets/ai-evaluation/runs/public-vlm.json `
  --run datasets/ai-evaluation/runs/custom-vlm.json `
  --output reports/ai-evaluation `
  --fail-below-target
```

4. 复核 `ai-evaluation-report.json` 和中文 Markdown 报告，并将运行 ID、数据集摘要、供应商版本、价格/政策依据及批准记录写入验收证据。报告刻意不包含图片、原始路径、原始输出、任务/页面 ID、媒体 URL、令牌或密钥。

Schema 变更后执行：

```powershell
python tools/export_ai_evaluation_schemas.py --write
python tools/export_ai_evaluation_schemas.py --check
```

## 人工验收清单

- 数据规模、语言与场景覆盖满足 v1.4，并按文档、试卷或书籍来源分组切分。
- 所有图片已授权、脱敏，且许可和同意记录可追溯。
- 四类系统使用同一数据集摘要；模型、框架、量化、提示词和适配器版本固定。
- 实际 API 的准确率、幻觉率、结构化成功率、P95 延迟和成本达到已批准阈值。
- 供应商账单与本地成本记录完成抽样对账，数据政策和保存期限完成复核。
- 外部 AI 全部关闭或故障时，核心扫描流程完整通过。
