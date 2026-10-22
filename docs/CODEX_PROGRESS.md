# SmartScan 长任务进度

更新时间：2026-10-22

## 当前断点

| 项目 | 当前值 |
|---|---|
| 当前里程碑 | M8 可选视觉 AI 业务接入 |
| 当前工作包 | `AND-AI-001` Android AI 接入 |
| 工作包状态 | 进行中：公共 API、仓储、Compose 产品闭环和自动测试已实现；等待最终代码头 CI、PR 与合并 |
| 当前分支 | `codex/and-ai-001-android-ai`（从已验证的 AI-009 提交堆叠，待 #66 合并后以 `main` 为 PR 基线） |
| 最后验证基线 | `24051e3`（AI-009 PR #66 最终文档头；PR 五项与重复 push 五项的实际作业全部成功，GitHub 事故仍延迟一个重复 Web Check Run 的汇总） |
| 工作包提交 | `ed48714`（Android AI 闭环）、`d3b7d3a`（构造参数兼容）、`94f533e`（降级语义）及当前待提交的自审/中文文档 |
| PR | 尚未创建；先使用 push CI 迭代 Android 固定工具链，#66 合并后创建独立中文 PR |
| 下一工作包 | `IOS-AI-001`：iOS 项目授权、建议、进度和候选选择 |

## 当前工作包进展

- Android `SmartScanApi` 新增能力、项目设置、页面候选创建/列表和接受/放弃接口；版本化页面下载支持来源基础版本只读预览。所有请求继续复用现有 Bearer/设备头拦截器，移动端不建立或保存部署连接配置。
- 仓储把不可信候选收敛为分类、方向、标题、页码、公式、表格和版面七类有限字段，最多读取 40 个复杂块、每表 200 个单元格、每条 512 字符。网络 DTO 不解析部署证据；UI 在不确定网络失败后复用同一幂等键，成功后才轮换。
- Compose 项目工作区先展示固定传输说明，用户显式同意后才开启；支持通用建议/复杂 OCR、运行态轮询、候选对比、接受/放弃、过期禁用和基础/当前版本切换。模拟模式持续标注，复杂 OCR 明确不修改像素；AI 不可用只影响面板，已开启项目仍可关闭，基础编辑/导出保持可用。
- 新增网络契约、仓储边界和工作区纯状态测试；双语资源 XML、Android 发布配置和差异空白检查通过。本机没有 JDK、Gradle 或 Android SDK，首个 push `39798801780` 通过 GitHub 固定工具链发现新增字段插入构造参数中间的源兼容失败；`d3b7d3a` 将字段移至末尾后，运行 `39799346910` 的 Android 单元测试、应用编译、Lint 与无密钥 Release 构建通过。最终自审代码头仍待 CI。
- AI-009 的最终 PR 运行 `39794719321` 与 push 运行 `39794712396` 的五类作业实际全部成功；GitHub 官方事故使后者 Web Check Run 汇总仍显示进行中，PR #66 暂为 `unstable`，未绕过保护规则。AND-AI-001 因与该外部门禁独立而按计划先在堆叠分支继续。

- AI-009 已让专用 AI Worker 消费 `complex_ocr` 的 `ocr_formula`，请求公式、表格和版面三类块并使用 4096 输出上限；仍复用稳定子任务 ID、内部检查点、安全媒体、租约重试和失败降级。候选完成前后均不修改页面或导出。
- 用户接受仍绑定当前活动版本的候选时，API 会再次校验结构化块，把归一化坐标映射到源图片像素并写入版本绑定 OCR 详情；PDF 仅在此后采用文字层。专项验证活动版本、`PageResult` 数量及图片 SHA-256 全部不变，非法存储候选返回 `422` 且不修改页面。
- H5 增加通用建议/公式与复杂版面 OCR 类型选择，按类型隔离当前候选，并展示长度受限的公式、表格和版面文字；中英文、键盘名称、Provider 字段隐藏和 axe 继续受测试保护。本机 Mock 返回明确含“模拟”标识的三类可重复块，不读取媒体或计入真实验收。
- 本机一键试用实际启动 API、AI 网关、AI Worker、CPU Worker 和 H5，在固定 `demo` 账号下完成“项目授权→Mock `complex_ocr`→公式/表格/版面候选→接受→PDF 文字层导出”；证据为 `execution_mode=mock`、三类块齐全、活动图片版本不变、OCR `ready`、导出采用一页文字层。随后停止全部五个托管进程并保留隔离数据。
- 完整本地门禁通过：Ruff 与 162 个 Python 文件格式、iOS/Android 发布草稿、两套 AI Schema、OpenAPI 当前/上一代兼容、迁移漂移、H5/管理后台 JavaScript 语法和差异空白均通过；Python `453 passed, 7 skipped`、覆盖率 `87.81%`，H5 单元 `45 passed`，Chromium E2E/axe `8 passed`。一次联合回归先因误写不存在的 `tests/test_ai_media_security.py` 而未收集测试，纠正为实际 `tests/test_ai_secure_media.py` 后相关 `160 passed`；7 项跳过仍是既有 PostgreSQL/Docker/真实主机外部门禁。
- 代码提交 `0d601d5` 的 PR 工作流 `39792248750` 已完成 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器五项检查，全部通过。重复 push 工作流 `39792163156` 的 API/Web/Android/容器通过，iOS 每个内部步骤均成功但 Check Run 汇总较晚收敛；没有用该重复运行替代 PR 五项门禁。当前证据提交只更新中文状态文档，仍需在同一 PR 完成 CI 后合并。

- H5-AI-001 已由 [PR #64](https://github.com/j4meshub/SmartScan/pull/64) 合并到主线，中文 squash 提交为 `725e0ad`；最终 push `39773633246` 与 PR `39773639990` 的 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过。
- DEVX-002 将既有中文启动器扩展为一次启动 API、AI 网关、AI Worker、CPU Worker 和 H5。默认 Provider 是不读取媒体、不访问外网的确定性 Mock，七类任务都通过现有结构化结果校验；能力接口、H5 双语徽标和持久化证据明确区分 `mock` 与 `provider`，生产环境禁止 Mock。
- 可选真实模式从被 Git 忽略的 `.smartscan-trial/ai-provider.local.json` 读取 OpenAI Chat/Responses 配置。启动器拒绝非 HTTPS/IP 地址、未知字段、过宽或非受控私网；Key 只注入 AI 网关进程，不写入运行配置、状态、日志或客户端。真实模型不能访问签名 HTTPS 媒体地址时继续作为外部门禁。
- 真实本机编排确认五个托管角色均运行，并使用自动创建的 `demo` 账号完成“项目授权→Mock AI 候选→用户接受”；候选证据为 `mock`。停止命令关闭全部五个角色并保留试用数据。专项 Python/OpenAPI `136 passed`；最终仓库级 Python `450 passed, 7 skipped`、覆盖率 `87.82%`，H5 单元 `44 passed`，Chromium E2E/axe `7 passed`；Ruff、162 个 Python 文件格式、迁移漂移、OpenAPI 当前/上一代兼容、两套 AI Schema、H5/管理后台 JavaScript 语法和差异空白均通过。首次全量回归只因 AI 网关健康响应新增脱敏 `execution_mode` 而旧精确字典断言失败，补齐契约断言后原命令全量通过；7 项跳过仍为既有 PostgreSQL/Docker/真实主机外部门禁。
- DEVX-002 代码提交为 `b2696c0`。首次 push `39779325414` 的 API/Web/Android/容器成功，但 iOS Simulator 长时间不收敛；同提交 PR `39779395427` 五项全部成功。取消请求同样未及时收敛后，强制取消旧 push，并以中文空提交 `59fe5e6` 原样重触发，没有修改或跳过测试。新代码头 push `39781073863` 与 PR `39781082752` 的 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过。

- AI-008 已由 [PR #63](https://github.com/j4meshub/SmartScan/pull/63) 合并到主线，中文 squash 提交为 `5ebee7f`；最终 push `39768108559` 与 PR `39768115196` 的 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过。
- H5 项目工作区新增固定传输说明与项目级 AI 开关；能力未配置时不能开启或发起建议，但页面编辑、基础预览和导出保持可用。每次建议使用安全随机幂等键并绑定当前活动页面版本，页面切换后只展示同页状态。
- 分类、方向、标题和页码候选以业务字段和置信度对比，不读取或显示 Provider ID、模型、URL 或 Key。用户可以接受或放弃仍有效的候选；接受导致确定性旋转生成新版本时，可在来源基础版本和当前版本之间只读回看，不把普通文档伪装成 AI 图像。
- H5 中英文词条、键盘焦点、ARIA 状态区和移动端布局已补齐。本地 `node --check` 通过，H5 单元测试 `44 passed`；Chromium E2E/axe `6 passed`，覆盖授权、建议、候选对比、接受、放弃、基础版本回看和 AI 不可用降级。仓库级 Python `431 passed, 7 skipped`、覆盖率 `87.76%`；Ruff、161 个 Python 文件格式、迁移漂移、OpenAPI 当前/上一代兼容、两套 AI Schema、Android/iOS 发布草稿、H5/管理后台 JavaScript 语法及差异空白均通过。7 项跳过仍是既有 PostgreSQL/Docker/真实主机外部门禁。代码头 push `39771891339` 与 PR `39771941635` 的 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过。

- AI-007 已由 [PR #62](https://github.com/j4meshub/SmartScan/pull/62) 合并到主线，中文 squash 提交为 `8ba83d4`；最终 push `39762220996` 与 PR `39762226150` 的 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过。
- AI-008 新增独立 `worker-ai` 服务，只在 `ai` Profile 中启动并领取 `ai_enhancement`。`recommended` 请求按稳定子任务 ID 调用分类、方向、标题和书籍页码 Schema；每个完成结果按任务类型写入内部检查点，租约重试会跳过已完成项，处理中检查点不通过公共 API 暴露。
- Worker 重新核对项目授权、页面活动版本、媒体 SHA-256、网关任务身份和脱敏证据；部署配置用媒体前缀 SHA-256 与网关注册表绑定。非法证据、未配置、超时、网关离线或永久错误只结束可选任务，基础页面、预览与导出不受影响。
- 四类输出均先成为候选，不在 Worker 阶段修改页面或项目。用户接受仍有效的候选后，方向通过现有确定性旋转生成新页面版本，标题写入 `suggested_name` 而不覆盖用户标题，书籍页码写入与活动结果版本绑定的证据；分类保留为用户已接受的结构化证据，不自动切换整个项目模式。
- 本地完整门禁已通过：Ruff 与 161 个 Python 文件格式、迁移升级/漂移/版本、OpenAPI 当前/上一代兼容、两套 AI Schema、H5/管理后台 JavaScript 语法和差异空白均通过；Python `431 passed, 7 skipped`，覆盖率 `87.76%`；H5 `40 passed`。7 项跳过均为既有 PostgreSQL/Docker/真实主机外部门禁；当前 Windows 未安装 Docker CLI，新增 AI Profile 的动态 Compose 解析和镜像构建已由 PR 容器 CI 补证。AI-008 在合并前仍保持进行中。
- 自审发现首个 CI 仅解析新增 AI Worker，却只构建 AI 网关镜像；没有用 Compose 解析替代镜像门禁。提交 `a366f05` 将容器步骤扩展为同时构建 `ai-gateway` 与 `worker-ai`。最终代码头 push `39767143470` 与 PR `39767150166` 的 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过；两套容器作业均实际完成 AI 网关与专用 Worker 镜像构建。

- AI-006 已由 [PR #61](https://github.com/j4meshub/SmartScan/pull/61) 合并到主线，中文 squash 提交为 `ad61afb`；项目授权、版本绑定候选、任务取消/重试、接受/放弃、IDOR 和删除解绑成为 AI-007 的已验证基线。
- AI-007 新增迁移 `20261022_0024` 和 `ai_media_grants`：令牌由 `token_urlsafe(32)` 生成，数据库只存 SHA-256 摘要，并绑定单一增强任务、项目、页面、页面结果与源版本。读取会重验项目授权、任务状态、页面版本、路径、大小和哈希；关闭授权、换版、失败、取消及删除均撤销或清除。
- AI 网关在配置内部令牌后保护全部 `/v1/*` 接口，生产环境缺失令牌时失败关闭；Worker 网关客户端固定使用部署级 URL、Provider ID 与 Secret，禁止重定向并屏蔽上游正文。业务 API 和客户端均不接受或返回 Provider 配置、媒体令牌与内部网络信息，网关仍无公网 Nginx 路由。
- 新增 AI 专用领取入口，使用 `optional_enhancing` 租约并同步业务状态；基础 Worker 继续拒绝 `ai_enhancement`。AI-007 只建立安全执行边界，七类任务参数、候选汇总和确定性应用仍归 AI-008～AI-011，不把传输客户端误报为用户可用闭环。
- 完整本地门禁通过：Ruff 与 158 个 Python 文件格式、AI Schema、OpenAPI 当前/上一代兼容、空库升级、迁移漂移/版本检查和差异空白均通过；Python `422 passed, 7 skipped`，覆盖率 `87.64%`；H5 `40 passed`，H5/管理后台 JavaScript 语法通过。7 项跳过均为既有 PostgreSQL/Docker/真实主机外部门禁；本机没有 Docker CLI，Compose/Nginx 动态验证留给 GitHub 容器检查，静态测试已确认网关无公网端口且媒体桥不记录令牌路径。
- 补充专项明确验证项目删除和账号删除都会清除媒体授权，Provider 调用只允许关联处理中的同页同版本业务任务。PR 首个容器运行发现 Nginx `map` 正则量词花括号被解析为块起始；未绕过容器门禁，提交 `bbde50b` 移除该歧义并保留 API 长度失败关闭。修复后的 push `39760674288` 与 PR `39760681719` 中 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器共 10 项全部通过。

- 新增迁移 `20261022_0023`：项目保存 AI 开关、传输说明版本、授权人和授权时间；增强任务关联所有者、项目、页面、源结果版本、统一处理作业、结构化候选、模型证据和 Provider 聚合调用。页面结果新增可空源版本与来源证据，旧库默认保持 AI 关闭。
- 新增能力查询、项目 AI 设置、页面增强创建/列表和候选接受/放弃 API。创建必须使用当前页面版本和 16～100 位受限幂等键；未授权、跨用户、旧源版本、模式不匹配和键重用冲突均失败关闭并保留审计。
- `ai_enhancement` 已进入现有任务取消/重试边界，但基础 Worker 在 AI-007 前显式拒绝领取。页面新版本会使排队、处理或待确认候选过期并取消对应作业；接受只保存用户选择，不提前执行 AI-008 的标题、方向或页面确定性修改。
- 项目/账号删除会清除候选内容并显式解绑保留的脱敏 Provider 聚合记录；账号合并会迁移任务所有者、项目授权人和候选接受人。新增 IDOR、幂等、Worker 隔离、版本竞争、接受/放弃、删除解绑、空库/旧库迁移及回滚测试。
- 本地完整门禁通过：Ruff、154 个 Python 文件格式、迁移升级/漂移/版本、OpenAPI 当前/上一代兼容、两套 AI Schema 和差异空白均通过；Python `417 passed, 7 skipped`，覆盖率 `88.28%`；H5 `40 passed`，管理后台与 H5 JavaScript 语法通过。7 项跳过均为缺少本机 PostgreSQL/Docker/真实主机条件的既有外部门禁。
- 初次代码头的 push 工作流 `39750466182` 五项通过，但 PR 工作流 `39750474176` 的 iOS Simulator 在同一测试步骤长时间不更新，普通取消和强制取消均未收敛。未把相同提交的另一套绿灯替代该门禁；中文空提交 `df641d0` 原样重触发后，push `39752340384` 与 PR `39752345039` 的 API、Web、Android、iOS 和容器共 10 项全部通过。

- 已确认 M8 原计划缺少从 AI 网关到扫描业务的调用者、用户/项目/页面关联、候选版本持久化、接受流程和三端 UI；现有 H5“增强”仅为确定性本地图像滤镜，不是外部 AI。
- 修正版保持 `AI-001～AI-004` 完成、`AI-005` 等待人工验收，将 M8 总体恢复为进行中；M4～M6 明确为外部 AI 关闭时的三端核心产品，AI 产品能力由 M8 新工作包承接。
- 已锁定部署级共享 Provider、项目级显式授权、候选永不自动覆盖、H5 先验证后补齐原生端以及本机 Mock 默认/真实配置可选。个人 BYOK 和管理后台动态修改 Key 不在当前范围。
- `GOV-002` 只修订治理和架构事实，不实现数据库、接口或客户端行为；后续实现从 `AI-006` 独立分支开始。
- 本地 Markdown 链接、差异空白、Ruff 和 150 个 Python 文件格式检查通过；全量 Python `414 passed, 7 skipped`，覆盖率 `88.42%`。PR #60 初始代码头两套 API、Web、Android、iOS 和容器检查共 10 项全部通过。

- 新增根目录中文启动器 `SmartScan本机试用.cmd` 和 `tools/local_trial.py`：首次运行自动创建 `.venv`、安装 `dev,vision` 依赖，后台启动只监听回环地址的 API、CPU Worker 与 H5，并自动创建固定 `demo` 账号；后续启动根据依赖指纹复用环境。
- 试用数据库、扫描文件、运行密钥、PID 状态和日志全部隔离在 `.smartscan-trial/`。停止按 PID 与命令行双重核对后关闭三个进程并保留数据；清理要求中文二次确认、验证精确目录后只删除试用区，明确保留 `.venv`。
- 真实首次启动发现 CORS 复杂字段必须使用 JSON 数组，并发现 Python 3.14/Windows 不支持 `os.kill(pid, 0)` 的存活探测；分别改为 JSON 编码和 Windows 只读进程句柄检查，没有放宽 PID 复用防护。
- 本机端到端已验证自动安装、API/H5 就绪、自动注册、真实登录、停止后 `8000/8080` 端口关闭、数据保留重启、再次登录和清理后仅保留 `.venv`。专项 `6 passed`；仓库级 Python `414 passed, 7 skipped`，覆盖率 `88.42%`，Ruff、150 个 Python 文件格式和差异空白检查通过。
- PR #59 代码头 `25001f4` 的工作流 `39711732455` 已完成 API、Web、Android、固定 Xcode 16.4 iOS Simulator 和容器五项检查，全部通过；DEVX-001 完成后恢复固定数据集、公司服务器和签名发布等外部门禁断点。

- 新增只允许人工触发的 `iOS 正式发布` 工作流：要求 `main` 历史上的受保护 `ios-vX.Y.Z-build.N` 标签、`ios-release` Environment 审批和实际 Xcode 26+ 证据；默认 `validate-only`，只有显式选择 `upload-testflight` 才产生 Apple 外部副作用。
- 正式参数由 Environment Variables 注入，P12、描述文件、App Store Connect `.p8` 与审核账号由 Secrets 注入。脚本使用临时钥匙串，完成发行签名、Archive、IPA 导出和清理；不把正式值写回 `project.yml`，Artifact 也不保存 IPA 或密钥材料。
- 新增实包校验器，核对 Bundle、版本、构建号、Team、精确 App ID、发行身份、描述文件类型/有效期、后台任务标识、三个 HTTPS 地址、Archive/IPA 描述文件一致性、`codesign`、Xcode 门禁、IPA SHA-256 与大小。合成归档及发布准备专项 `21 passed`；全量 Python `408 passed, 7 skipped`、覆盖率 `88.42%`，H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、148 个 Python 文件格式、迁移漂移、OpenAPI 当前/上一代兼容、AI Schema、Android/iOS 发布草稿、JavaScript 语法和差异检查均通过。本机没有 Bash/Xcode，Shell 语法和真实 Simulator 由 GitHub Runner 补证。
- 首次推送的发布工作流运行 `39682892179` 在解析阶段失败且没有启动作业：作业级 `env` 不能读取 `runner.temp`。没有删除报告门禁或改用仓库目录；修复提交 `c79f89b` 将路径限定在归档步骤，并以官方 actionlint 复验两个工作流零报错。
- 修复后的 push 工作流 `39683400628` 与 PR 工作流 `39683405368` 共十项全部通过：API 在 PostgreSQL 17 完成全量回归并由 Ubuntu Bash 校验归档脚本语法，Web 完成 Chromium E2E，Android 完成单元/Lint/Release 组装，iOS 在固定 Xcode 16.4 Simulator 编译和测试，容器恢复回环同步通过。正式 `macos-26` 签名工作流仍需真实 Environment、受保护标签、截图和 Secret，因此没有被普通 CI 或合成制品冒充执行。
- REL-002 已由 PR #57 合并到主线，中文 squash 提交为 `c61fceb`；最终文档头 push 工作流 `39684567201` 与 PR 工作流 `39684574041` 共十项全部通过，合并后的主分支工作流 `39685863787` 五项再次全部通过。GitHub API 已确认仓库为公开状态，公开 Runner 已恢复，不再把额度作为当前阻塞项。
- REL-001 已由 PR #56 合并到主线，中文 squash 提交为 `c070826`；主分支工作流 `39679501026` 的 API、Web、Android、iOS 和容器五项全部通过。真实 GitLab、正式 Android 密钥、无凭据下载、真机升级与数据保留仍保持人工门禁。

以下保留已合并 REL-001 的近期证据：

- Android `versionCode`/`versionName` 改为流水线属性注入；正式 APK keystore 仅从四个完整环境变量装配，部分配置直接失败。正式签名启用 APK Signature Scheme v2/v3，不把 keystore、密码或私钥写入仓库。
- GitLab 仅允许受保护的 `android-vX.Y.Z` 标签进入正式流水线。构建前检查生产 HTTPS API、同源 Pages 清单/签名地址和 P-256 公钥；构建后以 `apkanalyzer`、`apksigner` 和流式 SHA-256 检查实包，并要求至少一个同包名、同证书、低版本的上一稳定 APK。
- 每个版本的 APK、原始清单、独立签名和脱敏报告上传到不可变 Generic Package 路径，Pages 只发布已复验的 `latest.json` 与 `.sig`。人工回滚作业只能原样恢复与旧 APK 匹配的已签名频道；已升级设备必须用更高 `versionCode` 前滚修复。
- 发布校验专项 `15 passed`；全量 Python `402 passed, 7 skipped`、覆盖率 `88.42%`，H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、146 个 Python 文件格式、迁移漂移、OpenAPI 当前/上一代兼容、AI Schema、iOS/Android 发布草稿、JavaScript 语法、GitLab YAML 解析和差异检查均通过。测试使用伪 APK 元数据与临时 ECDSA 密钥，只证明失败关闭逻辑；正式 GitLab 项目、固定构建镜像、受保护变量、无凭据下载、上一稳定真包和目标真机升级仍待人工验收。
- 代码头 push 工作流 `39676941097` 与 PR 工作流 `39677124080` 的 API、Web、Android、iOS 和容器共十项全部通过。Android Runner 实际完成现有单元/Lint 和新增无密钥 Release 变体组装，API 在 PostgreSQL 17 完成全量回归与发布草稿门禁，固定 Xcode 16.4 Simulator、Chromium 和备份恢复容器回环同步通过。
- OPS-004 已由 PR #55 合并到主线，中文 squash 提交为 `73a8019`；主分支工作流 `39671462319` 五项全部通过。真实异机仓库、定时任务、告警、RPO/RTO 和恢复清理仍保持人工门禁。

以下保留已合并 OPS-003 的近期证据：

- OPS-003 已由 PR #54 合并到主线，中文 squash 提交为 `87f04a9`；主分支工作流 `39662004298` 的 API、Web、Android、iOS 和容器五项全部通过，公开仓库 Runner 已恢复。

- 新上传按磁盘固定预留、最小可用比例、全局未接收上传预留和用户目录实际占用失败关闭；完整组装额外预留一份整文件，队列高水位拒绝完成但保留可重试上传。兼容单页上传、书籍缺页补扫和单侧重拍同样在写盘前执行磁盘、用户配额和队列门禁；下载、取消与清理不被新写入保护阻断。
- Worker 在清理任务之后检查磁盘再领取任务；PostgreSQL 用户级 advisory lock 与任务行锁共同限制每用户活跃 CPU 任务，避免两个 Worker 各自放行。迁移 `0022` 保存不含用户数据的空闲/忙碌心跳，任务租约仍是处理真实性来源。
- 新增默认关闭且不进入 OpenAPI 的 `/internal/metrics`，要求独立 Bearer Token；API 多进程请求/延迟、上传、数据库、队列、Worker、磁盘、审计、页面复核和 AI 指标均避免用户与对象高基数标签。公网 Nginx 不代理该路径。
- 新增显式 `monitoring` Profile：固定 digest 的 Prometheus、Alertmanager 和只读 Node Exporter 均不发布主机端口；渲染器核对运行配置与 Token 文件、HTTPS Webhook、安全目录和拒绝覆盖。CI 使用固定版本官方 `promtool`、`amtool` 校验配置与规则，并解析组合 Compose。
- OPS-003 容量、指标、任务和书籍联合回归 `40 passed`；最终全量 Python `382 passed, 7 skipped`，应用代码覆盖率 `88.48%`；H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、138 个 Python 文件格式、迁移版本/漂移、OpenAPI 当前/上一代兼容、AI Schema、iOS 发布草稿、JavaScript 语法和差异检查均通过。
- 首次专项运行因本机缺少已声明的 `prometheus-client` 无法收集；安装项目依赖后继续。开发中先后发现 SQLite 心跳时区断言、既有项目创建状态码预期，以及一次容量调用误插入分片完成路径，均按真实语义修正并重跑，没有放宽生产门禁。自审补齐数据库和容量快照同时失败时指标仍可抓取，以及三条旧直接写入入口不得绕过保护的回归。
- 首轮代码头的 push `39656023475` 与 PR `39656089448` 容器作业发现渲染器按脚本执行时无法导入同目录校验模块，提交 `215744c` 增加双入口导入和真实子进程回归。第二轮发现官方镜像入口把工具名误当服务参数，提交 `3f23151` 显式选择 `/bin/promtool` 与 `/bin/amtool`。第三轮证明 `0600` 配置不能由不同 UID 读取，提交 `f9eee16` 让 CI 工具使用 Runner 非 root 文件所有者，并保留真实镜像 UID/GID 人工门禁。第四轮 `promtool` 进一步发现缺少生产路径 Token 挂载，代码头 `f061acb` 补齐只读 Token；均未删除或放宽配置、安全与语法校验。
- 代码头 push 工作流 `39657570069` 第 2 次运行与 PR 工作流 `39657579124` 的 API、Web、Android、iOS 和容器共十项全部通过：API 在 PostgreSQL 17 完成全量回归与迁移，容器作业实际运行 `promtool`/`amtool`、解析 monitoring Compose，并复验既有 Nginx/TLS 链路；Android 和固定 Xcode 16.4 Simulator 同步通过。push 首次运行仅 iOS 状态长期未收敛，同提交 PR iOS 已成功；原样重跑后五项全部成功，未将运行中状态冒充通过。
- 本机没有 Docker、Android SDK 或 Xcode；上述真实环境由 GitHub Runner 补证。公司服务器仍不可用，真实通知、故障注入、运行 UID/GID、阈值和 15 天保留未被本地夹具或 CI 标记为通过。

以下保留已合并 OPS-002 的近期证据：

- 新增主机 TLS Nginx 模板与失败关闭渲染器：只代理 staging 回环端口，启用 TLS 1.2/1.3、HTTP/2、短期 HSTS、认证限频、不含查询字符串的日志及上传/下载流式代理。
- 新增 TLS 材料离线校验：要求精确 staging SAN、证书/私钥匹配、当前有效且至少 14 天剩余、非 SHA-1/MD5 签名摘要和私钥 `0600`；安全摘要不包含私钥或证书正文。
- 容器 Nginx 启用 `sendfile`、公平分块、符号链接阻断和压缩类型边界；认证限频从错误保留 `/api` 前缀的正则 location 改为 `$uri` 空键映射，普通 API 不计数且 FastAPI 继续收到 `/v1/...`。
- 新增隔离容器集成链路：假 API 只产生 `X-Accel-Redirect`，真实 Web 镜像验证内部路径直访 `404`、完整下载、内部头不泄露、附件/ETag/私有缓存以及单区间 `206 Content-Range`。
- 新增 BBR 只读 procfs 快照、启用前后比较和按原值生成回滚配置；工具不执行 `modprobe`、`sysctl`、覆盖或删除。只有同一内核、BBR 可用/生效且 qdisc 为 `fq` 时才允许进入真实网络对照，核心验收始终保持未完成。
- OPS-002 Python 专项当前 `12 passed, 1 skipped`；全量 Python `369 passed, 7 skipped`，应用代码覆盖率 `88.67%`；H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、131 个 Python 文件格式、迁移漂移、OpenAPI 当前/上一代兼容、iOS 发布草稿、JavaScript 语法和差异检查均通过。
- 首轮提交的 push 工作流 `39642978300` 与 PR 工作流 `39642987687` 仅容器作业失败：真实 Nginx 为内部文件自动生成了基于修改时间和大小的 ETag，覆盖 API 提供的 SHA-256 强 ETag。没有放宽校验，修复提交 `91fbf61` 在内部文件 location 关闭自动 ETag 并显式转发上游强 ETag。
- 修复后的 push 工作流 `39643470449` 与 PR 工作流 `39643479528` 共 10 项全部通过：容器作业完成证书生成与校验、TLS 边缘配置渲染、真实 `nginx -t`、内部路径直访 `404`、完整下载和单区间 `206`；API 在 PostgreSQL 17 运行全量回归，Web、Android 和固定 Xcode 16.4 iOS Simulator 同步通过。公开仓库 Runner 已恢复，没有额度阻塞。
- 本机没有 Docker，Nginx/TLS 与 internal/Range 的容器证据来自 GitHub Runner。真实域名、可信证书、ACME 续期、防火墙、公网/手机链路、大文件和 BBR 前后指标没有被合成夹具或 CI 标记为通过。

以下保留已合并 OPS-001 的近期证据：

- 新增独立 staging Compose：目标服务器只拉取固定 digest 镜像，不含 `build`，不挂载仓库源码；PostgreSQL、API 和 Worker 使用独立数据网络，Nginx 只在主机回环独立端口暴露 Web 入口。
- PostgreSQL、业务数据和 OCR 模型必须位于 `/srv/smartscan/staging/` 下互不重叠的主机目录；严格模式可在 Linux 目标主机拒绝缺失目录、符号链接和解析后越界。
- 部署与运行 Secret 使用仓库外 `0600` 文件；应用继续使用 `SMARTSCAN_ENV=production`，显式迁移、基础 OCR 开启，短信、企业微信和外部 AI 在基线中关闭。
- 校验器拒绝生产式项目名、保留域名、特权/生产端口、可变或占位镜像、目录复用、仓库内 Secret、密码错配、自动迁移、开发验证码、Mock 服务和 CORS 错配；安全摘要不回显 Secret。
- staging 专项在 Windows 为 `19 passed, 1 skipped`，并使用真实应用 `Settings` 加载生产模式运行夹具；全量 Python `357 passed, 6 skipped`，应用代码覆盖率 `88.67%`；H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、格式、迁移漂移、API 兼容、JavaScript 语法和差异检查通过。本机没有 Docker，Compose 真实解析、Web 镜像构建以及 Android/iOS 回归由 GitHub Runner 补证。
- 首轮 push API 作业 `39634646303` 在 Linux 暴露严格测试的临时 Secret 文件仍为默认 `0644`，校验器按设计拒绝；没有放宽安全规则，修复为测试写入后显式设置 `0600`，并新增 POSIX 宽权限拒绝反例。修复提交 `31441eb` 的 push 工作流 `39635214962` 与 PR 工作流 `39635223887` 共 10 项全部通过：API 在 PostgreSQL 17/Linux 完成全量测试与权限反例，容器作业实际解析两份 Compose 并构建 staging Web 镜像，Web、Android 和固定 Xcode 16.4 iOS Simulator 均通过。
- 公司服务器、真实域名、镜像仓库与 digest、主机目录、Secret、模型、迁移和核心流程没有被本地夹具或 CI 标记为通过；OPS-001 保持“等待人工验收”。

以下保留已合并 AI-005 的近期证据：

- 新增默认离线的多系统评估器，用同一数据集比较基础 OCR、专业 OCR、公共 VLM 和自定义 VLM；评估器只导入本地运行 JSON，不自动启用 Provider 或发送媒体。
- 固定清单强制授权、脱敏、许可、同意依据、按 `source_group` 切分、文件与任务媒体 SHA-256/尺寸一致。运行结果必须完整覆盖 test 集，并固定模型、框架、提示词、适配器、配置、价格和数据政策版本。
- 七类结构化任务分别计算准确率和无依据声明，统一报告幻觉率、结构化成功率、P50/P95 延迟、平均/总成本及逐任务指标；阈值必须在清单中保存批准人与记录，不臆造 v1.4 未规定的通用数值。四类系统缺少任一类型时只能生成局部报告，总门禁固定关闭。
- JSON 和中文 Markdown 报告不包含图片、原始路径、原始模型输出、任务/页面 ID、媒体 URL、令牌或密钥。真实数据集目录、实际运行结果和报告均已加入 Git 忽略。
- 当前 AI 固定评估专项 `11 passed`；全量 Python `338 passed, 5 skipped`，应用代码覆盖率 `88.67%`；H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、123 个 Python 文件格式、AI 任务/评估 Schema 快照、OpenAPI 当前/上一代兼容、迁移升级/漂移、iOS 发布草稿、JavaScript 语法和差异检查均通过。本机没有 PostgreSQL 17、Android、Xcode 或 Docker，相关环境由 GitHub Runner 补证。
- 代码提交 `745d6d1` 的 PR 工作流 `39621101031` 五项全部通过，已在 PostgreSQL 17、Chromium、Android、Xcode 16.4 Simulator 和 Docker 环境补证。push 工作流 `39620899771` 的 API、Web、Android 和容器通过；iOS 完整日志显示编译、全部 Swift 单测和清理通过，但 GitHub 状态长时间未从 `in_progress` 收敛，取消接口称其已不在运行而重跑接口称其仍在运行。该平台状态异常不冒充绿色结论，最终文档头会触发新一轮两套工作流验证。
- 文档头提交 `e4f0f44` 重新触发 push 工作流 `39626063110` 与 PR 工作流 `39626069371`；API、Web、Android、iOS 和容器共 10 项全部通过，公开仓库 Runner 已完成最终补证。

以下保留已合并 AI-004 的近期证据：

- Provider 新增可配置网络超时、最多一次重试、独立并发/滚动一分钟频率/UTC 日费用上限、连续失败阈值和熔断冷却期；日限额必须覆盖一次最坏调用，金额以整数微美元计算。
- 熔断状态、半开单探针、360 秒调用租约、出站尝试和保守费用证据保存在 PostgreSQL。事务级 Provider advisory lock 防止两个 Uvicorn Worker 同时越过并发或费用门禁；进程崩溃后的过期租约会释放槽位并记录失败。
- `408`、`429`、`5xx`、DNS、超时和传输故障最多重试一次；凭据拒绝或未付费立即熔断。媒体摘要、SSRF 或响应安全门禁等本地错误不污染供应商连续失败；只有进入 HTTPS 发送阶段的尝试才计入费用和每分钟请求数。
- 脱敏数据库证据、JSON 运行日志和内部运行状态只记录 Provider、任务类型、随机调用 ID、稳定错误、次数、耗时、字节数和保守费用，不保存用户/任务/页面 ID、媒体 URL/令牌、密钥或模型原文。
- Alembic `0021` 新增三张 AI 可靠性表；AI 网关在开发环境自动迁移、生产仅检查版本，并等待 Compose `migrate` 完成后启动。AI/迁移专项 `141 passed`，覆盖一次重试、立即/阈值熔断、半开恢复、租约、并发、频率、费用、日志脱敏和迁移升降级。
- 首次全量门禁为 `323 passed, 5 skipped, 1 failed`：Alembic `fileConfig` 在同一进程执行迁移后禁用了已存在的 AI 可靠性 logger，导致专项单独通过但完整应用链路丢失脱敏日志。修正为 `disable_existing_loggers=False` 并增加回归测试；自审又补齐“重试被限频时仍累计原供应商失败”和“本地门禁拒绝不占半开探针”后，全量 Python `327 passed, 5 skipped`、覆盖率 `88.63%`。Ruff、119 个 Python 文件格式、迁移升级/漂移/版本和差异检查通过；H5 `40 passed`、Chromium E2E/axe `3 passed`，JavaScript 语法通过。
- 本机没有 Docker、Android SDK、XcodeGen 或 Xcode；PostgreSQL 17 迁移、Compose 解析/AI 网关镜像、Android 和 iOS 已由 PR 的真实 GitHub Runner 补证，没有以本地 SQLite 或静态检查替代。
- 提交 `1d7eb72` 的 push 工作流 `39611742874` 与 PR 工作流 `39611817771` 共 10 项全部通过：API 在 PostgreSQL 17 完成全量测试、`0021` 升降级和漂移检查；容器作业成功解析 Compose 并构建连接数据库的 AI 网关镜像；Web、Android 和固定 Xcode 16.4 iOS Simulator 编译/测试均通过。公开仓库 Runner 已恢复，没有再出现额度阻塞。

以下保留已合并 AI-003 的近期证据：

- Provider 和媒体目标不再接受调用方完整 URL：Provider 地址与任务路径来自启动配置，媒体只从最多 16 个固定 HTTPS 前缀中选择并追加不少于 128 位的不透明令牌。地址拒绝 IP 字面量、非 443 端口、凭据、查询、片段、转义和歧义路径。
- 每次调用解析 Provider 与媒体域名的全部 A/AAAA 结果，默认只接受公网；自定义 VLM 可显式声明窄范围受控网段。混合公网/私网、回环、链路本地、元数据、多播和保留地址失败关闭。
- HTTPS 套接字直接连接已验证 IP，TLS SNI、证书主机名和 Host 使用原始域名，关闭代理隧道和二次 DNS；任何 `3xx` 都拒绝，不跟随下一跳。
- 媒体引用核对 SHA-256、MIME、声明字节数和 30 秒～24 小时有效窗口；请求/响应按 Provider 限制，响应只接受有限、未压缩、非空的 `application/json`。网络证据不回显域名、IP、令牌、媒体 URL 或密钥。
- Compose AI 网关容器改为只读、删除全部 capabilities、启用 `no-new-privileges` 和受限临时目录；网关仍使用显式 `ai` Profile 且不经 Nginx 暴露。
- 初版专项首次运行 `92 passed`、4 项失败：两项旧 Provider 夹具缺少新增媒体前缀，一项 TLS 假上下文缺少标准属性，一项测试把 `SecretStr` 的掩码当成原令牌提交。修正夹具并完成安全自审反例后，AI-001～AI-003 联合专项 `107 passed`；没有放宽安全规则或跳过测试。
- 当前本地全量 Python `310 passed, 5 skipped`，应用代码覆盖率 `88.60%`；H5 `40 passed`、Chromium E2E/axe `3 passed`。Ruff、116 个 Python 文件格式、AI Schema 快照、OpenAPI 当前/上一代兼容、迁移升级/漂移/版本、JavaScript 语法、iOS 发布草稿和差异检查均通过。当前 Windows 没有 Docker，Compose 语义与加固后的 AI 网关镜像由 PR CI 补证。
- 提交 `26b9063` 的 push 工作流 `39602627492` 与 PR 工作流 `39602693538` 共 10 项全部通过：API 在 PostgreSQL 17 环境完成全量测试、迁移和 AI Schema 快照检查，Web 完成 Chromium E2E，Android 完成 Gradle 测试/编译/Lint，iOS 完成固定 XcodeGen、Xcode 16.4 Simulator 编译与单测；两套容器作业均成功解析加固后的 Compose 并实际构建 AI 网关镜像。

以下保留已合并 AI-001 的近期证据：

- AI-001 使用 `SMARTSCAN_AI_PROVIDERS` JSON 在启动时构建不可变注册表；专业 OCR、OpenAI Chat/Responses-compatible 和自定义协议分别选择明确适配器，重复 ID、危险字段和启用但缺少必要配置会启动失败。
- 默认三类 Provider 全部关闭；密钥只以环境变量名引用。脱敏状态只报告是否存在凭据，不返回引用名称或值；关闭的 Provider 拒绝读取密钥，缺少凭据的启用项保持不可用。
- AI 网关作为 Compose `ai` Profile 独立运行，不被 Nginx 暴露，API、Worker、H5、Android、iOS 和导出链路均不依赖它。配置检查不联网、不发送媒体。
- AI-001 当时只提供结构 HTTPS 校验，不把它描述成完整 SSRF 防护；DNS 重绑定、连接固定、重定向和媒体域名策略现由 AI-003 独立实现并验证。
- 当前本地证据：AI Provider 专项 `14 passed`；全量 Python `217 passed, 5 skipped`，应用代码覆盖率 `88.85%`；H5 `40 passed`、Chromium E2E/axe `3 passed`；Ruff、格式、OpenAPI 当前/上一代兼容、迁移升级/漂移/版本、JavaScript 语法、iOS 发布草稿和差异检查均通过。本机没有 Docker，Compose 语义和 AI 网关镜像构建已由 GitHub Runner 补证。
- 提交 `df18491` 的 push 工作流 `39588619030` 与 PR 工作流 `39588671467` 共 10 项全部通过：API 使用 PostgreSQL 17 完成全量测试和迁移，Web 完成浏览器 E2E，Android 完成 Gradle 测试/编译/Lint，iOS 完成固定 XcodeGen、Xcode 16.4 Simulator 编译与单测；两套容器作业均成功解析 Compose 并实际构建 AI 网关镜像。公开仓库 Runner 未再出现额度阻塞。

以下保留已合并 BOOK-003 的近期证据：

- BOOK-003 新增常见页码区域 OCR 证据和本地图像 dHash；阿拉伯/规范罗马页码、候选冲突、无页码和置信原因均与活动处理版本绑定，页面编辑会使旧证据失效，不以内部页序伪装印刷页码。
- 完整性报告从当前逻辑页动态计算缺页、重复、同号异内容冲突、倒序、缺侧、质量复核和补扫页码不匹配；人工决策单独保存，可确认不存在、保留两页、排除重复或重新打开。排除只影响成册快照，不删除原图。
- 新增缺页补扫接口和版本化 PDF 成册：补扫保存新不可变原图并重新进入 Worker；完全相同快照幂等复用，内容或选项变化生成下一修订并链接上一导出。
- H5、Android 和 iOS 已增加双语问题清单、印刷页码、补扫/决策/完成成册入口；OpenAPI 修订为 `2026-10-21.2`，三端消费矩阵保留增量兼容。
- 当前本地证据：全量 Python `203 passed, 5 skipped`，应用代码覆盖率 `88.55%`；H5 `40 passed`、Chromium E2E/axe `3 passed`；Ruff、格式、OpenAPI 当前/上一代兼容、迁移升级/漂移/版本、JavaScript 语法、iOS 发布草稿和差异检查均通过。
- 首轮 Runner 发现 PostgreSQL 布尔字段不能用整数 `1` 回填，以及 Android 跨模块可空属性不能直接智能转换；提交 `1ce99a6` 改用标准布尔字面量并先收窄局部值，迁移/书籍专项 `28 passed`。修复后的 push 工作流 `39583092124` 与 PR 工作流 `39583100067` 共 10 项全部通过：API 含 PostgreSQL 17 迁移与并发测试，Android 完成 Gradle 测试、应用编译与 Lint，iOS 完成固定 XcodeGen、Xcode 16.4 Simulator 编译和 Swift 单元测试。
- 固定数据集不少于 5 本书、1000 个逻辑页面和 300 次双页取景，重复阻止率 `>=98%`、明显连续缺页检出率 `>=95%`、目标真机与大书容量仍为人工门禁；自动化通过不代表真实指标通过。

以下保留已合并 BOOK-002 的近期证据：

- BOOK-002 已把 POC 双页拆分接入 Worker：一次不可变物理原图可生成左右两个逻辑页，按项目持久化的 `reading_order` 排列；左右侧分别保存派生源图、拆分置信度和去弯曲前后评分，并独立执行质量、OCR 和结果版本处理。
- 低置信拆分只保留 `single` 页面，写入 `book_split_review` 并要求复核；不创建虚假另一侧。正常拆分在同一事务中顺延后续页号，子任务只处理既有逻辑源图，不重复拆分。
- 单侧重拍接口创建新逻辑页和新不可变原图，旧页记录唯一替代关系。默认页面列表与 JPG/PDF 导出过滤旧页；旧原图和历史结果仍可按 ID 追溯。普通用户、管理员跨用户操作统一 `404` 并写拒绝审计。
- H5、Android 和 iOS 已增加左右/单页标识与“重拍当前侧”入口，上传后只切换当前逻辑页。OpenAPI 增量修订为 `2026-10-21.1`，三端消费矩阵登记新操作，上一代客户端可忽略新增字段。
- Alembic `0019` 对旧书籍页回填 `legacy`，其他页回填 `disabled`；升级、降级和 ORM 漂移专项已通过。账号合并与项目删除已纳入逻辑派生源图，避免路径残留或文件泄漏。
- 当前本地结果：全量 Python `194 passed, 5 skipped`，应用代码覆盖率 `88.79%`；H5 `38 passed`、Chromium E2E/axe `3 passed`、iOS 工程/发布静态契约 `15 passed`，Ruff、格式、OpenAPI 兼容、迁移升级/漂移/版本、JavaScript 语法和差异检查均通过。迁移门禁首次因本地库停在 `0018` 失败，执行正式升级到 `0019` 后重跑通过；H5 E2E 首次发现重拍文件输入缺少无障碍名称，补齐中英文 `aria-label` 后重跑通过。
- Windows 没有 Gradle、Android SDK、XcodeGen 或 Xcode；提交 `fe8e6cc` 的 GitHub Actions push 工作流 `39572682283` 已由真实 Runner 完整通过，API、Web、容器、Android 和 iOS 共 5 项成功。Android 完成 Gradle 测试、应用编译与 Lint，iOS 完成固定 XcodeGen 工程生成、Xcode 16.4 Simulator 编译和 Swift 单元测试，未以静态检查替代。
- 至少 5 本书、1000 个逻辑页面、300 次双页取景、正确拆分率 `>=95%`、顺序正确率 `>=99%` 以及目标真机仍为人工门禁；合成图片和 Simulator 不能替代。

以下保留已合并 BOOK-001 的近期证据：

- BOOK-001 已在 Android、iOS 和 H5 建立同一条件状态机：必须先检测翻页，再通过连续稳定、清晰度、曝光、边界、书脊和遮挡检查；无固定倒计时且手动快门始终可用。
- Android CameraX 与 iOS AVFoundation 使用连续亮度帧计算运动、中心书脊和保守暗区比例；自动与手动拍摄复用不可变原图保存路径，只有原图保存并进入队列后才重新等待下一页。
- PR #44 的两套 10 项 CI 全部通过并已合并；真实书籍固定集与目标真机保持等待人工验收。

以下保留已合并 EXAM-001 的近期证据：

- EXAM-001 已把 POC 规则扩展为 Worker 本地 CPU 分类链路；支持规则与可选轻量模型固定权重融合，模型异常回退规则。显式试卷模式记录用户意图，扫书模式关闭分类。
- 分类概率、置信区间、建议、结构化信号和分类器版本与活动页面结果版本绑定；旋转、裁切或滤镜生成新版本后旧分类失效。OCR 原文不复制到分类证据。
- 新增当前版本建议取消接口，只有所有者可操作；过期版本返回 `409`，跨用户和管理员统一 `404` 并记录拒绝审计。用户取消与机器证据分离且同版本幂等。
- H5、Android 和 iOS 均以兼容可选字段显示高/中置信建议并可“暂不使用”；旧服务端缺少字段时维持普通页面。当前 OpenAPI 修订为 `2026-10-21.0`，三端消费矩阵已登记新操作。
- Alembic `0018` 对既有页面回填 `legacy`，升级、模型漂移和版本检查通过；回滚只移除新增分类列与约束。
- 本地 Ruff 与格式检查、OpenAPI 当前/上一代兼容、全量 Python `187 passed, 5 skipped`、覆盖率超过 `88%`、H5 `34 passed`、Chromium E2E/axe `3 passed`、iOS 配置与发布契约 `21 passed`、前端语法和差异检查通过。Windows 没有 Gradle、Android SDK 和 Xcode，Android 编译/Lint与 iOS Simulator 必须由 GitHub Runner 提供证据。
- 当前无不少于 300 页的授权固定数据集，召回率 `>=95%`、普通文档误报率、置信分布和性能报告仍为人工门禁；自动化通过后不得宣称真实指标已通过。
- 提交 `e2122ec` 的推送与 PR 两套 Actions 共 10 项全部通过；Android 完成网络/仓储/工作区测试、应用编译与 Lint，iOS 完成 XcodeGen 工程生成、Xcode 16.4 Simulator 编译和全部 Swift 单元测试。公开仓库 Runner 已恢复，之前的额度阻塞未复现。

以下保留已完成 IOS-006 的近期证据：

- IOS-006 已建立双语 App Store 元数据、审核说明、iPhone/iPad 截图场景清单、隐私披露草稿和 TestFlight/App Review 操作规程；所有正式身份、签名与审核账号仅以环境变量名称引用。
- 新增 `PrivacyInfo.xcprivacy`，声明手机号、用户 ID、设备 ID、扫描照片和其他用户内容用于应用功能且不跟踪；应用账户页只在注入有效公网 HTTPS 地址时显示隐私政策与支持入口。
- `tools/validate_ios_release.py` 提供草稿与 `--release` 两级门禁。草稿检查可在普通 CI 运行；正式门禁拒绝 `.invalid`、开发 Bundle ID、空截图以及缺失的签名/审核账号环境变量，并且不会读取或打印 Secret 值。
- 当前固定 Xcode 16.4 只用于既有 Simulator 可复现回归；Apple 2026 上传要求已单独记录为 Xcode 26 或更高版本，Archive 时必须再次核对，不改写现有测试基线冒充上传工具链。
- 本地通过 Ruff/格式、发布草稿校验、全量 Python `177 passed, 5 skipped`、覆盖率 `88.28%`、API 兼容、迁移升级/漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法和差异检查。Windows 不能提供 Swift 编译证据。
- 仓库改为公开后重新触发 PR #41 的两套失败工作流，attempt 2 均获得真实 Runner；API、Web、Android、iOS 与容器共 10 项检查全部通过，PR #41 已以中文 squash 提交 `af6fab7` 合并。IOS-006 已从旧堆叠基线重基到该主线提交。
- PR #42 的推送与拉取请求两套工作流共 10 项检查全部通过；两个 iOS 作业都完成固定 XcodeGen 工程生成、Xcode 16.4 Simulator 编译、隐私清单打包和全部 Swift 单元测试。正式 Xcode 26+ Archive、签名、真实截图、审核账号、真机和 TestFlight 未被自动测试替代。
- 最终纯文档提交的拉取请求 iOS 作业暴露 Runner 设备集偶发为空：Xcode 仅列出通用占位目标，固定设备名以退出码 70 失败，代码编译尚未开始。CI 改为复用可用设备或从当前 Xcode Runtime 创建临时 iPhone 16 Pro，按 UDID 测试并定向清理；不通过重跑掩盖环境脆弱性。

- IOS-004 已由 PR #40 squash 合并到主线，中文提交为 `33f6754`；最终文档头两套 API、Web、Android、iOS 与容器共 10 项 CI 检查通过。
- IOS-005 新增项目/页面工作区，支持完整页序上移下移、活动版本预览、90 度旋转、四角归一化调整、四档滤镜和页面复核；编辑继续调用服务端版本化接口，不覆盖原图。
- 导出支持 JPG/PDF、三档质量和可选 OCR 文本层，恢复既有导出并刷新状态。制品通过鉴权端点下载到当前用户摘要目录，流式校验精确字节数与 SHA-256 后才允许 PDFKit 预览或系统 Share Sheet 分享，失败会删除临时文件。
- 账号删除要求 E.164 手机号、独立 `account_deletion` 短信挑战和完全匹配的用户名；服务端接受并撤销会话后，本机按用户清除项目缓存、捕获原图、上传队列和下载文件。未登录取消流程使用独立 `account_deletion_cancel` 挑战，不把重新登录误作取消。
- 新增页面/导出/账号删除请求契约、非法页序与四角、下载大小/摘要、离线项目缓存、用户分区清理和删除/取消流程测试。
- 本地通过 Ruff/格式、iOS 配置契约 `10 passed`、全量 Python `172 passed, 5 skipped`、覆盖率 `88.28%`、迁移漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法、双语资源键和差异检查。Windows 没有 XcodeGen、Swift、Xcode、Gradle 和 Docker；Swift 编译、PDFKit 链接和 Simulator 测试必须等待 macOS CI。
- PR #41 最初的推送与 PR 两套工作流因私有仓库账户付款/额度问题未分配 Runner；仓库改为公开后执行 attempt 2，10 项作业全部通过并完成合并。该历史保留为外部 CI 故障证据，不再是当前阻塞。
- 账单阻塞期间继续静态自审，提交 `c148d77` 补齐 `WorkspaceStore` 的 Combine 导入、统一 SwiftUI 条件样式类型，并让账号删除在 `401` 时只刷新一次再重试；本地 iOS 契约仍为 `10 passed`。

- IOS-003 已由 PR #39 合并到主线，中文 squash 提交为 `5977b44`；最终文档头两套 API、Web、Android、iOS 与容器共 10 项 CI 检查通过。
- IOS-004 使用按用户摘要分区的版本化 JSON 队列，原图只允许来自当前用户私有捕获目录；队列原子写入并使用首次解锁后的完整文件保护，重复捕获 ID 幂等忽略。
- 上传处理器创建服务端项目与上传会话，流式计算整图 SHA-256；恢复时只跳过服务端 `received_chunks` 明确确认的分片，逐片校验哈希回执，完成响应丢失后通过已完成上传与 `page_id` 幂等收敛。
- `401` 只尝试一次现有刷新令牌流程；断网、`408`、`429` 和 `5xx` 保持幂等键等待重试，上传会话过期才轮换幂等键。登录用户与队列所有者不一致时暂停，禁止跨账号接管。
- `BGProcessingTask` 仅在系统授予执行时间且网络可用时恢复队列，过期会取消当前任务并保留可重入状态；不宣称后台任务会按固定时间执行。
- 拍照成功后先保存不可变原图，再持久化入队并触发前台处理/后台调度；界面区分“已保存并入队”和“原图已保存但入队失败”。
- 新增队列持久化、跨用户拒绝、上传过期轮换、服务端确认分片、完成收敛、单次刷新、断网证据保留、错误回执拒绝和账号隔离测试。
- 本地通过 Ruff/格式、iOS 契约 `8 passed`、全量 Python `170 passed, 5 skipped`、覆盖率 `88.28%`、迁移漂移、H5 `33 passed`、Chromium E2E/axe `3 passed`、管理后台语法和差异检查。Windows 没有 XcodeGen、Swift、Xcode、Gradle 和 Docker；Swift 编译与 Simulator 测试必须等待 macOS CI，不能把契约测试记为编译通过。
- 提交 `74b9aff` 的推送与 PR 两套 API、Web、Android、iOS 和容器共 10 项检查全部通过；两个 iOS 作业均完成固定 XcodeGen 工程生成、Xcode 16.4 Simulator 编译和全部 Swift 单元测试。

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
| Android 正式签名分发 | 等待人工验收 | 仓库链路已实现；需配置真实 GitLab、固定构建镜像、受保护签名资产、公开下载域名和上一稳定 APK，并完成目标真机升级、数据保留与回滚/前滚演练 |
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
| 可选视觉 AI Provider 注册 | `df18491` | PR #47 代码头两套 10 项 CI 全部通过；默认关闭、三类适配器、密钥引用隔离、脱敏状态、Compose Profile 和 AI 网关镜像构建通过；真实供应商与出站安全由后续工作包承担 |
| 视觉 AI 结构化任务契约 | `af44c89` | PR #48 代码头两套 10 项 CI 全部通过；七类 Schema、严格输出解析、保守业务规则、模型版本证据、快照门禁和无网络请求计划通过；安全出站由 AI-003 承接 |
| 视觉 AI 出站网络与媒体安全 | `26b9063` | PR #49 代码头两套 10 项 CI 全部通过；固定 HTTPS 目标、全部 DNS 答案校验、IP 固定 TLS、禁重定向、媒体前缀/令牌、请求限制和容器加固通过；真实 Provider 与出口防火墙待人工验收 |
| 视觉 AI 可靠性与费用门禁 | `1d7eb72` | PR #50 代码头两套 10 项 CI 全部通过；超时/一次重试、PostgreSQL 共享熔断/租约、并发/频率/UTC 日费用和脱敏证据通过；真实价格、账单、告警与供应商 SLA 待 AI-005/人工验收 |

## 下一步

1. 提供授权且脱敏的固定数据集后，先执行 `POC-003/004/005`、`OCR-001`、`EXAM-001`、`BOOK-001/002/003` 与 `AI-005` 的真实指标门禁；只有分类与基础净化指标通过后才启动 `EXAM-002/003`，失败时先调整算法路线或产品范围。
2. 公司服务器恢复后，先部署隔离 staging 并补做 OPS-001～OPS-004 的真实域名、证书、告警、备份恢复与故障注入验收，再执行 `OPS-005` 的 30 分钟 16 用户容量门禁，禁止直接在生产环境开发。
3. 外部账号和材料到位后，分别完成真实短信/企微、Android 正式分发、iOS `validate-only`、TestFlight、目标真机和商店审核；任何 Mock、Simulator 或合成制品证据不得解除对应门禁。
