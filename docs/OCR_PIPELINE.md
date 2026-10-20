# 基础 OCR、方向融合与安全命名

## 能力边界

`OCR-001` 是运行在 CPU Worker 内的本地能力，不属于外部视觉 AI。生产环境即使关闭全部外部 AI Provider，也必须启用本地 OCR；若 OCR 运行库、模型目录、版本或文件校验不一致，Worker 在领取任务前失败，禁止在首次用户请求时联网下载模型。

当前固定运行库为 `paddleocr==3.7.0` 和 `paddlepaddle==3.3.1`，使用 `PP-OCRv6_small_det` 与 `PP-OCRv6_small_rec` 离线模型包，内部模型包版本为 `PP-OCRv6-small-v1`。PaddleOCR 官方文档说明了 CPU 设备、Python `predict()` 接口、本地模型目录以及识别结果中的文字、置信度和矩形框字段：

- [PaddleOCR 通用 OCR Python 集成](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)
- [PaddleOCR 安装说明](https://www.paddleocr.ai/main/en/version3.x/installation.html)

仓库不提交模型权重。模型是发布资产，必须在受控构建或 staging 准备，并挂载为只读目录。

## 离线模型包

模型根目录至少包含检测、识别目录和 `manifest.json`：

```text
models/ocr/
├── PP-OCRv6_small_det/
├── PP-OCRv6_small_rec/
└── manifest.json
```

从官方来源取得模型并完成许可证、安全和来源复核后，生成固定清单：

```bash
python tools/build_ocr_manifest.py models/ocr \
  --detection-dir PP-OCRv6_small_det \
  --recognition-dir PP-OCRv6_small_rec \
  --model-version PP-OCRv6-small-v1
```

清单记录 PaddleOCR、PaddlePaddle、模型包版本和模型目录内每个文件的 SHA-256。Worker 初始化时逐项校验，拒绝绝对路径、目录逃逸、缺失文件、版本偏差和哈希偏差。更新模型时必须使用新的 `SMARTSCAN_OCR_MODEL_VERSION`，重新生成清单并通过固定数据集，不可静默替换同版本内容。

本地需要真实 OCR 时安装：

```bash
pip install -e ".[dev,vision,ocr]"
```

仅运行不涉及 OCR 的开发测试时可设置 `SMARTSCAN_OCR_ENABLED=false`；生产配置会拒绝关闭。Compose 把 `models/ocr` 只读挂载到 Worker 的 `/opt/smartscan/models/ocr`，API 和迁移服务不读取模型文件。

## 四方向融合

Worker 在透视校正和基础增强后，分别对 0°、90°、180°、270° 图像执行 OCR。每个方向综合：

- 按文字长度加权的平均识别置信度；
- 横排行框比例；
- 有效文字量的有限加分。

非 0° 结果必须比 0° 至少高出 `SMARTSCAN_OCR_ORIENTATION_MARGIN` 才会自动旋转，避免相近分数造成抖动。每次方向推理后续租；租约丢失、用户取消或其他 Worker 抢占时立即停止，旧 Worker 不能提交 OCR 或页面结果。自动旋转只写新的处理图，原图不变；用户后续手动旋转会产生新页面版本，并把旧 OCR 标记为 `stale`，避免文字框与图像错位。

## 结果与兼容性

OCR 结果保存在 `scan_pages`，并由 `ocr_result_version` 绑定当时的 `active_result_version`：

- `ocr_text`：兼容全文；
- `ocr_details`：版本化 JSON，保存四方向评分以及最终方向的文字、置信度和矩形框；
- `ocr_model_version`、`ocr_confidence`、`ocr_rotation_degrees`：模型和方向证据；
- `ocr_title_candidate`：已经过安全过滤的标题候选；
- `ocr_status`：`pending`、`ready`、`disabled`、`stale` 或迁移数据的 `legacy`。

适配器会拒绝非有限置信度和无效/越界矩形框，单页最多接收 2,000 行、每行最多 512 个字符，避免异常模型输出无界占用数据库和内存。

API 仅在 OCR 结果版本与活动页面版本一致时返回全文、模型、置信度、方向、行框和标题候选。页面接口继续复用项目/页面 RBAC：普通用户只能读取本人 OCR，管理员跨用户读取会审计，无权和不存在统一返回 `404`。OCR 字段随页面参与现有账号合并和删除，不形成独立孤儿资源。

## 安全命名

标题候选只从图像顶部 40% 内、达到标题置信阈值的文字行选择。候选会：

- 拒绝手机号、18 位证件号、纯页码和 `Page N`；
- 清理 Windows、POSIX 和全角非法文件名字符；
- 移除已有 `.pdf`、`.jpg`、`.jpeg` 后缀，拒绝 Windows 保留设备名；
- 截断到 80 个字符，不翻译扫描内容。

建议名称单独写入项目的 `suggested_name`，不覆盖用户输入的 `title`。没有可信标题时，中文用户使用 `智能扫描_YYYYMMDD`，英文用户使用 `SmartScan_YYYYMMDD`。后续导出工作包可以采用该建议名称，仍需在最终扩展名和冲突处理后再次校验。

## 验收边界

自动化测试使用可重复的假引擎验证四方向融合、阈值、敏感标题过滤、Worker 租约、结果版本、API 权限、迁移和回滚；它不能替代真实模型质量。以下项目仍须使用已授权固定数据集或 staging 人工验收：

- 中英文、四方向、阴影、低光和弯曲文档；
- v1.4 的文字方向正确率 `≥98%`；
- 真实 CPU 耗时、峰值内存和双 Worker 容量；
- 模型包来源、许可证、哈希发布和离线重建。
