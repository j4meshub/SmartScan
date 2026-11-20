# PaddleOCR v3.7.0 模型说明快照

快照日期：2026-11-20

来源：PaddlePaddle/PaddleOCR `v3.7.0`，固定提交
`b03f46425e8ff4442b268ce449e3eef758146cd4`的通用OCR流水线文档。

| 模型 | 用途 | 官方说明中的推理模型大小 | SmartScan用途 |
|---|---|---:|---|
| `PP-OCRv6_small_det` | PP-OCRv6轻量文字检测 | 9.6 MiB | CPU页面文字区域检测 |
| `PP-OCRv6_small_rec` | PP-OCRv6轻量文字识别 | 20.4 MiB | CPU简体中文、英文及混排识别 |

官方原始下载URL、归档SHA-256、官方模型仓库固定提交和逐文件摘要以同目录
`source-lock.json`为准。本快照用于离线审计，不替代上游原文；上游信息发生变化时必须创建
新的内部模型版本，不能静默更新`PP-OCRv6-small-v1`。
