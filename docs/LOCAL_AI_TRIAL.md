# SmartScan 本机 AI 一键试用

## 默认模拟模式

直接双击仓库根目录的 `SmartScan本机试用.cmd`，选择“启动试用”即可。启动器会在首次运行时准备
Python 环境，随后一次启动 API、AI 网关、AI Worker、CPU Worker 和 H5，并自动创建以下低权限
账号：

```text
用户名：demo
密码：SmartScan2026!
```

未创建真实配置文件时，启动器固定使用“模拟 AI”。模拟结果不读取图片内容、不访问真实 Provider，
并对相同结构化任务返回可重复的保守结果。H5 模式徽标和服务端模型证据都会写明 `模拟 AI`/`mock`；
这只能验证“项目授权→页面任务→候选→接受/放弃”的产品流程，不能用于质量、费用、延迟或数据政策
验收。

选择“停止试用”会关闭五个托管进程并保留账号和扫描数据。选择“清理试用数据”并输入中文确认后，
只会删除固定的 `.smartscan-trial/`，其中也包括真实 Provider Secret；`.venv` 会保留。

## 可选真实 Provider

真实模式仍使用部署级共享 Provider，不是个人 BYOK，H5 不提供 Key 输入框。先在仓库根目录创建
`.smartscan-trial/ai-provider.local.json`，填入公司服务的真实值：

```json
{
  "mode": "real",
  "base_url": "https://vlm.corp.example/v1",
  "api_key": "请替换为本机真实密钥",
  "model": "company-vlm-1",
  "api_style": "openai_responses",
  "media_base_url": "https://scan.corp.example/api/v1/ai-media/",
  "allowed_private_cidrs": ["10.20.0.0/16"]
}
```

- `api_style` 只能是 `openai_chat` 或 `openai_responses`。
- 两个 URL 必须使用完整 DNS 域名、默认 HTTPS 端口，不能含账号、查询参数、片段或 IP 地址；
  `media_base_url` 必须以 `/` 结尾。
- `allowed_private_cidrs` 只在公司域名解析到受控私网时填写。每项必须位于 RFC 1918、
  `100.64.0.0/10` 或 `fc00::/7` 内，IPv4 不得宽于 `/16`，IPv6 不得宽于 `/48`。
- 文件不能加入 Git；`.smartscan-trial/` 已整体写入 `.gitignore`。启动器拒绝未知字段、过宽网段、
  非 HTTPS 地址和超过 64 KiB 的文件。

完成一次配置后，仍然只需在中文菜单选择启动、停止或清理。Key 只存在于启动器读取后的 AI 网关
进程环境，不会进入 `runtime-config.json`、`state.json`、Provider 描述、日志、API 响应或 H5 存储。
生产环境会拒绝开启 Mock 模式。

真实模型必须能够读取 `media_base_url` 签发的限时单页 HTTPS 地址。如果公司模型只能读取 URL，
而该地址从模型所在网络不可达，则启动器仍可拉起服务，但真实页面任务不能视为验收通过。此时需要
先由部署方提供可达的 HTTPS 反向代理和精确受控网段；不要改用公网暴露 AI 网关或在客户端填写 Key。

## 命令行等价操作

不使用中文菜单时，可执行：

```powershell
python tools/local_trial.py start
python tools/local_trial.py status
python tools/local_trial.py stop
python tools/local_trial.py clean
```

状态输出会明确显示“模拟 AI”或“真实 AI”。日志位于 `.smartscan-trial/logs/`；启动任一环节失败时，
工具会按已记录 PID 和命令行标记停止本次托管进程，同时保留日志供定位。
