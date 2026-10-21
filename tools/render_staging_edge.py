"""渲染 SmartScan staging 主机 TLS 入口配置，不连接或修改服务器。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = PROJECT_ROOT / "deploy" / "nginx" / "staging-edge.conf.template"
TLS_ROOT = PurePosixPath("/etc/smartscan/staging/tls")
SAFE_POSIX_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
TOKENS = {"{{HOST}}", "{{UPSTREAM_PORT}}", "{{CERTIFICATE}}", "{{CERTIFICATE_KEY}}"}


class EdgeConfigError(ValueError):
    """主机 TLS 入口配置不满足隔离或安全要求。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EdgeConfigError(message)


def validate_host(host: str, *, ci_fixture: bool = False) -> str:
    normalized = host.casefold().rstrip(".")
    _require(HOST_PATTERN.fullmatch(normalized) is not None, "staging 域名格式无效")
    _require(
        normalized.startswith("staging.") or ".staging." in normalized,
        "staging 域名必须明确包含 staging 标签",
    )
    if not ci_fixture:
        _require(
            not normalized.endswith((".invalid", ".example", ".test")),
            "staging 域名仍是保留占位域名",
        )
    return normalized


def validate_tls_target(value: str, label: str) -> str:
    path = PurePosixPath(value)
    _require(path.is_absolute(), f"{label} 必须是绝对路径")
    _require(".." not in path.parts, f"{label} 禁止包含上级路径")
    _require(TLS_ROOT in path.parents, f"{label} 必须位于 staging TLS 目录")
    _require(SAFE_POSIX_PATH.fullmatch(value) is not None, f"{label} 包含危险字符")
    return str(path)


def render_edge_config(
    *,
    host: str,
    upstream_port: int,
    certificate: str,
    certificate_key: str,
    template_path: Path = DEFAULT_TEMPLATE,
    ci_fixture: bool = False,
) -> str:
    host = validate_host(host, ci_fixture=ci_fixture)
    _require(1024 <= upstream_port <= 65535, "staging 上游必须使用非特权端口")
    certificate = validate_tls_target(certificate, "TLS 证书")
    certificate_key = validate_tls_target(certificate_key, "TLS 私钥")
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EdgeConfigError(f"无法读取 Nginx 模板：{template_path}") from exc
    for token in TOKENS:
        _require(template.count(token) >= 1, f"Nginx 模板缺少占位符：{token}")
    rendered = (
        template.replace("{{HOST}}", host)
        .replace("{{UPSTREAM_PORT}}", str(upstream_port))
        .replace("{{CERTIFICATE}}", certificate)
        .replace("{{CERTIFICATE_KEY}}", certificate_key)
    )
    _require("{{" not in rendered and "}}" not in rendered, "Nginx 模板仍有未替换占位符")
    return rendered


def write_new_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise EdgeConfigError(f"拒绝覆盖已有配置：{path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 SmartScan staging 主机 TLS 入口配置")
    parser.add_argument("--host", required=True)
    parser.add_argument("--upstream-port", required=True, type=int)
    parser.add_argument("--certificate", required=True, help="Nginx 运行时证书绝对路径")
    parser.add_argument("--certificate-key", required=True, help="Nginx 运行时私钥绝对路径")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ci-fixture", action="store_true", help="允许 CI 使用保留测试域名")
    args = parser.parse_args()
    rendered = render_edge_config(
        host=args.host,
        upstream_port=args.upstream_port,
        certificate=args.certificate,
        certificate_key=args.certificate_key,
        template_path=args.template,
        ci_fixture=args.ci_fixture,
    )
    write_new_file(args.output, rendered)
    print(f"已生成 staging TLS 入口配置：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
