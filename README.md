# SmartScan / 智能扫描

SmartScan 是一套注重隐私的文档扫描平台，为企业微信 H5、Android、iOS 和浏览器管理后台提供统一的账号与数据层。系统设计保证在关闭全部外部 AI 的情况下，基础处理链路仍可运行。

本仓库是依据 v1.4 实施方案建立的首个可执行基线，并非已经具备 App Store 上架或生产验收条件的最终版本。当前完成范围和剩余工作详见[实施状态](docs/IMPLEMENTATION_STATUS.md)。

长期开发采用可断点续接的工作包机制。完整路线见[长期执行计划](docs/CODEX_EXECUTION_PLAN.md)，当前断点和验证证据见[长任务进度](docs/CODEX_PROGRESS.md)，跨阶段技术选择见[实施决策记录](docs/DECISIONS.md)。

## 当前包含内容

- FastAPI API：本地注册与登录、Argon2id 密码哈希、手机号确定性 HMAC、随机会话令牌和会话撤销。
- 服务端 RBAC：实现 `user`、`admin`、唯一 `super_admin` 的数据可见范围。
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
pip install -e ".[dev,vision]"
copy .env.example .env   # macOS/Linux 使用 cp
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

开发环境注册使用 `SMARTSCAN_DEV_SMS_CODE`，非开发环境会拒绝该验证码。首次启动 API 前应设置 `SMARTSCAN_SUPERADMIN_PASSWORD`，以初始化受保护的超级管理员。生产环境会拒绝缺失或强度不足的核心密钥，仓库中不会硬编码方案文档里的示例密码。

## 容器运行

将 `.env.example` 复制为 `.env`，替换所有密钥后执行：

```bash
docker compose -f deploy/compose/docker-compose.yml up --build
```

使用 PostgreSQL 时，应在应用表结构创建后执行 `deploy/postgres/001_guards.sql`。正式上线前必须将该初始化方式替换为版本化数据库迁移，并配置 TLS、加密备份和生产密钥管理。

## 测试

```bash
ruff check services
pytest
node --check apps/h5/app.js
node --check apps/admin-web/app.js
```

## 安全基线

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

