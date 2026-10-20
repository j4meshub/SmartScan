# 文档透视固定评估集

本目录只保存评估清单示例，不提交图片本体、用户扫描数据或包含个人信息的标注。

## 准备规则

1. 复制 `manifest.example.json` 为本地 `manifest.json`。
2. 将已授权且脱敏的图片放入 `datasets/perspective/images/`；该目录已被 Git 忽略。
3. 每个样本记录 SHA-256、类别和人工标注。正样本四角顺序固定为左上、右上、右下、左下，并以图片宽高归一化到 `0–1`。
4. 授权区必须记录许可证或内部使用范围、非个人化审批编号、用途，并明确 `approved=true`、`deidentified=true`。
5. 不得使用生产用户目录、未授权聊天附件、截图中的完整手机号/证件号或无法证明来源的网络图片。

清单契约见 `packages/contracts/perspective-evaluation-manifest.schema.json`。脚本还会校验路径不能越出数据集目录、文件格式、SHA-256、像素上限和正负样本标注。

## 运行

```bash
python tools/evaluate_perspective.py datasets/perspective/manifest.json \
  --output reports/perspective \
  --minimum-usable-rate 0.95 \
  --minimum-positive-samples 100 \
  --corner-error-threshold 0.03 \
  --save-previews \
  --fail-below-target
```

输出包含不带原始路径的 JSON 与中文 Markdown 报告，记录检测召回、负样本误检、透视可用率、归一化角点误差、P50/P95/最大耗时和进程峰值 RSS。`--save-previews` 会在被 Git 忽略的报告目录生成校正预览，只用于授权人员人工复核，不得复制到仓库或公开附件。

示例清单中的 SHA-256 是占位值，不能作为通过证据。真实运行默认至少要求 100 个正样本，且透视可用率达到 `≥95%` 才会打开风险闸门；只有固定授权数据集的实际报告才可解除 `POC-003` 门禁。
