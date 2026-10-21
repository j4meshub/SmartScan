# Android 分层工程与 API 客户端

## 范围

`AND-001` 建立可持续扩展的 Android 工程边界，不在这一工作包内实现真实登录、本地加密缓存、CameraX 状态机或离线上传。应用使用 Kotlin、Compose、Retrofit、OkHttp 和 Kotlin Serialization，构建基线为 JDK 17、Gradle 8.9、Android Gradle Plugin 8.7.3 与 Android 35 SDK。

## 模块职责

```text
:app
  ├─ Compose 导航与 Android 生命周期
  ├─ 应用级依赖装配
  └─ BuildConfig 环境入口
        │
        ├─ :core:auth ── 设备会话模型与存储抽象
        ├─ :core:upload ── 用户分区上传队列模型与存储协议
        ├─ :core:security ── Android Keystore 加密实现
        ├─ :data:local ── Room 用户分区缓存
        ├─ :data:repository ── 领域模型映射与稳定失败分类
        │       │
        │       ├─ :core:model
        │       └─ :core:network
        │
        ├─ :core:network ── Retrofit 契约、序列化与请求头
        ├─ :core:model ── 不依赖 Android 的领域对象
        ├─ :feature:capture ── CameraX 预览、质量提示与原图捕获
        ├─ :feature:sync ── WorkManager、分片续传与会话恢复
        ├─ :feature:workspace ── 页面编辑、导出下载与分享入口
        ├─ :core:update ── 签名清单、版本、哈希与 APK 身份规则
        └─ :feature:update ── 受控下载、PackageManager 校验与系统安装器
```

- `:core:model` 只保存项目、页面、任务和导出领域模型，可被后续缓存与界面复用。
- `:core:network` 声明当前 `/v1` 读取契约，忽略服务端新增的可选字段，但不吞掉缺失必填字段或类型错误。
- `:data:repository` 隔离 DTO 与领域对象，并把 HTTP、网络和响应解析失败转换为不泄漏异常内容的分类结果。
- `:feature:capture` 封装 CameraX 生命周期、实时亮度/清晰度/高光提示、点按对焦、曝光补偿、手动快门和不可变原图落盘；不依赖网络或认证实现。
- `:core:upload` 定义与 Android 框架无关的队列状态、项目/页面模型和用户分区存储协议；`:data:local` 使用 Room v2 实现。
- `:feature:sync` 负责私有原图入队、WorkManager 网络约束、服务端确认分片续传和登录恢复；不读取其他用户队列。
- `:feature:workspace` 负责项目恢复、页序、旋转、四角/滤镜编辑、复核、导出创建和鉴权制品下载；系统分享仍由 `:app` 通过受限 `FileProvider` 执行。
- `:core:update` 负责与 Android 框架无关的 ECDSA P-256 清单验签、版本/地址/哈希与 APK 身份规则；`:feature:update` 负责每日检查、私有目录下载、实包证书读取和系统安装确认。
- `:app` 只负责 Android 入口、Compose 导航、系统分享和依赖装配。账号删除入口调用服务端冷静期流程，并按用户清理本地队列和私有原图。

依赖方向只允许上层依赖下层；网络模块不能依赖应用模块，领域模型不能依赖 Android 或传输库。

## 环境与传输安全

API 根地址通过 Gradle 属性 `SMARTSCAN_API_BASE_URL` 注入，例如：

```text
gradle -p apps/android -PSMARTSCAN_API_BASE_URL=https://staging.example.com/ :app:assembleDebug
```

仓库默认值为不可解析的 `https://api.smartscan.invalid/`，避免未配置环境时误连真实服务。运行时配置遵守以下边界：

- 远端地址必须使用 HTTPS，且不得携带用户名、密码、查询参数或片段。
- HTTP 只允许测试显式开启的 `localhost`、`127.0.0.1` 或 `::1`。
- Android 清单禁用明文流量；调试局域网地址也不会被默认放行。
- 访问令牌只通过 `Authorization` 请求头发送，不写入 URL。
- 每个请求携带设备 ID、经过编码的设备名称和 `android` 平台标识。
- 默认配置不包含真实令牌；`AND-002` 再以 Keystore 支持的会话存储实现 `AccessTokenProvider`。

## 契约与错误边界

当前 Android 产品链路已消费认证、项目/上传、页面读取与编辑、复核、导出创建/查询/下载和账号删除接口。兼容策略只登记已进入产品链路的 `operationId`；仅存在 DTO 或未接入界面的接口不能据此宣称功能完成。

仓储层把失败归类为未授权、不存在、限频、服务端、网络、无效响应和未知错误。返回值不携带底层主机、异常消息或响应正文，界面必须根据分类决定登录、重试或用户提示。

## 验证

本机具备 JDK 17、Gradle 8.9 与 Android 35 SDK 时运行：

```text
gradle -p apps/android :core:network:test :core:security:testDebugUnitTest :core:upload:test :data:repository:test :data:local:testDebugUnitTest :feature:capture:testDebugUnitTest :feature:sync:testDebugUnitTest :feature:workspace:testDebugUnitTest :app:testDebugUnitTest :app:lintDebug
```

GitHub CI 会安装固定工具链并执行同一命令。网络单元测试使用本地 `MockWebServer`，只验证请求头、路径和兼容解析，不访问开发、staging 或生产 API。模拟器、真机、FileProvider 目标应用分享、相机、弱网和后台恢复仍保留人工验收。

