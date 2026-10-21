from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from tools.bbr_baseline import (
    BbrBaselineError,
    capture_snapshot,
    evaluate_transition,
    render_rollback,
    validate_snapshot,
    write_new_json,
)
from tools.render_staging_edge import (
    DEFAULT_TEMPLATE,
    EdgeConfigError,
    render_edge_config,
    write_new_file,
)
from tools.validate_tls_material import TlsMaterialError, validate_tls_material

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _issue_certificate(
    root: Path,
    *,
    host: str = "staging.ci.smartscan.test",
    lifetime_days: int = 30,
    key: rsa.RSAPrivateKey | None = None,
) -> tuple[Path, Path]:
    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=lifetime_days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate_path = root / "fullchain.pem"
    key_path = root / "privkey.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certificate_path.chmod(0o644)
    key_path.chmod(0o600)
    return certificate_path, key_path


def test_edge_template_renders_loopback_tls_and_safe_logs(tmp_path: Path) -> None:
    rendered = render_edge_config(
        host="staging.ci.smartscan.test",
        upstream_port=18080,
        certificate="/etc/smartscan/staging/tls/fullchain.pem",
        certificate_key="/etc/smartscan/staging/tls/privkey.pem",
        ci_fixture=True,
    )

    assert "server 127.0.0.1:18080;" in rendered
    assert "server_name staging.ci.smartscan.test;" in rendered
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in rendered
    assert "listen 443 ssl http2;" in rendered
    assert "proxy_request_buffering off;" in rendered
    assert "proxy_buffering off;" in rendered
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in rendered
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in rendered
    assert "$request_method $uri $server_protocol" in rendered
    assert '"$request"' not in rendered
    assert "$http_referer" not in rendered
    assert "{{" not in rendered

    output = tmp_path / "edge.conf"
    write_new_file(output, rendered)
    with pytest.raises(EdgeConfigError, match="拒绝覆盖"):
        write_new_file(output, rendered)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"host": "api.smartscan.company"}, "staging 标签"),
        ({"host": "staging.smartscan.example"}, "保留占位域名"),
        ({"upstream_port": 443}, "非特权端口"),
        ({"certificate": "/tmp/fullchain.pem"}, "staging TLS 目录"),
        (
            {"certificate": "/etc/smartscan/staging/tls/full chain;$uri.pem"},
            "危险字符",
        ),
    ],
)
def test_edge_renderer_rejects_unsafe_values(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "host": "staging.smartscan.company",
        "upstream_port": 18080,
        "certificate": "/etc/smartscan/staging/tls/fullchain.pem",
        "certificate_key": "/etc/smartscan/staging/tls/privkey.pem",
    }
    values.update(kwargs)
    with pytest.raises(EdgeConfigError, match=message):
        render_edge_config(**values)  # type: ignore[arg-type]


def test_tls_material_matches_exact_san_key_and_lifetime(tmp_path: Path) -> None:
    certificate, key = _issue_certificate(tmp_path)

    result = validate_tls_material(
        host="staging.ci.smartscan.test",
        certificate_path=certificate,
        certificate_key_path=key,
        ci_fixture=True,
    )

    assert result["san_exact_match"] is True
    assert result["certificate_key_match"] is True
    assert result["private_key_included"] is False
    assert "BEGIN PRIVATE KEY" not in json.dumps(result)


def test_tls_material_rejects_wrong_host_key_and_short_lifetime(tmp_path: Path) -> None:
    certificate, key = _issue_certificate(tmp_path, lifetime_days=2)
    with pytest.raises(TlsMaterialError, match="SAN"):
        validate_tls_material(
            host="other.staging.smartscan.test",
            certificate_path=certificate,
            certificate_key_path=key,
            ci_fixture=True,
        )
    with pytest.raises(TlsMaterialError, match="剩余有效期"):
        validate_tls_material(
            host="staging.ci.smartscan.test",
            certificate_path=certificate,
            certificate_key_path=key,
            ci_fixture=True,
        )

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key.write_bytes(
        other_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(0o600)
    with pytest.raises(TlsMaterialError, match="不匹配"):
        validate_tls_material(
            host="staging.ci.smartscan.test",
            certificate_path=certificate,
            certificate_key_path=key,
            minimum_days=1,
            ci_fixture=True,
        )


def test_tls_material_rejects_weak_rsa_key(tmp_path: Path) -> None:
    weak_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    certificate, key = _issue_certificate(tmp_path, key=weak_key)

    with pytest.raises(TlsMaterialError, match="2048"):
        validate_tls_material(
            host="staging.ci.smartscan.test",
            certificate_path=certificate,
            certificate_key_path=key,
            ci_fixture=True,
        )


@pytest.mark.skipif(os.name == "nt", reason="Windows 不提供 POSIX 私钥权限位")
def test_tls_material_rejects_group_readable_private_key(tmp_path: Path) -> None:
    certificate, key = _issue_certificate(tmp_path)
    key.chmod(0o640)

    with pytest.raises(TlsMaterialError, match="0600"):
        validate_tls_material(
            host="staging.ci.smartscan.test",
            certificate_path=certificate,
            certificate_key_path=key,
            ci_fixture=True,
        )


def _write_proc_fixture(root: Path, *, control: str, qdisc: str, kernel: str = "6.8.0-90") -> None:
    values = {
        "net/ipv4/tcp_available_congestion_control": "reno cubic bbr\n",
        "net/ipv4/tcp_congestion_control": f"{control}\n",
        "net/core/default_qdisc": f"{qdisc}\n",
        "kernel/osrelease": f"{kernel}\n",
    }
    for relative, value in values.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")


def test_bbr_snapshot_transition_and_exact_rollback(tmp_path: Path) -> None:
    before_root = tmp_path / "before"
    after_root = tmp_path / "after"
    _write_proc_fixture(before_root, control="cubic", qdisc="fq_codel")
    _write_proc_fixture(after_root, control="bbr", qdisc="fq")
    modules = tmp_path / "modules"
    modules.write_text("tcp_bbr 20480 1 - Live 0x0\n", encoding="utf-8")
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    captured = datetime(2026, 10, 22, tzinfo=UTC)

    before = capture_snapshot(
        proc_sys_root=before_root,
        modules_path=modules,
        machine_id_path=machine_id,
        now=captured,
    )
    after = capture_snapshot(
        proc_sys_root=after_root,
        modules_path=modules,
        machine_id_path=machine_id,
        now=captured + timedelta(minutes=5),
    )
    report = evaluate_transition(before, after)

    assert report["ready_for_controlled_network_comparison"] is True
    assert report["core_network_gate_complete"] is False
    assert report["checks"] == {
        "same_host": True,
        "same_kernel": True,
        "after_is_later": True,
        "bbr_available": True,
        "bbr_active": True,
        "fq_active": True,
    }
    assert render_rollback(before) == (
        "# 由变更前 SmartScan BBR 快照生成；人工复核后安装。\n"
        "net.core.default_qdisc=fq_codel\n"
        "net.ipv4.tcp_congestion_control=cubic\n"
    )


def test_bbr_transition_fails_closed_on_kernel_change_or_unsafe_value(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    _write_proc_fixture(root, control="bbr", qdisc="fq", kernel="6.8.0-91")
    modules = tmp_path / "modules"
    modules.write_text("", encoding="utf-8")
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("fedcba9876543210fedcba9876543210\n", encoding="utf-8")
    after = capture_snapshot(
        proc_sys_root=root,
        modules_path=modules,
        machine_id_path=machine_id,
    )
    before = dict(after)
    before["kernel_release"] = "6.8.0-90"
    before["active_congestion_control"] = "cubic"
    before["captured_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    report = evaluate_transition(before, after)
    assert report["ready_for_controlled_network_comparison"] is False
    assert report["checks"]["same_kernel"] is False

    after["active_congestion_control"] = "bbr;reboot"
    with pytest.raises(BbrBaselineError, match="不安全字符"):
        validate_snapshot(after)

    evidence = tmp_path / "evidence.json"
    write_new_json(evidence, before)
    with pytest.raises(BbrBaselineError, match="拒绝覆盖"):
        write_new_json(evidence, before)


def test_nginx_internal_send_and_ci_compose_static_contract() -> None:
    nginx = (PROJECT_ROOT / "deploy/nginx/nginx.conf").read_text(encoding="utf-8")
    compose_path = PROJECT_ROOT / "deploy/compose/docker-compose.nginx-test.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert "internal;" in nginx
    assert "disable_symlinks on from=/srv/smartscan/data;" in nginx
    assert "etag off;" in nginx
    assert "add_header ETag $upstream_http_etag always;" in nginx
    assert "sendfile on;" in nginx
    assert "sendfile_max_chunk 1m;" in nginx
    assert "map $uri $auth_limit_key" in nginx
    assert "location ~ ^/api/v1/auth" not in nginx
    assert "proxy_pass http://api/;" in nginx
    assert set(compose["services"]) == {"api", "nginx"}
    assert compose["services"]["nginx"]["ports"] == ["127.0.0.1:18081:80"]
    assert compose["services"]["nginx"]["image"] == "smartscan-web:ci"
    assert DEFAULT_TEMPLATE.is_file()
    assert (PROJECT_ROOT / "deploy/sysctl/60-smartscan-bbr.conf").read_text(
        encoding="utf-8"
    ).splitlines()[-2:] == [
        "net.core.default_qdisc=fq",
        "net.ipv4.tcp_congestion_control=bbr",
    ]
