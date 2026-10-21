# SmartScan 长任务进度

更新时间：2026-10-21

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M6 iOS |
| 当前工作包 | `IOS-004` 后台恢复（进行中） |
| 工作包状态 | 用户分区队列、分片续传与 BGProcessing 恢复已实现，等待 macOS Simulator 编译验证 |
| 当前分支 | `codex/ios-004-background-upload` |
| 最后验证基线 | `5977b44`（IOS-003 PR #39 已合并） |
| 工作包提交 | 待提交 |
| PR | 待创建 |
| 下一工作包 | `IOS-005` 编辑与分享 |

## 当前工作包进展

- IOS-003 已由 PR #39 合并到主线，中文 squash 提交为 `5977b44`；最终文档头两套 API、Web、Android、iOS 与容器共 10 项 CI 检查通过。
- IOS-004 使用按用户摘要分区的版本化 JSON 队列，原图只允许来自当前用户私有捕获目录；队列原子写入并使用首次解锁后的完整文件保护，重复捕获 ID 幂等忽略。
- 上传处理器创建服务端项目与上传会话，流式计算整图 SHA-256；恢复时只跳过服务端 `received_chunks` 明确确认的分片，逐片校验哈希回执，完成响应丢失后通过已完成上传与 `page_id` 幂等收敛。
- `401` 只尝试一次现有刷新令牌流程；断网、`408`、`429` 和 `5xx` 保持幂等键等待重试，上传会话过期才轮换幂等键。登录用户与队列所有者不一致时暂停，禁止跨账号接管。
- `BGProcessingTask` 仅在系统授予执行时间且网络可用时恢复队列，过期会取消当前任务并保留可重入状态；不宣称后台任务会按固定时间执行。
- 拍照成功后先保存不可变原图，再持久化入队并触发前台处理/后台调度；界面区分“已保存并入队”和“原图已保存但入队失败”。
- 新增队列持久化、跨用户拒绝、上传过期轮换、服务端确认分片、完成收敛、单次刷新和账号隔离测试；本地 iOS 契约 `8 passed`，Swift 编译和 Simulator 测试等待 macOS CI。

- IOS-002 已由 PR #38 合并到主线，中文 squash 提交为 `2944430`；最终文档头两套 API、Web、Android、iOS 与容器共 10 项 CI 检查通过。
- IOS-003 三个首页模式已进入同一 AVFoundation 后摄拍摄页，包含权限、预览、点按对焦、曝光补偿、手动快门和连续拍摄状态机；质量警告不禁用快门。
- 视频帧每 250 毫秒抽样亮度、梯度清晰度和高光比例，Vision 同时提供文档矩形与置信度；阈值只生成提示，不声称替代服务端复核或真实样本校准。
- 拍照使用 `fileDataRepresentation()` 的 JPEG 原始数据，不进行裁切或增强；原图与 JSON 方向/尺寸/质量/矩形证据成对写入当前用户摘要目录，任一写入失败都会清理残留。
- 新增相机用途双语说明、状态机、质量指标、方向映射、用户隔离原图存储测试和 iOS 工程安全契约；本地通过 Ruff/格式、iOS 契约 `7 passed`、全量 Python `169 passed, 5 skipped`、覆盖率 `88.28%`、API 兼容、迁移升级/漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法和差异检查。
- 首轮提交 `d19c7ee` 的 macOS 编译发现多语句计算属性缺少显式返回；修复同时改用 iOS 17 的 `videoRotationAngle` API，避免继续依赖已弃用的 `AVCaptureVideoOrientation`。
- 修复提交 `2449395` 的推送与 PR 两套 API、Web、Android、iOS 和容器共 10 项检查全部通过；两个 iOS 作业均完成工程生成、Xcode 16.4 Simulator 编译和全部 Swift 单元测试。

- IOS-001 已由 PR #37 合并到主线，中文 squash 提交为 `4cc0a18`；最终代码头两套 API、Web、Android、iOS 与容器共 10 项 CI 检查通过。
- IOS-002 已接入注册、短信挑战、本地登录、`/v1/me` 会话恢复、一次性刷新令牌轮换和退出；接口字段与现有 H5/Android 客户端保持一致。
- 访问令牌、刷新令牌和稳定设备 ID 保存到 iOS Keychain，使用 `AfterFirstUnlockThisDeviceOnly`，设备 ID 与可清除的会话项分离。
- API 客户端默认使用不可解析的 `https://api.invalid/`，只接受 HTTPS 或显式回环 HTTP；统一发送设备 ID、百分号编码设备名和 `ios` 平台头，认证请求才附带 Bearer 令牌。
- 项目缓存按用户 ID 的 SHA-256 目录分区，退出时即使服务端不可达也清除当前用户会话和缓存，不清除其他用户数据。
- SwiftUI 增加中英文登录/注册界面、短信挑战状态、会话恢复和本地退出提示；当前尚未加入企业微信入口，该能力不在 IOS-002 交付范围。
- 新增身份模型、Keychain、API 请求头/错误、刷新恢复、注销失败清理和用户缓存隔离单元测试；本地通过 Ruff/格式、iOS 工程契约 `5 passed`、全量 Python `167 passed, 5 skipped`、覆盖率 `88.28%`、API 兼容、迁移升级/漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法和差异检查。
- 首轮提交 `8dbad86` 已在两套 macOS 作业成功完成 Swift 编译；Simulator 仅有请求体断言失败。`URLProtocol` 接收的上传体可能转换为 `httpBodyStream`，测试读取逻辑同时支持 `httpBody` 与流后重跑，不修改产品请求协议。
- 修复提交 `284da8e` 的推送与 PR 两套 API、Web、Android、iOS 和容器共 10 项检查全部通过；两个 iOS 作业均完成工程生成、Xcode 16.4 Simulator 编译和全部 Swift 单元测试。

- AND-006 已由 PR #36 合并到主线，中文 squash 提交为 `4709c61`；最终文档头两套 API、Web、容器与 Android 共 8 项 CI 检查通过。
- IOS-001 使用 `project.yml` 作为唯一工程规范，固定 XcodeGen `2.46.0` 官方发布 ZIP 与 SHA-256；生成的 `.xcodeproj` 和本地工具目录不提交。
- GitHub CI 新增 `macos-15` 作业并显式选择 Xcode 16.4，不依赖 `macos-latest` 默认版本；使用无签名 iPhone 16 Pro Simulator 执行应用编译和单元测试。
- 新增应用/测试 Target、共享 Scheme、iOS 17 最低版本和开发占位 Bundle ID；正式 Bundle ID、Team 与签名参数未冻结且不进入当前配置。
- 首页扫描模式抽成稳定枚举并增加单元测试；所有可见首页文案补齐英文和简体中文资源。
- 本地通过 Ruff/格式、iOS 配置契约 `4 passed`、全量 Python `166 passed, 5 skipped`、覆盖率 `88.28%`、API 兼容、迁移升级/漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法和差异检查。Windows 无法运行 XcodeGen、Xcode 与 Simulator，必须等待 macOS CI，不能把 YAML 契约测试记为 Swift 编译通过。
- 首轮提交 `915ee44` 的 iOS CI 在哈希校验通过后发现官方 ZIP 顶层为包含 `bin` 与 `share` 的目录，脚本误把目录当作单一可执行文件。提交 `51b182c` 保留完整发布目录并补充结构契约测试，不绕过摘要或版本门禁。
- `51b182c` 的推送与 PR 两套 API、Web、Android、iOS、容器共 10 项检查全部通过；两个 iOS 作业均完成工程生成、Xcode 16.4 Simulator 编译和 Swift 单元测试。

- AND-005 已由 PR #35 合并到主线，中文 squash 提交为 `649b441`；最终头两套 API、Web、容器与 Android 共 8 项 CI 检查通过。
- AND-006 新增 `:core:update` 纯 JVM 模块，使用固定 ECDSA P-256 公钥和 SHA-256 验证原始清单字节，篡改后在解析和下载前拒绝；该算法覆盖 Android API 26 起的目标系统。
- 已校验清单版本、应用包名、版本号、最低支持版本、HTTPS APK 地址、APK SHA-256 和 APK 签名证书摘要格式；APK 文件哈希使用流式读取和定时安全比较。
- 提交 `8b98466` 的推送 CI 4 项全部通过，包含新增更新核心单元测试及既有 Android 编译/Lint 门禁。
- 新增 `:feature:update`，只在完整安全配置下启用；禁止重定向和带凭据、查询、片段的固定 URL，限制清单、签名与 APK 响应大小。
- APK 下载到应用私有临时文件并校验精确大小、SHA-256、包名、版本和发布/已安装证书，提交后在打开系统安装器前再次校验；应用不执行静默安装。
- 设置页提供每日自动检查、手动检查、下载和明确安装动作；未知来源权限缺失时只打开本应用授权页，异常时返回稳定拒绝结果。
- 新增 Python 清单生成器，使用独立 ECDSA P-256 私钥签署规范 JSON；正式私钥、APK keystore、带令牌地址和真实发布清单不得进入仓库。
- 本地通过 Ruff/格式、`162 passed, 5 skipped`、覆盖率 `88.28%`、API 兼容、迁移升级/漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法、双语资源键和差异检查。当前机器没有 Gradle、JDK/Android SDK 与 Docker 命令，这些本地缺项已由 GitHub CI 覆盖。
- 完整实现首轮提交 `c36b42c` 的 API、Web 与容器通过；Android 编译发现 `:core:update` 的公开构造签名暴露 `Json` 类型但依赖仍为内部实现。提交 `4676b90` 将该依赖改为 API 边界，不跳过测试。
- `4676b90` 的推送与 PR 两套 API、Web、容器和 Android 共 8 项检查全部通过；Android 完成核心/更新功能/Robolectric/应用测试、应用编译和 `lintDebug`。
- GitLab 项目、更新域名、正式公钥和签名材料尚未冻结，继续作为外部门禁；默认配置不得指向任何真实发布源。

- AND-004 已由 PR #34 合并到主线，中文 squash 提交为 `9b19932`；最终头的 API、Web、容器与 Android 共 8 项 CI 检查通过。
- 新增 `:feature:workspace`，接入项目/页面恢复、完整页序、旋转、四角/滤镜编辑、复核、PDF/JPG 导出和分享入口。
- 页面预览与导出均使用带会话的流式下载；导出制品校验长度与 SHA-256 后才原子落入分享目录，失败会删除临时文件。
- `FileProvider` 只开放 `cache/exports/`，分享前再次检查 canonical 父目录，页面预览、令牌和私有真实路径不会交给第三方应用。
- 设置页接入完整手机号、强验证短信和用户名确认的账号删除申请；登录页接入冷静期撤销。
- 服务端接受删除后，客户端按用户取消上传链、清理该用户私有原图和 Room 队列；清理失败会提示通过系统设置清除应用存储，不静默宣称成功。
- 新增网络契约、仓储下载、表单、页序和 Room 用户隔离测试；Android 编译、Lint、模拟器与真机结果尚未产生。

`AND-005` 计划门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm --prefix apps/h5 ci
npm --prefix apps/h5 test
npm --prefix apps/h5 run test:e2e
gradle -p apps/android :core:network:test :core:security:testDebugUnitTest :core:upload:test :data:repository:test :data:local:testDebugUnitTest :feature:capture:testDebugUnitTest :feature:sync:testDebugUnitTest :feature:workspace:testDebugUnitTest :app:testDebugUnitTest :app:lintDebug
git diff --check
```

本地结果：137 个 Python 文件格式与 Ruff、OpenAPI 当前/上一代客户端兼容、迁移升级/漂移/版本、CI YAML、14 个 Android XML、应用与工作区双语资源键和差异检查通过；后端 `156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；H5 `33 passed`，Chromium E2E/axe `3 passed`，管理后台 JavaScript 语法通过。本机未安装 JDK、Gradle 与 Android SDK，因此 Android 编译、单元测试和 Lint 将由固定 GitHub CI 环境验证；该限制不替代模拟器和真机人工验收。

首轮推送提交 `0fd95b0` 的 API、Web 与容器 CI 通过；Android 仓储测试发现落盘防冲突前缀被错误暴露为用户下载文件名。修复将安全存储名与展示名分离，继续保留制品 ID 前缀避免缓存覆盖，分享界面使用服务端原始文件名。

第二轮提交 `9c56f77` 的 API、Web 与容器 CI 通过；Android 编译发现新增可选展示名参数插入了既有位置参数中间，使页面预览调用的空哈希被错误绑定为非空展示名。修复把可选展示名移到参数列表末尾，保持既有位置调用兼容。

第三轮提交 `9491c24` 的 API、Web 与容器 CI 通过，仓储测试已越过此前失败；Android 编译发现 Compose `RowScope.weight` 被显式导入时解析到同文件内部属性。移除该错误导入，让 `Row` 作用域直接解析公开成员扩展，不改变布局行为。

第四轮最终代码头 `9f1755f` 的两套 API、Web、容器与 Android 共 8 项检查全部通过。Android 完成网络/仓储/Room/同步/工作区/应用单元测试、应用编译和 `lintDebug`；真实目标应用分享、删除与运行中 Worker 并发、真实短信撤销、动态字体、TalkBack 和目标真机仍保留人工验收，不以 CI 结果替代。

## 已完成前置工作包证据

- AND-003 已由 PR #33 合并到主线，中文 squash 提交为 `b238992`；三模式 CameraX 预览、点按对焦、曝光补偿、质量提示、手动快门和原图保护已完成。
- 新增 `:core:upload` 队列协议与 `:feature:sync` WorkManager/续传模块；应用捕获成功只有在原图持久化入队后才显示成功。
- Room 从 v1 升级到 v2，新增用户分区的本地上传项目与页面队列；显式迁移保留已有项目缓存，不使用破坏性重建。
- 同一本地项目使用 WorkManager 唯一工作链和联网约束；登录恢复会重新调度当前用户队列，换用户不会处理其他用户原图。
- 原图流式计算 SHA-256，创建上传会话后只跳过服务端 `received_chunks` 确认的分片；每个二进制分片携带并校验独立哈希回执。
- 断网、超时、`408`、`429` 和 `5xx` 保持幂等键并指数退避；上传过期才轮换幂等键；完成响应丢失可由服务端 `page_id` 收敛。
- `401` 先复用一次性刷新令牌流程，刷新失败进入等待登录；本地文件缺失、分片计划或回执不一致进入不可安全重试的失败状态。
- 入队仅接受应用私有 `files/captures/originals` 的 canonical 路径，拒绝外部路径和目录穿越；成功上传不删除原图。

`AND-004` 计划门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm --prefix apps/h5 ci
npm --prefix apps/h5 test
npm --prefix apps/h5 run test:e2e
gradle -p apps/android :core:network:test :core:security:testDebugUnitTest :core:upload:test :data:repository:test :data:local:testDebugUnitTest :feature:capture:testDebugUnitTest :feature:sync:testDebugUnitTest :app:testDebugUnitTest :app:lintDebug
git diff --check
```

Android 门禁将验证 Room v1→v2 迁移、队列用户隔离、服务端确认分片恢复、断网重试幂等键、过期轮换、二进制请求契约、WorkManager/应用编译和 Lint。本机未安装 Android 工具链，模拟器、真机网络切换和 staging 服务端重启继续保留人工验收。

本地结果：95 个 Python 文件格式与 Ruff、OpenAPI 客户端兼容、迁移模型漂移、CI YAML、Android XML、兼容策略 JSON 和差异检查通过；后端 `156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；H5 `33 passed`，Chromium E2E/axe `3 passed`。本机未安装 Docker、JDK、Gradle 与 Android SDK，因此 Compose 配置以及 Android 的 Room/Robolectric、续传处理器、应用编译和 Lint 交由 PR CI 验证；缺少本机工具链不是产品门禁通过证据。

首轮推送提交 `78e5b94` 的 API、Web 与容器 CI 通过；Android 编译发现既有仓储测试的 `ScanApi` Fake 未实现本工作包新增的项目创建与上传方法。修复补齐测试替身的完整接口边界，保持未使用的方法显式失败，等待第二轮验证。

第二轮提交 `483fef9` 的 API、Web 与容器 CI 通过；Android 编译继续发现 suspend 成员函数引用不能直接传给 `let`，以及跨模块可空属性不能依赖智能类型转换。修复改为显式分支调用并在完成态收窄 `page_id`，同时消除测试替身属性对 Kotlin `error` 函数的名称遮蔽，等待后续验证。

后续提交 `ac5fbc3` 已越过主代码编译，Android 单元测试编译发现 `PageDto` 的公开字段暴露 `JsonElement`，但 `:core:network` 将其依赖声明为内部实现。修复把序列化 JSON 调整为 API 依赖，使公开 DTO 的完整类型在消费模块可解析，等待下一轮验证。

提交 `8b11f39` 已进入应用编译和 Room/Robolectric 执行阶段：应用模块需要显式声明其实际消费的 `:core:upload` 类型；新增 Room 测试未绑定 Robolectric Runner，导致 Android Application 上下文未初始化。修复补齐模块依赖和两类 Room 测试 Runner，不用跳过测试或改成破坏性迁移。

提交 `a6dffeb` 的 API、Web、容器与 Android CI 全部通过；Android 完整执行 Room v1→v2 迁移、用户隔离队列、续传处理器、既有模块与应用单元测试、应用编译和 `lintDebug`。PR #34 已创建，真实弱网、进程强杀、服务端重启和大文件门禁仍等待目标设备与 staging，未被 CI 结果替代。

- AND-002 已由 PR #32 合并到主线，中文 squash 提交为 `60bac1e`；认证仓储、Keystore 会话、Room 用户分区缓存、Compose 登录注册与退出清理已完成。
- 新增 `:feature:capture`，将 CameraX 生命周期、状态机、质量提示和原图捕获从 `:app` 分离；模块不依赖认证、网络或仓储。
- 首页智能扫描、试卷净化和连续扫书入口已传入明确的 `CaptureMode`，三种模式共用后摄预览，底部导航在相机内隐藏。
- CameraX 使用 `KEEP_ONLY_LATEST` 在独立线程分析 Y 平面；最多每 250 毫秒更新亮度、相邻抽样差和极亮比例提示，不阻塞预览。
- 用户可点按预览触发 AF/AE、使用设备支持范围内的曝光补偿，并在相机就绪后手动快门；没有倒计时或自动拍摄。
- 原图写入应用私有 `files/captures/originals`，文件名不含用户信息；低质量只提示不禁拍，保存失败不创建成功状态。
- 连续扫书自动快门仍属于 `BOOK-001`，上传和后台恢复仍属于 `AND-004`，当前不以占位逻辑宣称完成。

`AND-003` 计划门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm --prefix apps/h5 ci
npm --prefix apps/h5 test
npm --prefix apps/h5 run test:e2e
gradle -p apps/android :core:network:test :core:security:testDebugUnitTest :data:repository:test :data:local:testDebugUnitTest :feature:capture:testDebugUnitTest :app:testDebugUnitTest :app:lintDebug
git diff --check
```

本机已通过差异检查、Android Manifest/双语资源 XML 解析和中英文资源键一致性检查。本机未安装 JDK、Gradle 与 Android SDK，CameraX/Compose 编译、拍摄状态机与质量评估单元测试、应用单元测试和 Lint 等待 GitHub CI；模拟器和真机不因 CI 通过而自动验收。

首轮推送 CI 的 API、Web 和容器门禁通过；Android 编译发现 `:app` 移除旧 Room 依赖后仍直接调用 `Room.databaseBuilder`。修复把数据库创建工厂收回 `:data:local`，应用层只调用 `SmartScanDatabase.open`，不把 Room API 再泄漏回应用模块，等待重跑验证。

第二轮 Android 编译确认返回 `SmartScanDatabase` 仍会让应用编译器解析其 `RoomDatabase` 父类。修复进一步把公开工厂返回类型收窄为 `UserScopedCache`，数据库与 DAO 类型完全停留在 `:data:local`，应用层不再感知 Room，等待第三轮验证。

第三轮提交 `302dc89` 的 API、Web、容器和 Android CI 已全部通过，PR #33 已创建。Android 在固定 JDK 17、Gradle 8.9 与 SDK 35 环境执行 187 个任务，完成拍摄状态机/质量评估、既有模块与应用单元测试、应用编译和 `lintDebug`，`BUILD SUCCESSFUL`；该结果不替代 CameraX 真机验收。

- AND-001 已由 PR #31 合并到主线，中文 squash 提交为 `41bf07d`；领域、网络、仓储与应用模块、Compose 导航、HTTPS 配置和 Android CI 基线已完成。
- AND-002 已核对并接入服务端注册、登录、刷新、注销与 `/v1/me` 契约。
- 注册、登录、验证码申请、启动恢复、一次性刷新与注销已进入认证仓储和 Compose 产品入口；认证失败不保留半完成会话。
- Keystore 使用 AES-GCM 信封加密会话；损坏密文自清理，令牌不进入 Room、URL 或日志。
- Room 项目缓存使用 `(owner_user_id, id)` 复合主键，所有访问显式传入用户 ID；远端失败只回退当前用户缓存。
- 远端注销失败仍清理加密会话与当前用户缓存，本地两项清理互不跳过。
- H5-005 已由 PR #30 合并到主线，中文 squash 提交为 `6d20db5`；M4 桌面自动化门禁完成，真实企微、短信、相机、弱网、系统分享和屏幕阅读器继续保留人工验收。
- Android 工程已拆分 `:core:model`、`:core:network`、`:data:repository` 和 `:app`，依赖方向保持从应用到仓储/网络再到领域模型。
- Compose 已建立首页、项目和设置三个稳定导航入口；项目与设置业务页由后续工作包接入，不以占位界面宣称功能完成。
- Retrofit/OkHttp 客户端已建模项目、页面、任务和导出读取接口，项目仓储完成 DTO 到领域模型映射及稳定错误分类。
- 远端 API 根地址强制 HTTPS，禁止凭据、查询与片段；HTTP 仅能在测试显式允许回环地址。默认使用不可解析的 `.invalid` 域名，不携带真实令牌。
- `MockWebServer` 验证项目请求路径、设备头、Bearer 头和新增可选字段兼容；兼容矩阵只登记已进入仓储产品链路的项目列表接口。
- 提交前自审发现通用 `data/` 忽略规则误伤 Android 仓储模块，已增加仅针对 `apps/android/data` 的例外并核对实现提交包含全部 34 个预期文件。

`AND-002` 计划门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm --prefix apps/h5 ci
npm --prefix apps/h5 test
npm --prefix apps/h5 run test:e2e
gradle -p apps/android :core:network:test :core:security:testDebugUnitTest :data:repository:test :data:local:testDebugUnitTest :app:testDebugUnitTest :app:lintDebug
git diff --check
```

本机结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；134 个 Python 文件格式、Ruff、OpenAPI 兼容、迁移升级/漂移/版本、H5 `33 passed`、Chromium E2E 与 axe `3 passed`、JavaScript 语法、配置解析、密钥模式和差异检查均通过。5 项 PostgreSQL 专属测试及 Android 编译、Room/Robolectric、应用单元测试和 Lint 等待 PR CI；本机未安装 JDK、Gradle 与 Android SDK。

首轮推送 CI 的 API、Web 和容器门禁通过；Android 在 `:data:local:kaptDebugKotlin` 暴露 Room 2.6.1 只能读取 Kotlin 2.0 元数据、无法处理工程 Kotlin 2.1 元数据的问题。修复统一升级 Room runtime、KTX、compiler 和 testing 到 2.7.2，保留全部 Android 测试与 Lint 门禁。修复提交 `f435d3b` 的 API、Web、容器与 Android CI 已全部通过，PR #32 已创建；Android 使用固定 JDK 17、Gradle 8.9 与 SDK 35 完成 network/security/repository/local/app 单元测试和 `lintDebug`。

`AND-001` 计划门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/auth-client.js
node --check apps/h5/camera.js
node --check apps/h5/i18n.js
node --check apps/h5/page-editor.js
node --check apps/h5/project-files.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
npm --prefix apps/h5 ci
npm --prefix apps/h5 test
npm --prefix apps/h5 run test:e2e
gradle -p apps/android :core:network:test :data:repository:test :app:testDebugUnitTest :app:lintDebug
git diff --check
```

本机结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；133 个 Python 文件格式、Ruff、OpenAPI 兼容、迁移升级/漂移/版本、H5 `33 passed`、Chromium E2E 与 axe `3 passed`、JavaScript 语法、CI YAML、Android Manifest、兼容策略 JSON、密钥模式和差异检查均通过。5 项 PostgreSQL 专属测试及 Android 编译等待 PR CI 复核。本机未安装 JDK、Gradle 与 Android SDK，Android JVM 单元测试、应用单元测试和 Lint 将由固定 JDK 17、Gradle 8.9 与 Android 35 SDK 的 GitHub CI 执行；这不等同于模拟器或真机验收。

PR #31 最终代码提交 `a2fb25a` 的两套 CI 全部通过：PostgreSQL 17 环境 `161 passed`、应用代码覆盖率 `88.54%`；Web 的 33 项单元测试和 3 项 Chromium E2E/axe、容器门禁均通过；Android 使用 JDK 17、Gradle 8.9 与 Android 35 SDK 完成网络/仓储 JVM 单元测试、应用单元测试和 `lintDebug`，Gradle `BUILD SUCCESSFUL`。前两轮分别暴露废弃 SDK `tools` 包和 `sdkmanager` 路径问题；进入编译后依次发现仓储直接依赖缺失及相机硬件声明问题，均按模块边界和文件上传兜底的真实语义修复后重跑，没有跳过测试或关闭 Lint。模拟器和真机仍是后续人工门禁。

`H5-005` 本地结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；132 个 Python 文件格式、Ruff、OpenAPI 兼容、迁移升级/漂移/版本、H5 `33 passed`、Chromium E2E 与 axe `3 passed`、JavaScript 语法和差异检查均通过。PR #30 CI 在 PostgreSQL 17 环境 `161 passed`，覆盖率 `88.54%`；Web 的 33 项单元测试和 3 项 Chromium E2E/axe、容器门禁全部通过。

`H5-004` 本地结果：`156 passed, 5 skipped`，覆盖率 `88.28%`，H5 `29 passed`。PR #29 CI 在 PostgreSQL 17 环境 `161 passed`，覆盖率 `88.54%`；Web 与容器门禁全部通过。

`H5-003` 本地结果：`156 passed, 5 skipped`，应用代码覆盖率 `88.28%`；H5 `25 passed`，OpenAPI、迁移、JavaScript 和差异检查通过。PR #28 CI 在 PostgreSQL 17 环境 `161 passed`，覆盖率 `88.54%`；Web 与容器门禁全部通过。

- API-001 已由 PR #25 合并到主线，中文 squash 提交为 `4a76fb9`；当前与上一代契约继续由 CI 双门禁保护。
- H5 登录请求现在发送稳定设备标识，获得短期访问令牌和单次轮换刷新令牌；并发 `401` 共用一次刷新，失败后清理会话。
- 凭据只原子保存在标签页 `sessionStorage`，设备 ID 单独保存在 `localStorage`；旧版长期访问令牌键会被清理。
- 企业微信授权、回调、可信手机号直接登录、缺手机号短信绑定、冲突错误和安全退出已接入双语界面。
- 企微回调增量返回完整设备会话，契约修订为 `2026-10-20.2`；H5 实际消费的认证操作已登记到兼容矩阵。
- Mock 和自动测试只证明本地契约；真实企微租户、真实短信、HTTPS Cookie 与 Android 企业微信内置浏览器保持人工验收。

`H5-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/auth-client.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
npm test  # apps/h5
git diff --check
```

本地结果：`152 passed, 5 skipped`，应用代码覆盖率 `88.29%`；128 个 Python 文件格式、Ruff、当前/上一代 OpenAPI 兼容检查、迁移升级/漂移/版本、H5 `17 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 复核。

PR #26 CI 结果：PostgreSQL 17 环境 `157 passed`，应用代码覆盖率 `88.56%`；H5 `17 passed`，OpenAPI 兼容、数据库漂移、Web 和容器门禁均通过。该结果不替代真实企微租户、短信、HTTPS Cookie 或 Android 企业微信内置浏览器验收。

- FILE-001 已由 PR #24 合并到主线，中文 squash 提交为 `d8025b8`；生产 TLS、大文件并发、磁盘满和备份恢复继续保留 OPS staging 门禁。
- API-001 使用 `openapi.json` 固定当前运行时契约，并以独立 `openapi-baseline.json` 固定仍受支持的上一代客户端基线。
- 机器可读兼容策略只登记 H5 和管理后台当前实际消费的 `operationId`；Android/iOS 仍是骨架，不虚报已接通接口。
- 兼容检查允许新增端点和可选字段，禁止删除旧能力、增加必填项、修改类型/引用/枚举或静默缩短支持窗口。
- 弃用必须同时更新 OpenAPI 与策略，提供替代方案并保留至少 90 天；当前没有登记弃用。
- API 响应新增 `X-SmartScan-API-Version` 和契约修订号，GitHub/GitLab CI 都显式运行兼容检查器。

`API-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python tools/api_compatibility.py
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`152 passed, 5 skipped`，应用代码覆盖率 `88.28%`；127 个 Python 文件格式、Ruff、当前/上一代 OpenAPI 兼容检查、删除端点/新增必填字段/枚举变化反例、运行时精确快照、版本响应头、迁移升级/漂移/版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 复核。

PR #25 CI 结果：PostgreSQL 17 环境 `157 passed`，应用代码覆盖率 `88.55%`；OpenAPI 当前契约兼容上一代客户端基线，数据库未检测到遗漏迁移，Web 与容器门禁均通过。

`FILE-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
python -c "解析 Compose 并断言 X-Accel 前缀与 Nginx 只读存储卷"
git diff --check
```

本地结果：`149 passed, 5 skipped`，应用代码覆盖率 `88.23%`；124 个 Python 文件格式、Ruff、`0017` 空库/旧版本升级与降级、上传取消降级映射、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法、Compose X-Accel 映射和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核；本机无 Docker，完整 `docker compose config` 由 PR CI 执行。

PR #24 CI 结果：PostgreSQL 17 环境 `154 passed`，应用代码覆盖率 `88.49%`；API、Web/H5 和 Compose/容器 3 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0017` 原生枚举转换、PostgreSQL 项目清理状态、Nginx 配置和只读存储卷通过，不替代真实 TLS、大文件 Range 并发、磁盘满或备份恢复验收。

上一工作包完成摘要：

`EXPORT-001` 本地门禁：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`143 passed, 5 skipped`，应用代码覆盖率 `88.46%`；118 个 Python 文件格式、Ruff、`0016` 空库升级与降级、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。首次 Web 命令误在仓库根目录执行，因根目录无 `package.json` 返回 `ENOENT`；切换到 `apps/h5` 后同一测试命令 8 项全部通过，这不是产品回归。

PR #23 CI 结果：PostgreSQL 17 环境 `148 passed`，应用代码覆盖率 `88.75%`；API、Web/H5 和 Compose/容器 3 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0016` 在 PostgreSQL、ReportLab 依赖安装、导出契约和容器配置下通过；不替代真实 PDF 视觉、超大项目内存峰值或真实中文文本复制验收。

上一工作包完成摘要：

- JOB-001 已由 PR #21 合并到主线，合并提交为 `1f5094b`。
- OCR-001 使用固定 `paddleocr==3.7.0`、`paddlepaddle==3.3.1` 的 CPU 本地适配器；模型包从只读目录加载并按版本与全部文件 SHA-256 校验，生产启动禁止关闭或首次请求联网下载。
- 已实现 0°、90°、180°、270° 四方向识别与置信/版式融合，每次推理后续租；非零方向没有明确优势时保持 0°，自动方向只作用于处理图，原图继续不可变。
- `0015` 已增加与活动页面结果版本关联的 OCR 全文、行框、模型、置信度、方向和状态；手动旋转会使旧 OCR 失效，旧 `ocr_text` 兼容迁移为 `legacy`。
- 标题候选过滤手机号、18 位证件号、页码、非法字符、重复扩展名和 Windows 保留名；建议名称不覆盖用户标题，无可信标题时按 locale 回退日期名称。
- 已覆盖离线模型适配参数/结果解析、清单篡改、方向阈值、敏感标题、Worker 失败重试、原图保留、页面 IDOR/管理员审计、迁移降级和 OpenAPI 增量契约。

`OCR-001` 提交前全量检查：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`140 passed, 5 skipped`，应用代码覆盖率 `88.80%`；114 个 Python 文件格式、Ruff、`0015` 空库/旧版本升级与降级、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法、Compose YAML/只读挂载解析和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。本机未安装 Docker，`docker compose config` 等待 PR CI 执行；本地 PyYAML 已验证锚点展开前的 YAML 结构与 OCR 只读挂载。

首次聚焦门禁曾发现全角中文冒号未清理、一个布尔表达式和未使用变量问题；补齐全角非法字符后重跑为 `31 passed`。首次全量门禁的唯一失败是新增测试误把既有审计成功值断言成 `success`，保持仓库统一的 `allowed` 契约后，OCR 专项 `3 passed`、最终全量 `140 passed`。失败均已定位修复，没有放宽方向、隐私、权限或迁移断言。

真实 PP-OCRv6 模型包、已授权固定数据集、文字方向正确率 `≥98%`、CPU 耗时/内存和双 Worker 容量仍等待人工验收；自动化假引擎和适配器契约绿灯不得替代这些外部门禁。

PR #22 CI 结果：PostgreSQL 17 环境 `145 passed`，应用代码覆盖率 `89.11%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0015` 可在 PostgreSQL 升级、离线适配契约、四方向规则、敏感命名、页面权限和 Compose 只读模型挂载通过，不代表真实模型质量、容量或发布模型包已经验收。

上一工作包完成摘要：

- `0014` 已把旧作业状态兼容迁移为排队、基础处理、基础就绪、可选增强、就绪、分级失败和取消，并新增租约、心跳、退避、阶段时间戳和结果版本关联。
- Worker 现在通过随机租约令牌领取及续租；过期抢占、取消和重试都会使旧令牌失效，写结果时再次锁行校验，页面结果与作业终态在同一事务提交。
- 已新增所有者作业详情、取消和手动重试接口；管理员只读遵循既有角色矩阵，跨用户修改统一返回 `404` 并写审计。
- 已覆盖租约过期恢复、旧 Worker 拒绝、指数退避、最终失败、取消竞态、单结果幂等、接口 IDOR、旧库迁移/降级和 PostgreSQL 双 Worker 单次领取。

`JOB-001` 提交前全量检查：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`125 passed, 5 skipped`，应用代码覆盖率 `88.66%`；108 个 Python 文件格式、Ruff、`0014` 空库/旧版本升级与降级、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法和差异检查均通过。5 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

首次聚焦回归曾出现 2 项失败：一项测试未先升级隔离数据库，另一项仍断言 `0013` 中间态；补齐测试数据库升级并按 `0014` 终态断言后重跑为 `31 passed`。随后发现 PostgreSQL 专项测试 import 排序问题，修复后 Ruff 与全量门禁通过。这些失败均为测试装配问题，未通过放宽业务断言规避。

PR #21 CI 结果：PostgreSQL 17 环境 `130 passed`，应用代码覆盖率 `89.00%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过，迁移模型漂移为 `No new upgrade operations detected`。该绿灯证明 `0014` PostgreSQL 枚举迁移、双 Worker 单次领取、崩溃恢复语义和回归门禁通过，不代表真实进程强杀、磁盘满或目标服务器多 Worker 压力已经验收。

`SCAN-001` 提交前全量检查：

```text
python -m ruff format --check .
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`121 passed, 4 skipped`，应用代码覆盖率 `88.57%`；104 个 Python 文件格式、Ruff、`0013` 空库/旧版本升级与降级测试、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed`、JavaScript 语法和差异检查均通过。4 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #20 CI 结果：PostgreSQL 17 环境 `125 passed`，应用代码覆盖率 `88.63%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过。该绿灯证明页面版本、复核语义和 `0013` 迁移可在隔离 PostgreSQL 上运行，不代表真实相机质量、授权固定数据集或生产存储门禁已经通过。

`ADMIN-001` 提交前全量检查：

```text
python -m ruff check .
python -m pytest --cov=services --cov-report=term-missing -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
npm test  # apps/h5
git diff --check
```

本地结果：`117 passed, 4 skipped`，应用代码覆盖率 `87.75%`；Ruff、迁移向前升级至 `0012`、模型漂移、迁移版本、OpenAPI 快照、H5 `8 passed` 和差异检查均通过。4 项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #19 CI 结果：PostgreSQL 17 环境 `121 passed`，应用代码覆盖率 `87.75%`；两组 API、Web/H5 和 Compose/容器检查共 6 项全部通过。该绿灯证明管理权限、审计和迁移可在隔离 PostgreSQL 上运行，不代表生产备份恢复或真实 staging 门禁已经通过。

`ACC-002` 提交前 Python 与迁移检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term --cov-fail-under=77 -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
```

本地结果：`89 passed, 2 skipped`，应用代码覆盖率 `87.18%`；Ruff、54 个 Python 文件格式、迁移升级/漂移/版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。手机号保护专项 32 项通过；两项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #13 CI 结果：PostgreSQL 17 环境 `91 passed`，应用代码覆盖率 `87.18%`；Ruff、54 个 Python 文件格式、迁移升级/漂移、H5 `8 passed`、Web 与 Compose/容器检查全部通过。该绿灯证明加密结构、命名枚举和迁移可以在隔离 PostgreSQL 上运行，不代表真实 Secret 管理、备份恢复或生产轮换演练已经通过。

`ACC-001` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term --cov-fail-under=77 -q
python -m services.api.app.migrations upgrade
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`80 passed, 2 skipped`，应用代码覆盖率 `87.24%`；Ruff、50 个 Python 文件格式、迁移升级/漂移/版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，等待 PR CI 的 PostgreSQL 17 服务复核。

PR #12 CI 结果：PostgreSQL 17 环境 `82 passed`，应用代码覆盖率 `87.24%`；Ruff、50 个 Python 文件格式、迁移升级/漂移、H5 `8 passed`、Web 与 Compose/容器检查全部通过。该绿灯证明统一身份拆分及迁移在隔离 PostgreSQL 上可运行，不代表真实短信、企业微信租户或生产备份回滚门禁已经通过。

## 已执行验证

`POC-006` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`75 passed, 2 skipped`，应用代码覆盖率 `85.50%`；Ruff、47 个 Python 文件格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，当前 Windows 未安装 Docker；两者由 PR CI 复核。目标服务器不可用，未运行 30 分钟正式负载。

PR #11 CI 结果：PostgreSQL 17 环境 `77 passed`，应用代码覆盖率 `85.50%`；Ruff、47 个 Python 文件格式、迁移升级/漂移、Web、H5 `8 passed` 和 Compose/容器检查全部通过。该绿灯验证负载工具，不代表 8 vCPU/16 GB 目标服务器已通过 30 分钟容量门禁。

`POC-005` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`64 passed, 2 skipped`，覆盖率 `85.50%`；Ruff、45 个 Python 文件格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，当前 Windows 未安装 Docker；两者由 PR CI 复核。

PR #10 CI 结果：PostgreSQL 17 环境 `66 passed`，覆盖率 `85.50%`；Ruff、45 个 Python 文件格式、迁移升级/漂移、Web、H5 `8 passed` 和 Compose/容器检查全部通过。真实书籍固定集不存在，自动化绿灯只证明几何策略和回退可重复，不代表拆分率、顺序或文字去弯曲质量达到 v1.4 指标。

`POC-004` 提交前全量检查：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`53 passed, 2 skipped`，覆盖率 `84.35%`；Ruff、43 个 Python 文件格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过，当前 Windows 未安装 Docker；两者由 PR CI 复核。

PR #9 CI 结果：PostgreSQL 17 环境 `55 passed`，覆盖率 `84.35%`；Ruff、43 个 Python 文件格式、迁移升级/漂移、Web、H5 `8 passed` 和 Compose/容器检查全部通过。真实试卷固定集不存在，自动化绿灯只证明保守边界和回退逻辑可重复，不代表试卷检出召回率或印刷内容保持率达到 v1.4 指标。

`POC-003` 专项检查已执行：

```text
python -m ruff check services/worker/app/vision.py services/worker/tests/test_vision.py tools/evaluate_perspective.py tests/test_perspective_evaluation.py
python -m ruff format --check services/worker/app/vision.py services/worker/tests/test_vision.py tools/evaluate_perspective.py tests/test_perspective_evaluation.py
python -m pytest services/worker/tests/test_vision.py tests/test_perspective_evaluation.py -q
```

专项结果：Ruff 与格式检查通过，透视处理和评估器 `8 passed`。

提交前全量检查已执行：

```text
python -m ruff check services migrations tests tools
python -m ruff format --check services migrations tests tools
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
git diff --check
```

本地结果：`41 passed, 2 skipped`，覆盖率 `82.81%`；Ruff、格式、迁移漂移、当前数据库版本、H5 `8 passed`、JavaScript 语法和差异检查均通过。两项 PostgreSQL 专属测试按本地环境预期跳过。当前 Windows 未安装 Docker。

PR #8 CI 结果：PostgreSQL 17 环境 `43 passed`，覆盖率 `82.81%`；Ruff、格式、迁移升级/漂移、Web、H5 `8 passed` 及 Compose/容器检查全部通过。真实数据集不存在，因此自动化绿灯只证明评估框架可运行，不代表文档透视真实可用率已达到 `95%`。

最近已验证的合并基线仍为 POC-002 PR #7：

```text
python -m ruff check services migrations tests
python -m ruff format --check services migrations tests
python -m pytest --cov=services --cov-report=term-missing --cov-fail-under=77
python -m services.api.app.migrations drift
python -m services.api.app.migrations check
node --check apps/h5/app.js
node --check apps/h5/camera.js
node --check apps/h5/resumable-upload.js
node --test apps/h5/tests/*.test.js
node --check apps/admin-web/app.js
docker compose --env-file .env.example -f deploy/compose/docker-compose.yml config
git diff --check
```

验证结果：

- Ruff 与格式检查通过，39 个 Python 文件纳入检查。
- H5 相机与弱网专项自动测试 `8 passed`。
- 全量本地测试 `36 passed, 2 skipped`，应用代码覆盖率 `82.80%`，达到 `77%` 门禁。
- 本地跳过的两项 PostgreSQL 测试已由 PR CI 的 PostgreSQL 17 服务执行并通过。
- Alembic 元数据漂移检查通过：`No new upgrade operations detected`。
- 当前本地数据库版本检查通过。
- H5 应用、相机模块、续传模块和管理后台 JavaScript 语法检查通过。
- `git diff --check` 通过。
- 当前 Windows 未安装 Docker；PR CI 的 Compose 语义检查已通过。
- PR CI 通过：PostgreSQL 环境 `38 passed`、覆盖率 `82.80%`，Node.js 22 环境 H5 `8 passed`，Web 与 Compose/容器检查全部通过。

## 外部阻塞

| 门禁 | 状态 | 解除条件 |
|---|---|---|
| 公司 staging 与目标主机负载 | 阻塞 | 提供可隔离的数据库、数据目录和域名/端口 |
| 企业微信真实身份与手机号 | 等待人工验收 | 提供 CorpId、AgentId、Secret、可信域名及测试成员权限 |
| H5 真机与真实弱网 | 等待人工验收 | 提供至少 3 款 Android 手机、2 个企业微信版本、Wi-Fi/4G/5G 切换、系统分享目标和屏幕阅读器条件 |
| 文档透视真实样本 | 等待人工验收 | 提供已授权、脱敏且具有人工期望标注的固定文档照片集 |
| 真实短信 | 等待人工验收 | 冻结供应商、签名、模板、密钥和限频参数 |
| Android 正式签名分发 | 等待人工验收 | 冻结包名、签名资产和 GitLab 发布位置 |
| Android CameraX 真机 | 等待人工验收 | 提供目标设备，验证权限、后摄、方向、对焦、曝光、质量阈值、中断恢复和连续原图完整性 |
| Android 离线续传真机 | 等待人工验收 | 在目标设备和 staging 验证 Wi-Fi/蜂窝切换、飞行模式、进程强杀、令牌过期、服务端重启、大文件和磁盘不足 |
| iOS 真机与 App Store | 等待人工验收 | 冻结 Team、Bundle ID、地区、隐私与支持 URL，并使用 Mac 完成门禁 |

外部阻塞不会阻止 Mock、契约、算法、客户端和本地部署工作；模拟结果不得把上述门禁改为“完成”。

## 已完成证据

| 工作包/基线 | 提交 | 验证摘要 |
|---|---|---|
| 初始平台基线 | `f35b742` | 初始 API、Worker、客户端骨架、CI 与部署布局 |
| 中文文档规范 | `13903b3` | 中文说明文档和提交规范 |
| 分片上传与断点续传 | `38df17a` | 7 项测试通过；分片、哈希、幂等和隔离 |
| 文档透视校正 POC | `1d5a9d6` | 10 项测试通过；OpenCV 透视和保守回退 |
| 长任务治理 | `dde779e` | Ruff、格式、10 项 Pytest、H5、后台及 Compose CI 通过；PR #1 已合并 |
| 版本化数据库迁移 | `91ff720` | 本地 15 项通过；PR CI 17 项通过且 PostgreSQL 测试无跳过；PR #2 已合并 |
| API 路由职责拆分 | `f711e47` | 入口缩减至 56 行；PR CI 19 项通过且覆盖率 81%；PR #3 已合并 |
| 隔离测试与契约基线 | `11d0a1c` | PR CI 21 项通过、覆盖率 77.67%；隔离、快照与漂移门禁通过；PR #4 已合并 |
| 现有资源越权矩阵 | `1b0e3dd` | PR CI 25 项通过、覆盖率 80.97%；角色、IDOR、审计、Web 与 Compose/容器检查通过；PR #5 已合并 |
| 企业微信可信身份 POC | `a766af5` | PR CI 38 项通过、覆盖率 82.80%；适配器、Mock、账号决策、Web 与 Compose/容器检查通过；PR #6 已合并，真实租户待人工验收 |
| H5 相机与弱网 POC | `fd82c30` | PR CI API 38 项、H5 8 项通过，覆盖率 82.80%；相机兜底、续传、Web 与 Compose/容器检查通过；PR #7 已合并，真机弱网待人工验收 |
| 文档透视评估框架 | `2371cd7` | PR CI 43 项通过、覆盖率 82.81%；授权清单、指标、性能报告、Web 与 Compose/容器检查通过；PR #8 已合并，真实数据集指标待人工验收 |
| 基础试卷净化 POC | `6ff0f2a` | PR CI 55 项通过、覆盖率 84.35%；三级建议、保守净化、原图回退、Web 与 Compose/容器检查通过；PR #9 已合并，真实试卷指标待人工验收 |
| 双页拆分与去弯曲 POC | `6a6301a` | PR CI 66 项通过、覆盖率 85.50%；非中心书脊、阅读顺序、去弯曲回退、Web 与 Compose/容器检查通过；PR #10 已合并，真实书籍指标待人工验收 |
| 16 用户混合负载工具 | `4fa566a` | PR CI 77 项通过、覆盖率 85.50%；16 会话 Mock、目标防护、资源门禁、Web 与 Compose/容器检查通过；PR #11 已合并，目标服务器 30 分钟正式容量仍阻塞 |
| 统一身份模型 | `d097a17` | PR CI 82 项通过、覆盖率 87.24%；用户主体、登录身份、已验证手机号、旧库回填、降级、Web 与 Compose/容器检查通过；PR #12 已合并 |
| 手机号数据保护 | `9041001` | PR CI 91 项通过、覆盖率 87.18%；AES-GCM、版本化 HMAC、旧数据状态、轮换、迁移、Web 与 Compose/容器检查通过；PR #13 已合并 |
| 短信验证码服务 | `4a1e8fc` | PR CI 96 项通过、覆盖率 87.53%；一次性挑战、尝试上限、并发限频、Provider、迁移、Web 与 Compose/容器检查通过；PR #14 已合并，真实短信待人工验收 |
| 企业微信 OAuth 登录 | `05141aa` | PR CI 在 PostgreSQL 17 环境 99 项通过、覆盖率 87.32%；浏览器绑定 state、可信手机号唯一绑定、短信回退、迁移、Web 与 Compose/容器检查通过；PR #15 已合并，真实租户待人工验收 |
| 账号合并与冲突处理 | `5f07000` | PR CI 在 PostgreSQL 17 环境 103 项通过、覆盖率 87.36%；强身份、canonical user、资源与文件补偿、幂等、跨用户阻断、不可变审计、Web 与 Compose/容器检查通过；PR #16 已合并 |
| 设备会话与刷新令牌 | `0d617f2` | PR CI 在 PostgreSQL 17 环境 109 项通过、覆盖率 87.75%；短期访问令牌、一次性刷新轮换、重放整族吊销、设备撤销、旧客户端兼容、迁移、Web 与 Compose/容器检查通过；PR #17 已合并 |
| 账号删除与手机号隔离 | `495576b` | PR CI 在 PostgreSQL 17 环境 117 项通过、覆盖率 86.86%；强验证、7 天冷静期、可重入清理、文件补偿、30 天复用隔离、并发 Worker、Web 与 Compose/容器检查通过；PR #18 已合并 |
| 完整管理与审计 | `5d73afa` | PR CI 在 PostgreSQL 17 环境 121 项通过、覆盖率 87.75%；角色层级、分页过滤、会话撤销、受控删除、失败审计、迁移、Web 与 Compose/容器检查通过；PR #19 已合并 |
| 页面版本与独立复核 | `7e501ff` | PR CI 在 PostgreSQL 17 环境 125 项通过、覆盖率 88.63%；原图保护、追加式结果、质量/旋转/复核、旧状态迁移、IDOR、Web 与 Compose/容器检查通过；PR #20 已合并 |
| 完整任务状态机 | `1f5094b` | PR CI 在 PostgreSQL 17 环境 130 项通过、覆盖率 89.00%；租约、心跳、过期抢占、指数退避、取消/重试、单结果幂等、IDOR、迁移、Web 与 Compose/容器检查通过；PR #21 已合并 |
| 基础 OCR 与安全命名 | `cff564c` | PR CI 在 PostgreSQL 17 环境 145 项通过、覆盖率 89.11%；固定离线适配、四方向融合、版本关联结果、敏感命名过滤、IDOR、迁移、Web 与 Compose/容器检查通过；PR #22 已合并，真实模型指标待人工验收 |
| JPG/PDF 多格式导出 | `4e10b2e` | 本地 143 项通过、覆盖率 88.46%；PR CI 在 PostgreSQL 17 环境 148 项通过、覆盖率 88.75%；多页制品、三档质量、当前 OCR 文本层、过期回退、IDOR、账号合并/删除、迁移、Web 与容器检查通过；PR #23 已合并 |
| 文件生命周期管理 | `d8025b8` | 本地 149 项通过、覆盖率 88.23%；PR CI 在 PostgreSQL 17 环境 154 项通过、覆盖率 88.49%；鉴权下载、Range/X-Accel、上传取消、过期回收、项目清理重试、IDOR、迁移、Web 与容器检查通过；PR #24 已合并 |
| v1 API 契约冻结 | `4a76fb9` | 本地 152 项通过、覆盖率 88.28%；PR CI 在 PostgreSQL 17 环境 157 项通过、覆盖率 88.55%；双快照兼容检查、破坏性反例、版本响应头、Web 与容器检查通过；PR #25 已合并 |
| H5 登录与企业微信绑定 | `10ab33e` | 本地 152 项通过、覆盖率 88.29%，H5 17 项通过；PR CI 在 PostgreSQL 17 环境 157 项通过、覆盖率 88.56%；设备会话、刷新轮换、企微回调、短信绑定、兼容契约、Web 与容器检查通过；PR #26 已合并 |
| H5 拍摄入口 | `3cd4511` | 本地 152 项通过、覆盖率 88.29%，H5 20 项通过；PR CI 在 PostgreSQL 17 环境 157 项通过、覆盖率 88.56%；后摄、ImageCapture/帧回退、后台释放、系统相机、预览、Web 与容器检查通过；PR #27 已合并 |
| H5 页面编辑 | `1868eea` | 本地 156 项通过、覆盖率 88.28%，H5 25 项通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%；四角裁切、滤镜、旋转、页序、复核、IDOR、OpenAPI、Web 与容器检查通过；PR #28 已合并 |
| H5 项目恢复与文件分享 | `a43deb9` | 本地 156 项通过、覆盖率 88.28%，H5 29 项通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%；项目恢复、任务轮询、导出、鉴权下载、Web Share 回退、Web 与容器检查通过；PR #29 已合并 |
| H5 双语与浏览器 E2E | `6d20db5` | 本地 156 项通过、覆盖率 88.28%，H5 33 项、Chromium E2E/axe 3 项通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%；中英文、键盘编辑、真实模块加载、分享回退、无障碍、Web 与容器检查通过；PR #30 已合并 |
| Android 分层工程与 API 客户端 | `41bf07d` | 本地后端与 H5 回归通过；PR CI 在 PostgreSQL 17 环境 161 项通过、覆盖率 88.54%，Android JDK 17/Gradle 8.9/SDK 35 的网络与仓储测试、应用单元测试和 Lint 通过，Web 与容器通过；PR #31 已合并，模拟器和真机待后续门禁 |
| Android 身份与用户分区缓存 | `60bac1e` | 本地后端 156 项、H5 33 项和 Chromium E2E/axe 3 项通过；PR #32 最终头两套 CI 的 API、Web、容器与 Android 共 8 项通过；首轮 Room/Kotlin 元数据失败已升级 Room 2.7.2 后修复，真实 Keystore、短信和真机待人工验收 |
| Android CameraX 手动拍摄 | `b238992` | 本地后端 156 项、H5 33 项和 Chromium E2E/axe 3 项通过；PR #33 最终头两套 CI 的 8 项检查通过，Android 执行拍摄状态机/质量评估、应用编译与 Lint；相机真机门禁待人工验收 |
| Android 离线队列与分片续传 | `9b19932` | PR #34 最终头两套 CI 的 8 项检查通过；Room v1→v2 迁移、用户隔离队列、WorkManager、服务端确认分片续传、应用编译和 Lint 通过；真实弱网、进程强杀和 staging 重启待人工验收 |
| Android 编辑、分享与账号删除 | `649b441` | PR #35 最终头两套 CI 的 8 项检查通过；页面编辑、鉴权导出、受限 FileProvider 分享、删除冷静期与用户级本地清理通过；真机分享、删除并发和真实短信待人工验收 |
| Android 安全更新 | `4676b90` | PR #36 最终代码头两套 CI 的 8 项检查通过；ECDSA 清单、受控下载、APK 身份/哈希/证书复检、每日检查、Robolectric、应用编译和 Lint 通过；正式签名分发与真机安装/回滚待人工验收 |
| iOS 可复现工程 | `51b182c` | PR #37 最终代码头两套 CI 的 10 项检查通过；固定 XcodeGen/Xcode、工程生成、双语资源、Simulator 应用编译和 Swift 单元测试通过；正式 Bundle ID、签名、真机与发布待后续门禁 |
| iOS 身份、Keychain 与网络 | `284da8e` | PR #38 最终代码头两套 10 项检查通过；注册登录、会话恢复、Keychain、设备头、刷新轮换、用户缓存隔离和双语界面的 Simulator 测试通过；真实短信与 Keychain 真机行为待人工验收 |
| iOS AVFoundation 与 Vision 拍摄 | `2449395` | PR #39 最终代码头两套 10 项检查通过；状态机、质量阈值、Vision 矩形、iOS 17 旋转角、原图与方向证据的 Simulator 编译/测试通过；真实相机与阈值仍待人工验收 |

## 下一步

1. 等待 PR #39 最终文档提交的两套 CI 通过后 squash 合并，并同步主线提交证据。
2. 创建 `codex/ios-004-background-upload` 分支，实现用户分区本地队列、允许范围内的后台恢复和服务端确认分片续传。
3. Keychain、相机、后台执行、Apple Team、正式 Bundle ID、签名、真机和发布继续保留外部门禁，不以 Simulator 结果替代。
