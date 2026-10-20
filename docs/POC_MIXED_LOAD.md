# 16 用户混合负载 POC

本文说明 `POC-006` 的负载模型、安全限制、运行方法和正式容量门禁。工具用于隔离的本地或 staging 环境，禁止直接对生产环境运行。

## 固定场景

账号清单顺序固定映射为：

- 前 8 个账号：连续创建 `book` 项目并上传合成书页。
- 中间 4 个账号：浏览本人项目、页面和任务，并在有预置页面时下载本人文件。
- 最后 4 个账号：创建 `document` 项目并上传普通扫描。

共 16 个已登录活跃会话。上传成功后工具轮询本人任务列表，计算从上传开始到任务可见的总时长。CPU 重任务仍应通过队列处理，正式场景不要求 16 个 Worker 同时推理；初始 Worker 并发应按 v1.4 从 2 开始。

浏览角色每 30 秒重新登录，用于观察 CPU 忙碌期间的登录可用性。正式运行前应为至少一个浏览账号预置一页可下载的合成或授权测试数据，否则下载操作数为零，门禁不会通过。

## 安全边界

- 默认只允许 `localhost`、`127.0.0.0/8` 或 `::1` 回环目标。
- 非回环目标必须通过 `--allowed-host` 精确列入，并传入固定确认文本 `I_CONFIRM_STAGING_NOT_PRODUCTION`。
- 目标 URL 不允许包含用户名、密码、查询参数、片段或额外路径。
- 工具不自动注册账号，不使用开发验证码绕过 staging 身份流程。16 个专用账号必须预先创建，并只拥有测试数据。
- 账号 JSON 只保存用户名和密码环境变量名；密码、令牌、响应正文和图片内容不会写入报告。
- 上传内容由工具确定性生成，不读取用户扫描文件。
- `load-tests/accounts.local.json` 与 `reports/load/` 已被 Git 忽略。正式运行后应通过隔离数据库/存储重建清理数据，不能在生产库中逐项手工删除。

允许列表只是防误操作措施，不是生产授权。即使主机被显式允许，操作人员仍必须确认它是可重建的隔离 staging。

## 账号准备

复制示例清单：

```powershell
Copy-Item load-tests/accounts.example.json load-tests/accounts.local.json
$env:SMARTSCAN_LOAD_PASSWORD = "仅用于隔离环境的密码"
```

可以让不同账号引用不同的环境变量。环境变量必须在启动工具的进程中存在，工具会拒绝缺失密码、重复用户名、非 16 个账号或未知清单字段。不要把实际密码写入 JSON、命令行、Git、PR 或报告。

## 服务器资源指标

负载客户端无法从现有业务 API 安全获取服务器 CPU、内存、OOM、磁盘和临时目录指标。正式运行必须由 staging 监控覆盖同一时间窗口，并按 `load-tests/resource-metrics.example.json` 导出：

- 指标来源与观察起止时间。
- CPU 峰值和内存峰值。
- OOM 事件数量。
- 磁盘开始/结束可用空间和临时目录峰值。
- 实际 Worker 并发。

缺少 `--resource-metrics` 时正式门禁必定不通过。示例中的零值只是格式占位，不能作为真实证据。

## 短时本地冒烟

本地 API 准备好 16 个专用账号后，可以缩短运行验证请求流程：

```powershell
python tools/mixed_load.py `
  --accounts load-tests/accounts.local.json `
  --duration-seconds 30 `
  --allow-short-run `
  --output reports/load/smoke
```

少于 `1800` 秒必须显式使用 `--allow-short-run`，报告中的 `acceptance_duration_met` 和 `gate_passed` 保持为 `false`。短时结果只用于调试，不能解除容量门禁。

## staging 正式运行

在可重建的隔离 staging 上运行至少 30 分钟：

```powershell
python tools/mixed_load.py `
  --base-url https://staging.smartscan.example `
  --allowed-host staging.smartscan.example `
  --confirm-non-production I_CONFIRM_STAGING_NOT_PRODUCTION `
  --accounts load-tests/accounts.local.json `
  --resource-metrics load-tests/resource-metrics.local.json `
  --duration-seconds 1800 `
  --upload-interval-seconds 15 `
  --browse-interval-seconds 1 `
  --output reports/load/staging `
  --fail-on-gate
```

服务器监控的时间窗口必须完整覆盖本次运行。BBR 前后对照应使用同一提交、账号、文件、并发、客户端位置和网络条件，分别保存报告；不得只比较两次条件不同的公网测速。

## 报告与门禁

JSON 和中文 Markdown 报告包含：

- 各操作请求数、成功/失败、错误码计数以及 P50/P95/最大时延。
- 非处理请求 P95。
- 已受理页面、已观察任务、缺失任务和最新任务状态。
- 2 秒内任务可见率与跨用户项目返回次数。
- 客户端运行环境、合成图片 SHA-256 和服务器资源指标。

自动门禁同时要求：

- 实际时长不少于 `1800` 秒且虚拟用户恰好为 16。
- 非处理请求 P95 小于 `1000 ms`。
- 所有已受理页面均观察到任务，2 秒内任务可见率为 `100%`。
- 隔离违规、失败任务和请求失败均为零。
- 至少一次页面下载成功。
- 服务器资源指标存在且 OOM 事件为零。

自动门禁无法独立判断 API 进程是否重启、磁盘临时文件是否最终回收、网络中断续传或 BBR 因果关系，这些项目仍需结合服务日志、监控、故障注入和人工验收。

## 当前状态

专项测试使用 `httpx.MockTransport` 完整运行 16 个虚拟用户，验证角色分配、登录、项目隔离、上传、分片、完成、任务可见和报告逻辑。公司目标服务器当前不可用，因此 8 vCPU/16 GB 主机、30 分钟真实网络、CPU 饱和、磁盘回收和 BBR 对照保持“阻塞”；不能用 Mock 或短时本地结果标记为通过。
