# 企业微信可信身份 POC

## 目标与边界

`POC-001` 验证企业微信 OAuth code、成员 `UserId` 和通讯录手机号可以通过可替换适配器形成稳定的内部契约，并验证手机号缺失或候选冲突时不会误合并账号。

本工作包不开放正式登录接口、不创建或合并生产账号，也不把 Mock 结果视为真实企业微信验收。正式 OAuth 回调、会话签发、数据库事务和短信绑定由 `WECOM-001`、`ACC-001` 至 `ACC-003` 实现。

## 适配器流程

```text
OAuth code
  -> 固定企业微信 API 域名换取 access_token
  -> 获取访问成员 UserId
  -> 按 UserId 读取通讯录成员
  -> 规范化可信手机号（可缺失）
  -> 输出 WeComIdentity
  -> 账号决策契约（仅决策，不写数据库）
```

真实适配器只访问 `https://qyapi.weixin.qq.com`，依次调用：

- `/cgi-bin/gettoken`
- `/cgi-bin/auth/getuserinfo`
- `/cgi-bin/user/get`

读取成员能力以[企业微信官方文档](https://developer.work.weixin.qq.com/document/path/90196)和实际租户权限为最终依据。

## 运行模式

| `SMARTSCAN_WECOM_MODE` | 用途 | 约束 |
|---|---|---|
| `disabled` | 默认值 | 所有解析请求返回稳定的禁用错误码 |
| `mock` | 本地开发和契约测试 | 只允许 `development`；结果标记为 `assurance=mock` |
| `live` | 真实企业微信租户 | 必须配置 CorpId、AgentId 和 Secret；结果标记为 `assurance=wecom_directory` |

真实配置还包括 `SMARTSCAN_WECOM_TIMEOUT_SECONDS`。Secret 只允许通过服务端 Secret 注入，不得写入仓库、客户端、日志或错误响应。

## 账号决策契约

| 条件 | 决策 | 安全含义 |
|---|---|---|
| `corp_id:UserId` 已绑定 | `use_bound_identity` | 已绑定身份优先，不因后来手机号变化迁移账号 |
| 未绑定且可信手机号唯一命中 | `bind_verified_phone` | 后续事务可绑定到唯一统一用户 |
| 未绑定且可信手机号无候选 | `create_wecom_user` | 后续事务可创建企微统一用户 |
| 通讯录手机号缺失 | `require_phone_binding` | 必须走短信绑定，禁止使用姓名或模糊号码猜测 |
| 手机号出现多个候选 | `require_conflict_review` | 禁止自动合并，进入人工冲突处理 |

## 安全控制

- 固定 HTTPS API 主机，不接受客户端或环境变量提供的任意 Provider URL。
- 每次请求显式禁止 HTTP 重定向，避免凭据被转发到其他主机。
- access token 仅在进程内短期缓存，并在官方过期时间前提前失效。
- 外部错误统一转为稳定错误码；不传播 `errmsg`，避免 code、Secret 或手机号进入日志。
- OAuth 只接受企业成员 `UserId`；仅返回 `OpenId` 的非成员身份拒绝进入账号流程。
- 通讯录返回的成员 ID 必须与 OAuth 身份一致，手机号必须通过 E.164 规范化。
- Mock 的 assurance 与真实通讯录 assurance 不可互换，生产环境禁止 Mock。

## 自动化证据

`tests/test_wecom_adapter.py` 覆盖：

- Mock 的手机号存在、手机号缺失、未知 code 和伪造真实 assurance。
- 真实适配器的三段 API 契约、固定域名、手机号规范化和令牌复用。
- 非成员、身份缺失、成员错配、非法手机号、Provider 错误和重定向拒绝。
- 已绑定身份、唯一手机号、无候选、无手机号和多候选冲突的全部决策。
- 默认关闭、非开发环境禁用 Mock、真实配置缺失和未知模式。

## 真实租户人工门禁

下列项目尚未通过，不得以本地 Mock 代替：

1. 配置自建应用 CorpId、AgentId、Secret、可信域名、回调地址和成员可见范围。
2. 使用真实成员确认 OAuth 返回可信 `UserId`。
3. 验证通讯录权限可以读取手机号，并记录手机号缺失、权限不足和成员不在可见范围的返回。
4. 使用已绑定成员更换手机号，确认仍按原 `UserId` 登录且不会迁移到其他账号。
5. 确认日志、错误追踪和反向代理访问日志均不记录 code、Secret、access token 或完整手机号。

完成上述项目并保存脱敏证据后，才可把“企业微信真实身份与手机号”门禁标记为通过。
