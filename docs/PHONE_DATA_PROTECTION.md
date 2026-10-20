# 手机号数据保护与密钥轮换

`ACC-002` 为新验证的手机号增加应用层认证加密，并为加密密钥和 HMAC Pepper 保存版本标识。数据库仍只向业务接口暴露掩码；明文只在可信验证写入、明确的服务端解密或轮换操作中短暂存在，不写入日志、异常、审计或仓库。

## 保护模型

- `phone_hmac`：使用版本化 Pepper 的 HMAC-SHA-256，用于精确查重，不可逆。
- `phone_ciphertext`：使用 AES-256-GCM 加密规范化 E.164 号码，每次写入生成独立 96 位随机 nonce。
- 关联数据：绑定固定格式版本、用户 ID 和加密密钥 ID，密文被复制到其他用户或错误密钥版本时认证失败。
- `hmac_key_id` 与 `encryption_key_id`：标记记录使用的密钥版本，便于保留旧密钥读取并显式轮换。
- `encryption_status`：`encrypted` 表示可认证解密；`unavailable` 表示旧数据只有 HMAC 和掩码，必须在下一次短信或可信企业微信验证后补写，禁止根据掩码猜测原号。

实现使用 `cryptography` 的 AES-GCM。任何密文篡改、关联数据不一致、密钥缺失或格式错误都只返回稳定的非敏感错误码。

## 生产配置

生产必须通过 Secret 注入以下配置，不能写入仓库、镜像或客户端：

| 变量 | 含义 |
|---|---|
| `SMARTSCAN_PHONE_HMAC_ACTIVE_KEY_ID` | 新写入使用的 HMAC Pepper 版本 |
| `SMARTSCAN_PHONE_HMAC_PEPPERS` | JSON 对象，包含当前与仍需读取的历史 Pepper |
| `SMARTSCAN_PHONE_ENCRYPTION_ACTIVE_KEY_ID` | 新写入使用的 AES-256-GCM 密钥版本 |
| `SMARTSCAN_PHONE_ENCRYPTION_KEYS` | JSON 对象，值为 URL-safe Base64 编码的 32 字节随机密钥 |

生成材料时在受控终端执行，输出直接保存到密钥管理系统：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

`.env.example` 中的空对象和占位值不能用于生产。生产启动会检查活动版本存在、密钥 ID 格式、Pepper 最低长度和 AES 密钥解码长度，但不会把配置值写入错误信息。

## 轮换流程

1. 完成加密备份，在隔离 staging 验证恢复。
2. 将新旧版本同时放入两个 Keyring，把活动 ID 切到新版本并部署；旧密钥此时仍必须保留。
3. 默认干跑，确认需轮换和需重新验证的数量：

   ```bash
   python -m services.api.app.phone_rotation --limit 500
   ```

4. 分批实际写入：

   ```bash
   python -m services.api.app.phone_rotation --limit 500 --apply
   ```

5. 重复干跑，直到可恢复记录的需轮换数量为零；监控唯一约束、认证失败和事务回滚。
6. 只有在数据库、备份保留期和回滚窗口均不再引用旧版本后，才能从 Secret 系统移除旧密钥。

轮换同时更新 `verified_phones` 的密文/HMAC 版本与兼容期 `users` 的 HMAC/掩码。命令不会输出明文、密文或密钥；`unavailable` 记录只计数，不会自动修改。

## 失败与回滚

- 丢失旧加密密钥时，受影响记录不能恢复明文，只能重新验证；禁止从掩码或其他个人资料推断。
- HMAC 轮换期间必须保留所有仍被数据引用的 Pepper，否则同一手机号可能无法被旧版本摘要查出。
- `20261020_0004` 可降级到 `0003`，但会删除新密文和密钥版本元数据；正式环境只有在确认上一版本仍可接受仅 HMAC/掩码数据后才允许降级。
- 当前公司服务器不可用，因此真实 Secret 管理、备份恢复和生产轮换演练仍是外部门禁。
