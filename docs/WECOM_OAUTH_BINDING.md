# 企业微信 OAuth 登录与安全绑定

`WECOM-001` 在 POC 适配器上增加正式登录接口、一次性 OAuth state、可信手机号自动绑定和无手机号时的短信回退。Mock 只用于 development 契约测试，不能替代真实租户验收。

## 接口流程

1. `POST /v1/auth/wecom/authorize` 创建 10 分钟一次性 state，以 `HttpOnly`、`SameSite=Lax` Cookie 绑定发起浏览器，并返回固定官方授权主机的 URL。
2. 企业微信重定向至 `GET /v1/auth/wecom/callback`；服务端先原子消费 state，再使用 code 解析成员身份。
3. 已绑定 `corp_id:UserId` 直接登录；未绑定但可信手机号唯一命中时绑定现有用户；无候选时创建企微用户。
4. 通讯录无手机号时返回 10 分钟一次性 binding ticket；客户端申请 `purpose=wecom_binding` 的短信挑战，再调用 `POST /v1/auth/wecom/bind-phone`。
5. 多手机号候选、同一用户已有不同企微身份或其他冲突返回 `409`，不自动合并。

## 安全控制

- state 和 binding ticket 只向客户端返回一次，数据库仅保存 SHA-256 摘要；state 还必须与发起浏览器的短期 Cookie 完全匹配，过期或消费后不能重放。
- state 在访问外部 Provider 前提交消费，避免慢请求持有数据库行锁，也避免失败 code 被重复尝试。
- 授权 URL 固定为 `https://open.weixin.qq.com/connect/oauth2/authorize`；API 解析仍只访问 `https://qyapi.weixin.qq.com` 且禁止重定向。
- code、state 原文、ticket 原文、Secret、access token 和完整手机号不写入审计或错误响应。
- 已绑定 Provider 身份优先，不因成员后来更换手机号迁移账号；无手机号禁止按姓名或掩码猜测。

## 配置与门禁

live 模式必须通过 Secret/环境注入 `SMARTSCAN_WECOM_CORP_ID`、`SMARTSCAN_WECOM_AGENT_ID`、`SMARTSCAN_WECOM_SECRET` 和 `SMARTSCAN_WECOM_REDIRECT_URI`。回调地址必须与企业微信管理后台可信域名配置一致。

真实 CorpId、通讯录权限和成员范围当前不可用，因此以下项目仍等待人工验收：真实授权跳转、成员 UserId、手机号读取、手机号缺失、权限不足、成员换号、反向代理日志脱敏。自动测试绿灯只证明本地事务和 Mock 契约。

## 迁移与回滚

`20261020_0007` 新增 OAuth state 与绑定票据表。降级会清除未完成登录和绑定流程，不删除已经绑定的 `user_identities`；生产回滚前应暂停企微入口并等待在途回调结束。
