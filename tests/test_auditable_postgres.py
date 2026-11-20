import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from tools import auditable_postgres as audit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "auditable-postgres.yml"
DOCKERFILE = ROOT / "deploy" / "postgres" / "Dockerfile.auditable"
RUNTIME_TEST = ROOT / "deploy" / "postgres" / "verify-auditable-runtime.sh"
DIGEST = "sha256:" + "a" * 64
COMMIT = "b" * 40


def _json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _analysis(tmp_path: Path) -> Path:
    return _json(
        tmp_path / "analysis.json",
        {"gosu": {"byte_identical_to_upstream_release": True}},
    )


def _sbom(tmp_path: Path, *, include_gosu: bool = False) -> Path:
    packages = [{"name": "gosu"}] if include_gosu else [{"name": "postgresql17"}]
    return _json(tmp_path / "sbom.json", {"packages": packages})


def test_dockerfile_removes_gosu_and_fixes_nonroot_runtime() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert audit.BASE_DIGEST in text
    assert "apk upgrade --no-cache" in text
    assert "rm -f /usr/local/bin/gosu" in text
    assert text.rstrip().endswith("USER 70:70")


def test_workflow_pins_actions_and_never_publishes_pull_requests() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    assert "verify-auditable-postgres" in workflow["jobs"]
    assert "publish-auditable-postgres" in workflow["jobs"]
    refs = re.findall(r"uses:\s+([^\s]+)@([^\s#]+)", text)
    assert refs
    assert all(re.fullmatch(r"[a-f0-9]{40}", ref) for _, ref in refs)
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in text
    assert "govulncheck" in text
    assert "CVE-2025-68121" in (ROOT / "tools" / "auditable_postgres.py").read_text(
        encoding="utf-8"
    )
    assert ":latest" not in text.casefold()
    assert "docker login" not in text.casefold()
    assert "ssh " not in text.casefold()
    assert "set -euo pipefail" in text
    assert "test -s postgres-audit/runtime-verification.txt" in text
    assert "grep -Fx 'result=passed'" in text


def test_runtime_contract_covers_database_lifecycle_and_tools() -> None:
    text = RUNTIME_TEST.read_text(encoding="utf-8")

    for evidence in (
        "--user 70:70",
        "--read-only",
        "POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C",
        "/var/run/postgresql:rw,noexec,nosuid,nodev,size=16m,mode=3775,uid=70,gid=70",
        "智能扫描验证",
        "migrations upgrade",
        "docker restart",
        "pg_dump",
        "pg_restore",
        "pg_basebackup",
        "pg_verifybackup",
        '"${ops_image}" -m services.api.app.migrations upgrade',
        "sudo chmod 0700",
        "sudo rm -rf",
        'stage="start_postgres"',
        'stage="run_smartscan_migrations"',
        'stage="basebackup_and_verify"',
        'docker logs --tail 100 "${container}"',
    ):
        assert evidence in text

    assert "docker inspect" not in text.split("on_error()", 1)[1].split("cleanup()", 1)[0]


def test_analyze_gosu_requires_identical_fixed_release_and_records_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = b"fixed-upstream-gosu"
    expected = hashlib.sha256(binary).hexdigest()
    monkeypatch.setattr(audit, "GOSU_AMD64_SHA256", expected)
    image = tmp_path / "image-gosu"
    release = tmp_path / "release-gosu"
    image.write_bytes(binary)
    release.write_bytes(binary)
    govuln = tmp_path / "govuln.json"
    govuln.write_text(
        json.dumps(
            {
                "finding": {
                    "osv": audit.GO_VULN_ID,
                    "trace": [{"function": "crypto/tls.(*Conn).Handshake"}],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status = tmp_path / "status"
    status.write_text("3\n", encoding="utf-8")
    nm = tmp_path / "nm"
    nm.write_text("crypto/tls.(*Conn).Handshake\n", encoding="utf-8")
    version = tmp_path / "version"
    version.write_text("go1.24.6 path github.com/tianon/gosu\n", encoding="utf-8")
    output = tmp_path / "analysis.json"

    result = audit.analyze_gosu(
        image_binary=image,
        release_binary=release,
        govuln_json=govuln,
        govuln_status=status,
        nm_evidence=nm,
        go_version_evidence=version,
        output=output,
    )

    assert result["gosu"]["byte_identical_to_upstream_release"] is True
    assert result["govulncheck"]["target_finding_count"] == 1
    assert result["govulncheck"]["symbol_finding_count"] == 1
    assert result["govulncheck"]["module_only_finding_count"] == 0
    assert result["binary_symbols"]["affected_symbols_linked"] is True
    assert output.is_file()


def test_govulncheck_reader_accepts_pretty_concatenated_json(tmp_path: Path) -> None:
    path = tmp_path / "govuln.json"
    path.write_text(
        json.dumps({"config": {"scan_mode": "binary"}}, indent=2)
        + "\n"
        + json.dumps({"finding": {"osv": audit.GO_VULN_ID}}, indent=2),
        encoding="utf-8",
    )

    messages = audit._read_json_stream(path)

    assert messages == [
        {"config": {"scan_mode": "binary"}},
        {"finding": {"osv": audit.GO_VULN_ID}},
    ]


def test_vex_is_exact_and_only_allowed_when_gosu_is_absent(tmp_path: Path) -> None:
    vex = audit.build_vex(
        analysis_path=_analysis(tmp_path),
        sbom_path=_sbom(tmp_path),
        image_digest=DIGEST,
        source_commit=COMMIT,
    )

    audit.validate_vex(vex, image_digest=DIGEST)
    statement = vex["statements"][0]
    assert statement["vulnerability"]["name"] == "CVE-2025-68121"
    assert statement["justification"] == "component_not_present"
    assert statement["products"][0]["identifiers"]["oci_digest"] == DIGEST
    assert "*" not in json.dumps(statement)
    assert "?" not in json.dumps(statement)

    with pytest.raises(audit.AuditError, match="仍包含gosu"):
        audit.build_vex(
            analysis_path=_analysis(tmp_path),
            sbom_path=_sbom(tmp_path, include_gosu=True),
            image_digest=DIGEST,
            source_commit=COMMIT,
        )


def test_combined_gate_rejects_fixable_high_and_any_remaining_critical(tmp_path: Path) -> None:
    vex_path = _json(
        tmp_path / "vex.json",
        audit.build_vex(
            analysis_path=_analysis(tmp_path),
            sbom_path=_sbom(tmp_path),
            image_digest=DIGEST,
            source_commit=COMMIT,
        ),
    )
    empty_report = _json(tmp_path / "empty.json", {"Results": []})
    result = audit.evaluate_scan(
        report_path=empty_report,
        vex_path=vex_path,
        image_digest=DIGEST,
        output=tmp_path / "gate.json",
    )
    assert result["result"] == "passed"

    fixable = _json(
        tmp_path / "fixable.json",
        {
            "Results": [
                {
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-test", "Severity": "HIGH", "FixedVersion": "2"}
                    ]
                }
            ]
        },
    )
    with pytest.raises(audit.AuditError, match="可修复"):
        audit.evaluate_scan(
            report_path=fixable,
            vex_path=vex_path,
            image_digest=DIGEST,
            output=tmp_path / "rejected.json",
        )

    critical = _json(
        tmp_path / "critical.json",
        {
            "Results": [
                {
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2025-68121",
                            "Severity": "CRITICAL",
                            "FixedVersion": "",
                        }
                    ]
                }
            ]
        },
    )
    with pytest.raises(audit.AuditError, match="仍含Critical"):
        audit.evaluate_scan(
            report_path=critical,
            vex_path=vex_path,
            image_digest=DIGEST,
            output=tmp_path / "rejected-critical.json",
        )
