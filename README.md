# SmartScan / 智能扫描

SmartScan 是一套注重隐私的文档扫描平台，为企业微信 H5、Android、iOS 和浏览器管理后台提供统一的账号与数据层。系统设计保证在关闭全部外部 AI 的情况下，基础处理链路仍可运行。

本仓库是依据 v1.4 实施方案建立的首个可执行基线，并非已经具备 App Store 上架或生产验收条件的最终版本。当前完成范围和剩余工作详见[实施状态](docs/IMPLEMENTATION_STATUS.md)。

长期开发采用可断点续接的工作包机制。完整路线见[长期执行计划](docs/CODEX_EXECUTION_PLAN.md)，当前断点和验证证据见[长任务进度](docs/CODEX_PROGRESS.md)，跨阶段技术选择见[实施决策记录](docs/DECISIONS.md)。

## 当前包含内容

- FastAPI API：已拆分稳定用户主体、本地登录身份和已验证手机号，并提供 Argon2id 密码哈希、手机号确定性 HMAC、随机会话令牌和会话撤销。
- 手机号保护：新验证号码使用绑定用户的 AES-256-GCM 认证密文和版本化 HMAC；旧账号明确等待下一次可信验证补齐，轮换工具默认干跑。
- 短信挑战：提供 5 分钟一次性挑战、5 次尝试上限、手机号/IP 并发安全限频及 development Mock；真实供应商仍待验收。
- 企业微信登录：提供一次性 OAuth state、可信手机号唯一绑定、无手机号短信回退和冲突拒绝；真实租户仍待人工验收。
- 账号合并：同一已验证手机号的两个无冲突普通账号可事务合并，资源与文件迁移可补偿，双方旧会话全部撤销。
- 设备会话：新客户端使用短期访问令牌和单次轮换刷新令牌，可查看、单独撤销或全部撤销设备；旧客户端保留兼容时长。
- 账号删除：短信强验证后进入 7 天冷静期，立即撤销会话；Worker 可重入清理身份、扫描数据和文件，并执行 30 天手机号复用隔离。
- 企业微信可信身份 POC：默认关闭的真实适配器、开发 Mock、可信手机号契约和安全账号决策；真实租户仍待人工验收。
- H5 拍摄与弱网：实时后置相机、`ImageCapture`/视频帧双回退、系统相机兜底、页面后台释放、待上传预览，以及不重传已确认分片的自动恢复测试。
- H5 统一登录：稳定设备会话、刷新令牌单次轮换与并发合并、企业微信 OAuth 回调、缺手机号短信绑定和安全退出。
- H5 页面编辑：鉴权预览、四角透视裁切、旋转、增强/灰度/黑白滤镜、页序调整和低质量复核；永久删除保留独立安全门禁。
- H5 文件工作区：项目 URL 断点恢复、项目任务自动轮询、PDF/JPG 导出、鉴权下载，以及 Web Share 不可用时的本地下载回退。
- H5 质量门禁：中英文词条键一致性、可本地化的无障碍名称、键盘四角调整，以及登录/恢复/导出/分享回退的 Chromium E2E。
- iOS 身份与网络：短信注册、本地登录、Keychain 设备会话、一次性刷新令牌、用户缓存分区和中英文身份界面；默认 API 域名不可解析。
- iOS 拍摄与 Vision：AVFoundation 后摄、点按对焦、曝光补偿、矩形/质量提示、手动快门，以及按用户保存的不可变原图和方向证据。
- iOS 离线与后台恢复：用户分区持久队列、服务端确认分片续传、一次刷新重试、幂等完成和系统允许范围内的 BGProcessing 恢复。
- iOS 工作区与账户：页序/四角/旋转/滤镜/复核、JPG/PDF 导出、SHA-256 校验、PDFKit 预览、系统分享及短信强验证账号删除。
- iOS 审核准备：双语商店元数据、隐私清单、截图/审核账号清单、应用内隐私与支持入口，以及不读取密钥值的两级发布校验。
- 文档透视评估框架：授权固定数据集清单、角点误差与可用率指标、耗时/内存报告及最少样本门禁；真实样本仍待人工验收。
- 基础试卷净化 POC：版式规则三级建议、保守彩色笔迹候选、印刷内容保护、复核掩膜和整页原图回退；黑色笔迹不会在无可靠模型时自动擦除。
- 双页拆分 POC：非中心书脊估计、左右独立裁切、显式阅读顺序、缺侧单页回退，以及仅在几何改善时采用的保守边界去弯曲。
- 书籍完整性与成册：版本化页码/内容指纹、缺页和重复/冲突报告、人工决策、补扫，以及可追溯的增量 PDF 修订；无页码页面不虚构印刷页码。
- 16 会话混合负载工具：固定 8 个书页上传、4 个浏览/下载、4 个普通扫描角色，输出任务、隔离、时延和资源指标报告，并默认拒绝非回环目标。
- 服务端 RBAC：实现 `user`、`admin`、唯一 `super_admin` 的数据可见范围。
- 完整管理审计：分层用户管理、会话撤销、受控账号删除、分页过滤，以及成功/失败操作的不可变审计。
- 页面版本与复核：原图不可覆盖，基础处理与手动旋转按版本追加，结构化记录质量、旋转角度和独立复核状态。
- 可恢复任务状态机：随机租约令牌、心跳续租、过期抢占、指数退避、最终失败、所有者取消与显式重试。
- 基础 OCR 与安全命名：固定版本的本地 CPU 适配器、四方向置信融合、版本关联行框，以及过滤手机号/证件号/页码的中英文建议名称。
- JPG/PDF 导出：单页/多页制品、清晰/均衡/小文件三档、版本快照和仅采用当前 OCR 行框的可选文本层。
- 文件生命周期：导出鉴权下载与 Range、Nginx 内部发送、幂等上传取消、过期分片回收和可重试项目清理。
- API 契约冻结：当前与上一代双快照、客户端实际消费矩阵、破坏性变更检查和至少 90 天弃用登记。
- 只增不改的审计事件：覆盖登录和管理员跨用户访问。
- 按所有者隔离的扫描项目、安全图片路径、SHA-256 元数据，以及由 PostgreSQL 支持的租约任务队列。
- 分片上传、断点续传、分片/整文件哈希校验、幂等完成和跨用户隔离。
- CPU Worker：保留原图，并在不依赖外部 AI 的情况下完成 EXIF 方向修正、文档边缘检测、透视校正、对比度增强和锐化；边缘检测失败时保留完整画面并进入人工复核。
- 无需前端构建工具即可运行的双语响应式 H5 与管理后台。
- Kotlin/Compose Android 和 SwiftUI iOS 工程起点。
- Docker Compose、Nginx、PostgreSQL 加固 SQL、GitHub Actions 和 GitLab CI。

## 本地运行

环境要求：Python 3.11 或更高版本。

```bash
python -m venv .venv
# Windows：.venv\Scripts\activate
# macOS/Linux：source .venv/bin/activate
pip install -e ".[dev,vision]"       # 不运行真实 OCR 的普通开发
# pip install -e ".[dev,vision,ocr]" # 需要离线 OCR 模型包时
copy .env.example .env   # macOS/Linux 使用 cp
python -m services.api.app.migrations upgrade
uvicorn services.api.app.main:app --reload
```

另外打开两个终端：

```bash
python -m services.worker.app.main
python -m http.server 8080 --directory apps/h5
python -m http.server 8081 --directory apps/admin-web
```

访问地址：

- H5：`http://localhost:8080`
- 管理后台：`http://localhost:8081`
- API 文档：`http://localhost:8000/docs`

开发环境注册使用 `SMARTSCAN_DEV_SMS_CODE`，非开发环境会拒绝该验证码。首次启动 API 前应设置 `SMARTSCAN_SUPERADMIN_PASSWORD`，以初始化受保护的超级管理员。生产环境还必须注入手机号 HMAC 与 AES-256-GCM Keyring；缺失、弱值或无效编码会拒绝启动，仓库中不会硬编码实际密钥。

企业微信 POC 默认使用 `SMARTSCAN_WECOM_MODE=disabled`。本地契约说明、运行模式与真实租户验收项见[企业微信可信身份 POC](docs/POC_WECOM_IDENTITY.md)。

统一用户、登录身份、已验证手机号的职责、兼容期双写和回滚边界见[统一身份模型说明](docs/UNIFIED_IDENTITY_MODEL.md)。

手机号密文格式、生产 Secret 配置、旧数据补验证和分批轮换步骤见[手机号数据保护与密钥轮换](docs/PHONE_DATA_PROTECTION.md)。

验证码申请、消费、限频和 Provider 边界见[短信验证码挑战与限频](docs/SMS_VERIFICATION.md)。

企业微信授权、回调、绑定票据和真实租户门禁见[企业微信 OAuth 登录与安全绑定](docs/WECOM_OAUTH_BINDING.md)。

历史双账号的强身份校验、冲突矩阵、文件补偿和不可变审计见[账号合并与冲突处理](docs/ACCOUNT_MERGE.md)。

访问/刷新令牌时长、设备头、重放防护、撤销和旧客户端兼容见[设备会话与刷新令牌](docs/DEVICE_SESSIONS.md)。

账号删除申请、撤销、Worker 清理、失败重试和手机号隔离见[账号删除、冷静期与手机号复用隔离](docs/ACCOUNT_DELETION.md)。

管理角色边界、用户与删除操作、分页过滤和失败审计见[管理接口、权限矩阵与审计](docs/ADMINISTRATION_AND_AUDIT.md)。

页面原图、处理结果版本、质量指标、旋转、内容读取和独立复核状态见[页面版本、质量与复核](docs/PAGE_VERSIONS_AND_REVIEW.md)。

作业阶段、租约令牌、心跳、崩溃恢复、重试退避和取消边界见[作业状态机、租约与恢复](docs/JOB_STATE_MACHINE.md)。

固定 CPU 运行库、离线模型清单、四方向融合、OCR 结果字段和安全命名见[基础 OCR、方向融合与安全命名](docs/OCR_PIPELINE.md)。

导出制品模型、三档质量、OCR 文本真实性、文件隔离和回滚边界见[JPG/PDF 导出与 OCR 文本层](docs/EXPORT_PIPELINE.md)。

制品下载、Range/X-Accel、上传取消、临时目录回收和项目删除见[文件下载、上传取消与项目清理](docs/FILE_LIFECYCLE.md)。

当前/上一客户端兼容范围、双快照检查和弃用规则见[v1 API 契约冻结与客户端兼容](docs/API_COMPATIBILITY.md)。

Android 模块边界、Compose 导航、环境注入、请求安全和 CI 工具链见[Android 分层工程与 API 客户端](docs/ANDROID_ARCHITECTURE.md)。

Android 注册登录、一次性刷新令牌、Keystore 加密会话、Room 用户分区和退出清理见[Android 身份、Keystore 与用户分区缓存](docs/ANDROID_AUTH_AND_CACHE.md)。

Android 三模式 CameraX 预览、点按对焦、曝光补偿、质量提示、手动快门和原图保护见[Android CameraX 拍摄与质量提示](docs/ANDROID_CAMERA_CAPTURE.md)。

Android Room 离线队列、WorkManager 网络恢复、服务端确认分片续传和会话隔离见[Android 离线队列与分片续传](docs/ANDROID_OFFLINE_UPLOAD.md)。

Android 页面编辑、导出鉴权下载、受限 FileProvider 分享和账号删除本地清理见[Android 编辑、导出、分享与账号删除](docs/ANDROID_EDIT_EXPORT_SHARE.md)。

Android 签名更新清单、APK 哈希/包名/版本/证书校验和系统安装确认见[Android 安全更新](docs/ANDROID_SECURE_UPDATE.md)。

iOS 固定 XcodeGen 版本、生成工程规范、Simulator 测试和 macOS CI 边界见[iOS 可复现工程与 CI 基线](docs/IOS_ARCHITECTURE.md)。

iOS 注册登录、Keychain 会话、受控 API 地址、刷新恢复和用户缓存分区见[iOS 身份、Keychain 与网络](docs/IOS_AUTH_AND_NETWORK.md)。

iOS 后摄预览、Vision 矩形、质量提示、原图和方向证据见[iOS AVFoundation 拍摄与 Vision 提示](docs/IOS_CAMERA_CAPTURE.md)。

iOS 用户队列、后台调度、服务端确认分片和幂等完成见[iOS 本地队列、后台恢复与分片续传](docs/IOS_BACKGROUND_UPLOAD.md)。

iOS 页面编辑、导出校验、PDFKit/Share Sheet 和账号删除见[iOS 工作区、导出分享与账号删除](docs/IOS_WORKSPACE_AND_ACCOUNT.md)。

iOS TestFlight、App Store 元数据、签名边界和人工发布顺序见[iOS TestFlight 与 App Store 准备说明](docs/IOS_APP_STORE_READINESS.md)；数据披露草稿、截图和审核账号分别见[iOS App 隐私披露草稿](docs/IOS_APP_PRIVACY_DRAFT.md)、[iOS App Store 截图清单](docs/IOS_SCREENSHOT_CHECKLIST.md)和[iOS 审核账号操作规程](docs/IOS_REVIEW_ACCOUNT.md)。

试卷页面规则/轻量模型分类、置信区间、结果版本、三端建议取消和固定数据集门禁见[试卷页面分类、建议与取消](docs/EXAM_CLASSIFICATION.md)。

扫书模式的翻页、稳定、清晰度、曝光、边界、书脊、遮挡状态机以及原生端与 H5 的能力边界见[扫书条件自动快门](docs/BOOK_AUTO_CAPTURE.md)。

物理展开页、左右逻辑页、显式阅读顺序、去弯曲证据和单侧替换血缘见[书籍双页逻辑页与单侧重拍](docs/BOOK_SPREAD_AND_RETAKE.md)。

印刷页码证据、缺页/重复页判断、人工决策、补扫和版本化 PDF 成册见[书籍页码、完整性与增量成册](docs/BOOK_PAGE_INTEGRITY.md)。

文档透视真实样本的准备、指标口径和验收边界见[文档透视真实样本评估](docs/POC_PERSPECTIVE_EVALUATION.md)。仓库中的合成测试只验证评估器，不能证明真实可用率达到 `95%`。

试卷规则检测、保守净化和禁止生成虚假原文的边界见[基础试卷检测与保守净化 POC](docs/POC_EXAM_CLEANUP.md)。

展开书籍的拆分、阅读顺序和去弯曲回退说明见[双页拆分与保守去弯曲 POC](docs/POC_BOOK_SPLIT.md)。

隔离环境的账号准备、短时冒烟、30 分钟正式场景和报告门禁见[16 用户混合负载 POC](docs/POC_MIXED_LOAD.md)。

## 容器运行

将 `.env.example` 复制为 `.env`，替换所有密钥后执行：

```bash
docker compose -f deploy/compose/docker-compose.yml up --build
```

Compose 会先运行一次性 `migrate` 服务，迁移成功后才启动 API 和 Worker。生产 Worker 还要求在 `models/ocr` 放置通过清单校验的离线模型包；缺失或被篡改时拒绝领取任务。数据库版本管理、旧基线接管和回滚要求详见[数据库迁移说明](docs/DATABASE_MIGRATIONS.md)。正式上线前仍需配置 TLS、加密备份和生产密钥管理。

## 测试

完整测试隔离、OpenAPI 快照和覆盖率门禁说明见[测试与 CI 基线](docs/TESTING.md)。

```bash
ruff check services migrations tests tools
ruff format --check services migrations tests tools
pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python tools/validate_ios_release.py
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
```

## 安全基线

当前资源的普通用户、管理员和超级管理员权限测试见[资源权限与 IDOR 测试矩阵](docs/SECURITY_TEST_MATRIX.md)。

- 不得提交 `.env`、短信/企业微信/AI 密钥、签名材料或用户扫描文件。
- 数据路径使用服务端生成的 ID，且不由 Nginx 直接公开。
- 未授权和不存在的对象 ID 均返回 `404`。
- 唯一超级管理员同时受 API 逻辑和 PostgreSQL 防护约束保护。
- 可选 AI 地址必须通过 HTTPS 和公网 IP 的 SSRF 检查；基础扫描链路不依赖外部 AI。
- 分片仅写入当前用户的临时目录，完成前校验分片大小、分片哈希、整文件哈希和图片文件签名。
- 文档透视校正只在边缘检测达到面积阈值时执行；检测失败不会裁切原图，而是生成基础增强结果并标记复核。

## 仓库结构

```text
apps/h5/             移动优先的企业微信/浏览器客户端
apps/admin-web/      带审计能力的管理后台
apps/android/        Kotlin、Compose 与 CameraX 工程骨架
apps/ios/            SwiftUI 应用工程骨架
services/api/        账号、权限、项目、上传和审计 API
services/worker/     CPU 图像处理队列 Worker
services/ai-gateway/ 可选 AI 供应商校验边界
packages/            接口约定与共享翻译
deploy/              Compose、Nginx 和 PostgreSQL 控制项
docs/                架构与交付状态文档
```

## 文档与提交语言

本仓库的 README、架构、实施状态、发布说明及其他说明性文档统一使用中文；Git 提交标题和正文也使用中文。代码标识符、协议字段、命令和必要的技术专有名词保持原文。

## 许可证

版权所有 © 2026。目前尚未选择开源许可证，保留所有权利。

