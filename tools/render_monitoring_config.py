"""渲染 SmartScan staging 监控配置；不连接服务器或启动服务。"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

if __package__:
    from tools.validate_staging_config import PROJECT_ROOT, load_env_file
else:
    from validate_staging_config import PROJECT_ROOT, load_env_file

MONITORING_CONFIG_ROOT = PurePosixPath("/etc/smartscan/staging/monitoring")
TEMPLATE_ROOT = PROJECT_ROOT / "deploy" / "monitoring"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{32,256}$")


class MonitoringConfigError(ValueError):
    """监控配置不满足安全边界。"""


@dataclass(frozen=True)
class RenderedMonitoringConfig:
    target_dir: Path
    webhook_host: str

    def safe_summary(self) -> dict[str, object]:
        return {
            "target_dir": str(self.target_dir),
            "webhook_host": self.webhook_host,
            "files": ["prometheus.yml", "rules.yml", "alertmanager.yml"],
            "secrets_included": False,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MonitoringConfigError(message)


def _validate_secret_file(path: Path, *, ci_fixture: bool) -> str:
    _require(path.is_file() and not path.is_symlink(), "指标令牌必须是普通文件且不能是符号链接")
    if not ci_fixture and os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        _require(mode & 0o077 == 0, "指标令牌文件权限必须为 0600 或更严格")
    token = path.read_text(encoding="utf-8").strip()
    _require(TOKEN_PATTERN.fullmatch(token) is not None, "指标令牌格式或长度无效")
    return token


def _validate_webhook(value: str, *, ci_fixture: bool) -> str:
    parsed = urlparse(value)
    _require(parsed.scheme == "https", "告警 Webhook 必须使用 HTTPS")
    _require(bool(parsed.hostname), "告警 Webhook 缺少域名")
    _require(parsed.username is None and parsed.password is None, "告警 Webhook 禁止 URL 用户信息")
    _require(not parsed.fragment, "告警 Webhook 禁止片段")
    _require(parsed.port in (None, 443), "告警 Webhook 只允许标准 HTTPS 端口")
    _require(not any(character.isspace() for character in value), "告警 Webhook 禁止空白字符")
    _require('"' not in value and "\\" not in value, "告警 Webhook 含不安全字符")
    if not ci_fixture:
        _require(
            not parsed.hostname.endswith((".invalid", ".example", ".test")),
            "告警 Webhook 仍是保留占位域名",
        )
    return parsed.hostname


def _validate_target(target_dir: Path, *, ci_fixture: bool) -> Path:
    target = target_dir.resolve(strict=False)
    if not ci_fixture:
        _require(target.is_absolute(), "监控配置目录必须是绝对路径")
        expected = Path(str(MONITORING_CONFIG_ROOT))
        _require(target == expected, "真实监控配置必须写入固定 staging 目录")
        try:
            target.relative_to(PROJECT_ROOT)
        except ValueError:
            pass
        else:
            raise MonitoringConfigError("真实监控配置禁止写入仓库")
    if target.exists():
        _require(target.is_dir() and not target.is_symlink(), "监控配置目标不是安全目录")
    return target


def render_monitoring_config(
    *,
    runtime_env_path: Path,
    metrics_token_path: Path,
    alert_webhook_url: str,
    target_dir: Path,
    ci_fixture: bool = False,
) -> RenderedMonitoringConfig:
    runtime = load_env_file(runtime_env_path)
    _require(
        runtime.get("SMARTSCAN_OPS_METRICS_ENABLED", "").casefold() == "true", "指标端点未启用"
    )
    runtime_token = runtime.get("SMARTSCAN_OPS_METRICS_TOKEN", "")
    token = _validate_secret_file(metrics_token_path.resolve(), ci_fixture=ci_fixture)
    _require(runtime_token == token, "运行配置与 Prometheus 指标令牌不一致")
    webhook_host = _validate_webhook(alert_webhook_url, ci_fixture=ci_fixture)
    target = _validate_target(target_dir, ci_fixture=ci_fixture)

    outputs = {
        "prometheus.yml": (TEMPLATE_ROOT / "prometheus.yml").read_text(encoding="utf-8"),
        "rules.yml": (TEMPLATE_ROOT / "alerts.yml").read_text(encoding="utf-8"),
        "alertmanager.yml": (
            (TEMPLATE_ROOT / "alertmanager.yml.template")
            .read_text(encoding="utf-8")
            .replace("{{ALERT_WEBHOOK_URL}}", alert_webhook_url)
        ),
    }
    _require("{{" not in outputs["alertmanager.yml"], "告警配置仍包含未替换占位符")
    target.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        destination = target / name
        _require(not destination.exists(), f"拒绝覆盖现有监控配置：{destination}")
        destination.write_text(content, encoding="utf-8", newline="\n")
        if os.name != "nt":
            destination.chmod(0o600)
    return RenderedMonitoringConfig(target_dir=target, webhook_host=webhook_host)


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 SmartScan staging 监控配置")
    parser.add_argument("--runtime-env", required=True, type=Path)
    parser.add_argument("--metrics-token-file", required=True, type=Path)
    parser.add_argument("--alert-webhook-url", required=True)
    parser.add_argument("--target-dir", required=True, type=Path)
    parser.add_argument("--ci-fixture", action="store_true")
    args = parser.parse_args()
    result = render_monitoring_config(
        runtime_env_path=args.runtime_env,
        metrics_token_path=args.metrics_token_file,
        alert_webhook_url=args.alert_webhook_url,
        target_dir=args.target_dir,
        ci_fixture=args.ci_fixture,
    )
    print(json.dumps(result.safe_summary(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
