# 页面版本、质量与复核

## 数据边界

`scan_pages` 保存页面身份和不可变原图引用，`page_results` 保存追加式处理结果。原图位于用户隔离目录的 `originals` 下；Worker 和页面编辑只允许在 `results/<项目>/<页面>/vNNNN.jpg` 创建新文件，不能覆盖原图或既有结果版本。

页面保留 `processed_path` 和 `mime_type` 作为旧客户端的活动结果兼容指针。新客户端使用 `active_result_version` 和 `active_result`；历史版本通过 `GET /v1/pages/{id}/results` 查询。`original_mime_type` 独立保存原图类型，避免基础处理转成 JPEG 后丢失来源信息。

## 质量与复核

基础 Worker 保存 0 至 100 的 `quality_score`、结构化 `quality_details`、首个兼容警告 `quality_warning` 和可读复核原因。当前结构化指标包含尺寸、像素数、亮度、对比范围、文档边缘判断与全部警告；后续清晰度、曝光、高光、遮挡和 OCR 指标可增量加入，不改变现有字段。

作业状态只表示处理生命周期。基础结果生成成功后作业为 `completed`；低质量页面把独立 `review_status` 设为 `pending`，不会把可用结果误记成失败。所有者可通过 `PATCH /v1/pages/{id}/review` 确认或重新打开复核，确认人和时间单独记录。

## 旋转与内容读取

`POST /v1/pages/{id}/rotations` 只允许页面所有者调用，并接受 `90`、`180` 或 `270` 度顺时针旋转。接口在当前活动结果之上创建新的不可变 JPEG 版本，更新累计旋转角度和活动版本；存在排队或运行中的页面任务时拒绝旋转，避免与 Worker 竞态覆盖。

`GET /v1/pages/{id}/content` 默认返回活动结果，没有结果时回退原图。`variant=original` 始终返回原图，`version=N` 返回指定历史结果。管理员可以按既有角色矩阵跨用户读取并产生审计，但不能替用户旋转或确认复核；其他普通用户与不存在页面统一返回 `404`。旋转、复核及被拒绝的跨用户修改均写入审计。

## 迁移与回滚

`20261020_0013` 回填原图类型、页面更新时间和复核状态，并把已有 `processed_path` 登记为 `legacy-baseline` 版本。旧 `needs_review` 作业迁移为 `completed`，对应页面变为 `pending`，表达“基础结果可用但需要复核”。

降级到 `0012` 时，待复核页面对应的已完成作业恢复为旧 `needs_review`，随后删除结果版本表和新增页面元数据；磁盘上的版本文件不会由数据库降级自动删除。生产降级前必须备份页面元数据并确认旧应用可以接受回退语义。
