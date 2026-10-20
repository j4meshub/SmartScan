# H5 登录与企业微信绑定

## 已实现流程

H5 支持用户名/密码登录与企业微信 OAuth 登录。所有认证入口都会发送稳定的 `X-Device-ID`、百分号编码的设备名和 `X-Device-Platform: web`，因此服务端签发 15 分钟访问令牌与单次轮换刷新令牌，不再使用旧 H5 的 24 小时兼容会话。

本地开发默认请求 `http://localhost:8000`；非本地环境默认使用同源 `/api` 反向代理，也可以通过既有 `smartscan.api` 本地配置覆盖。OAuth 状态 Cookie 使用根路径，以兼容浏览器回调页 `/wecom/callback` 与代理后的 `/api/v1/auth/wecom/callback`。

访问令牌失效后，客户端只允许一次刷新并重放原请求；同一时刻的并发 `401` 共用一个刷新请求，避免把单次刷新令牌重复消费。刷新失败、令牌重放或账号不可用时，客户端清除当前会话并回到登录页。退出登录会先撤销服务端设备会话，无论网络结果如何都会清理本地令牌。

企业微信回调有两条安全路径：

- 通讯录返回可信手机号时，服务端按已有绑定或唯一已验证手机号完成登录，并向 H5 返回完整设备会话。
- 通讯录没有手机号时，H5 只在内存保存短期、单次使用的绑定票据；用户必须申请 `wecom_binding` 用途的短信挑战并验证同一手机号后才能完成绑定。

身份冲突不会由 H5 自动合并，仍返回稳定错误并进入管理员处理流程。

## 浏览器存储边界

- 稳定设备 ID 不含用户身份或密钥，可保存在 `localStorage`。
- 访问令牌和刷新令牌以单个 JSON 记录原子写入 `sessionStorage`，不写入 `localStorage`；关闭标签页后需要重新登录，以降低长期令牌暴露面。
- OAuth `state` 仍由服务端保存摘要，并通过 `HttpOnly` Cookie 绑定发起登录的浏览器。H5 请求统一使用 `credentials: include`。
- 回调处理完成后立即从地址栏移除 `code` 和 `state`。绑定票据不落盘。

浏览器存储不能替代原生 Keychain/Keystore。生产部署必须使用 HTTPS，将 H5 与 API 放在同站点反向代理之后，并配置严格 CSP；这些属于 `OPS-002` 发布门禁。

## 配置与验证

本地用户名登录沿用 README 的 API 与 H5 启动方式。企业微信入口默认关闭；启用时至少配置：

```text
SMARTSCAN_WECOM_MODE=live
SMARTSCAN_WECOM_CORP_ID=企业 ID
SMARTSCAN_WECOM_AGENT_ID=应用 AgentId
SMARTSCAN_WECOM_SECRET=应用 Secret
SMARTSCAN_WECOM_REDIRECT_URI=https://同站点地址/wecom/callback
```

当前短信实现只有禁用与开发 Mock，配置校验会阻止把 Mock 带入生产；真实短信供应商接入前，企微通讯录缺少手机号的绑定路径不能发布。自动测试通过注入 Mock 身份验证授权、回调、可信手机号、缺手机号短信绑定、令牌轮换和退出契约；真实企业微信租户、真实短信、HTTPS Cookie 以及 Android 企业微信内置浏览器仍为人工验收项。
