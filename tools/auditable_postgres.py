"""生成并校验SmartScan可审计PostgreSQL 17运行镜像证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_IMAGE = "docker.io/library/postgres"
BASE_DIGEST = "sha256:526f86d93c6ea08fd3f1fe5605650cacc781b2c6013169a0ad8f42c7d3d84f32"
DESTINATION_IMAGE = "ghcr.io/j4meshub/smartscan-postgres"
GOSU_VERSION = "1.20"
GOSU_AMD64_SHA256 = "b1892636c281590f34bc63c1118f058cd9de66c4ea463772e3909672d8b302ac"
CVE_ID = "CVE-2025-68121"
GO_VULN_ID = "GO-2026-4337"
GOSU_COMPONENT = "pkg:github/tianon/gosu@1.20"
GO_STDLIB_COMPONENT = "pkg:golang/stdlib@go1.24.6"
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
FORBIDDEN_WILDCARDS = ("*", "?", "[", "]")
AFFECTED_TLS_SYMBOLS = {
    "crypto/tls.(*Conn).Handshake",
    "crypto/tls.(*Conn).HandshakeContext",
    "crypto/tls.(*Conn).Read",
    "crypto/tls.(*Conn).Write",
    "crypto/tls.Dial",
    "crypto/tls.DialWithDialer",
    "crypto/tls.(*Dialer).Dial",
    "crypto/tls.(*Dialer).DialContext",
    "crypto/tls.(*QUICConn).Start",
}


class AuditError(ValueError):
    """审计证据不满足失败关闭要求。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _now() -> datetime:
    return datetime.now(UTC)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"无法读取JSON证据：{path.name}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json_stream(path: Path) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuditError(f"无法读取govulncheck证据：{path.name}") from exc

    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset >= len(content):
            break
        try:
            value, offset = decoder.raw_decode(content, offset)
        except json.JSONDecodeError as exc:
            raise AuditError(f"govulncheck在字符{exc.pos}处不是有效JSON流") from exc
        _require(isinstance(value, dict), "govulncheck消息必须是JSON对象")
        messages.append(value)
    _require(messages, "govulncheck没有产生JSON证据")
    return messages


def analyze_gosu(
    *,
    image_binary: Path,
    release_binary: Path,
    govuln_json: Path,
    govuln_status: Path,
    nm_evidence: Path,
    go_version_evidence: Path,
    output: Path,
) -> dict[str, Any]:
    image_sha = _sha256(image_binary)
    release_sha = _sha256(release_binary)
    _require(image_sha == GOSU_AMD64_SHA256, "镜像内gosu摘要与固定上游发布摘要不一致")
    _require(release_sha == GOSU_AMD64_SHA256, "下载的gosu发布制品摘要不一致")
    _require(
        image_binary.read_bytes() == release_binary.read_bytes(), "镜像gosu与发布制品字节不一致"
    )

    version_text = go_version_evidence.read_text(encoding="utf-8", errors="replace")
    _require("go1.24.6" in version_text, "gosu Go构建版本证据不是go1.24.6")
    _require("github.com/tianon/gosu" in version_text, "gosu模块来源证据缺失")

    nm_text = nm_evidence.read_text(encoding="utf-8", errors="replace")
    linked_symbols = sorted(symbol for symbol in AFFECTED_TLS_SYMBOLS if symbol in nm_text)

    messages = _read_json_stream(govuln_json)
    findings = [
        message["finding"]
        for message in messages
        if isinstance(message.get("finding"), dict) and message["finding"].get("osv") == GO_VULN_ID
    ]
    reported_symbols = sorted(
        {
            str(frame.get("function"))
            for finding in findings
            for frame in finding.get("trace", [])
            if isinstance(frame, dict) and frame.get("function")
        }
    )
    try:
        status = int(govuln_status.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        raise AuditError("govulncheck退出状态证据无效") from exc
    _require(status in {0, 3}, "govulncheck退出状态不属于成功或发现漏洞")

    nm_available = "no symbol section" not in nm_text.casefold() and bool(nm_text.strip())
    _require(nm_available or bool(reported_symbols), "gosu二进制缺少可复核的符号可达性证据")

    analysis = {
        "schema_version": 1,
        "artifact_kind": "upstream_gosu_binary_reachability_analysis",
        "generated_at": _now().isoformat(),
        "base_image": f"{BASE_IMAGE}@{BASE_DIGEST}",
        "gosu": {
            "version": GOSU_VERSION,
            "component": GOSU_COMPONENT,
            "go_stdlib_component": GO_STDLIB_COMPONENT,
            "expected_sha256": GOSU_AMD64_SHA256,
            "image_sha256": image_sha,
            "release_sha256": release_sha,
            "byte_identical_to_upstream_release": True,
            "go_build_version": "go1.24.6",
        },
        "vulnerability": {
            "cve": CVE_ID,
            "go_vuln_id": GO_VULN_ID,
            "affected_package": "crypto/tls",
            "affected_symbols": sorted(AFFECTED_TLS_SYMBOLS),
        },
        "govulncheck": {
            "mode": "binary",
            "exit_status": status,
            "finding_count": len(findings),
            "reported_symbols": reported_symbols,
        },
        "binary_symbols": {
            "nm_symbol_table_available": nm_available,
            "linked_affected_symbols": linked_symbols,
            "govulncheck_reported_affected_symbols": reported_symbols,
            "affected_symbols_linked": bool(linked_symbols or reported_symbols),
            "call_graph_limit_zh": "二进制模式只能证明受影响符号是否存在，不能还原调用栈；最终结论不依赖不可达推断，而依赖从最终镜像删除gosu。",
        },
        "conclusion_zh": (
            "上游gosu二进制包含受影响符号，不能据此声明上游不受影响；最终镜像必须删除该组件。"
            if linked_symbols or reported_symbols
            else "上游gosu与固定发布制品一致，二进制govulncheck和符号表均未发现受影响crypto/tls符号；最终镜像仍删除gosu以消除组件。"
        ),
    }
    _write_json(output, analysis)
    return analysis


def _spdx_contains_gosu(sbom: dict[str, Any]) -> bool:
    for package in sbom.get("packages", []):
        if not isinstance(package, dict):
            continue
        name = str(package.get("name", "")).casefold()
        refs = json.dumps(package.get("externalRefs", []), ensure_ascii=False).casefold()
        if name == "gosu" or "tianon/gosu" in refs or "pkg:github/tianon/gosu" in refs:
            return True
    return False


def build_vex(
    *, analysis_path: Path, sbom_path: Path, image_digest: str, source_commit: str
) -> dict[str, Any]:
    _require(DIGEST.fullmatch(image_digest) is not None, "VEX产品镜像digest无效")
    _require(COMMIT.fullmatch(source_commit) is not None, "VEX来源提交必须是完整SHA")
    analysis = _load_json(analysis_path)
    sbom = _load_json(sbom_path)
    _require(
        analysis.get("gosu", {}).get("byte_identical_to_upstream_release") is True,
        "缺少gosu上游一致性证据",
    )
    _require(not _spdx_contains_gosu(sbom), "最终镜像SBOM仍包含gosu，禁止生成组件不存在VEX")
    now = _now()
    product = f"pkg:oci/smartscan-postgres@{image_digest.removeprefix('sha256:')}"
    return {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": f"https://github.com/j4meshub/SmartScan/vex/{source_commit}/{CVE_ID}",
        "author": "SmartScan容器供应链",
        "role": "Document Creator",
        "timestamp": now.isoformat(),
        "last_updated": now.isoformat(),
        "version": 1,
        "statements": [
            {
                "vulnerability": {"name": CVE_ID, "aliases": [GO_VULN_ID]},
                "products": [
                    {
                        "@id": product,
                        "identifiers": {"oci_digest": image_digest, "source_commit": source_commit},
                        "subcomponents": [
                            {"@id": GOSU_COMPONENT},
                            {"@id": GO_STDLIB_COMPONENT},
                        ],
                    }
                ],
                "status": "not_affected",
                "justification": "component_not_present",
                "impact_statement": "最终运行镜像删除/usr/local/bin/gosu并固定USER 70:70，受影响Go标准库组件不在最终SBOM和运行文件系统中。",
                "action_statement": "基础镜像、gosu发布摘要、最终镜像digest、entrypoint或USER任一变化时重新执行govulncheck、SBOM与运行兼容性门禁。",
                "x_smartscan_review": {
                    "reviewed_at": now.date().isoformat(),
                    "expires_at": (now + timedelta(days=90)).date().isoformat(),
                    "evidence": {
                        "upstream_analysis_sha256": _sha256(analysis_path),
                        "sbom_sha256": _sha256(sbom_path),
                        "base_digest": BASE_DIGEST,
                        "gosu_release_sha256": GOSU_AMD64_SHA256,
                    },
                    "invalidation_conditions": [
                        "基础镜像digest变化",
                        "最终镜像digest变化",
                        "最终SBOM或文件系统重新出现gosu",
                        "gosu 1.20发布制品摘要变化",
                        "GO-2026-4337受影响符号或Go漏洞库结论变化",
                        "容器USER不再是70:70或entrypoint运行路径变化",
                        "复核日期超过90天",
                    ],
                },
            }
        ],
    }


def generate_vex(
    *, analysis_path: Path, sbom_path: Path, image_digest: str, source_commit: str, output: Path
) -> dict[str, Any]:
    vex = build_vex(
        analysis_path=analysis_path,
        sbom_path=sbom_path,
        image_digest=image_digest,
        source_commit=source_commit,
    )
    _write_json(output, vex)
    return vex


def _trivy_vulnerabilities(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        vulnerability
        for result in report.get("Results", [])
        if isinstance(result, dict)
        for vulnerability in result.get("Vulnerabilities") or []
        if isinstance(vulnerability, dict)
    ]


def validate_vex(vex: dict[str, Any], *, image_digest: str) -> None:
    _require(DIGEST.fullmatch(image_digest) is not None, "待核验镜像digest无效")
    statements = vex.get("statements")
    _require(isinstance(statements, list) and len(statements) == 1, "VEX必须只有一条精确声明")
    statement = statements[0]
    _require(statement.get("vulnerability", {}).get("name") == CVE_ID, "VEX CVE不精确")
    _require(statement.get("status") == "not_affected", "VEX状态必须为not_affected")
    _require(
        statement.get("justification") == "component_not_present",
        "VEX理由必须是最终组件不存在",
    )

    def contains_wildcard(value: Any) -> bool:
        if isinstance(value, str):
            return any(marker in value for marker in FORBIDDEN_WILDCARDS)
        if isinstance(value, dict):
            return any(
                contains_wildcard(key) or contains_wildcard(item) for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_wildcard(item) for item in value)
        return False

    _require(not contains_wildcard(statement), "VEX禁止通配符")
    products = statement.get("products") or []
    _require(len(products) == 1, "VEX必须精确绑定一个产品")
    _require(
        products[0].get("identifiers", {}).get("oci_digest") == image_digest,
        "VEX未绑定待核验镜像digest",
    )
    components = {item.get("@id") for item in products[0].get("subcomponents", [])}
    _require(components == {GOSU_COMPONENT, GO_STDLIB_COMPONENT}, "VEX组件集合不精确")
    review = statement.get("x_smartscan_review") or {}
    _require(review.get("reviewed_at") and review.get("expires_at"), "VEX缺少复核日期")
    _require(len(review.get("invalidation_conditions") or []) >= 6, "VEX失效条件不完整")


def evaluate_scan(*, report_path: Path, vex_path: Path, image_digest: str, output: Path) -> dict:
    report = _load_json(report_path)
    vex = _load_json(vex_path)
    validate_vex(vex, image_digest=image_digest)
    vulnerabilities = _trivy_vulnerabilities(report)
    high_critical = [
        item
        for item in vulnerabilities
        if str(item.get("Severity", "")).upper() in {"HIGH", "CRITICAL"}
    ]
    fixable = [item for item in high_critical if str(item.get("FixedVersion", "")).strip()]
    critical = [
        item for item in high_critical if str(item.get("Severity", "")).upper() == "CRITICAL"
    ]
    _require(not fixable, "最终镜像仍含可修复High/Critical，禁止发布")
    _require(not critical, "最终镜像仍含Critical；本VEX只证明已删除gosu，不能豁免其他发现")
    _require(not high_critical, "最终镜像仍含High；必须处理或建立独立精确风险决策")
    result = {
        "schema_version": 1,
        "result": "passed",
        "image_digest": image_digest,
        "high_critical_count": 0,
        "fixable_high_critical_count": 0,
        "critical_count": 0,
        "vex": {"cve": CVE_ID, "status": "not_affected", "justification": "component_not_present"},
    }
    _write_json(output, result)
    return result


def finalize(
    *,
    image_digest: str,
    source_commit: str,
    workflow_run_url: str,
    vex_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    _require(DIGEST.fullmatch(image_digest) is not None, "发布镜像digest无效")
    _require(COMMIT.fullmatch(source_commit) is not None, "发布来源提交无效")
    _require(workflow_run_url.startswith("https://github.com/"), "Actions运行URL无效")
    vex = _load_json(vex_path)
    validate_vex(vex, image_digest=image_digest)
    generated_at = _now().isoformat()
    mapping = {
        "schema_version": 1,
        "artifact_kind": "auditable_postgresql_runtime_image",
        "description_zh": "以Docker Official Image固定Alpine制品为基础，升级系统包、删除gosu并固定非root用户后构建的SmartScan PostgreSQL运行镜像；不是Docker官方原样制品。",
        "generated_at": generated_at,
        "source_commit": source_commit,
        "workflow_run_url": workflow_run_url,
        "upstream": {"image": BASE_IMAGE, "digest": BASE_DIGEST},
        "transformation": {
            "apk_upgrade": True,
            "gosu_removed": True,
            "runtime_user": "70:70",
            "dockerfile": "deploy/postgres/Dockerfile.auditable",
        },
        "destination": {
            "repository": DESTINATION_IMAGE,
            "digest": image_digest,
            "immutable_ref": f"{DESTINATION_IMAGE}@{image_digest}",
            "visibility": "private_pending_manual_publication_check",
        },
        "evidence": {
            "sbom": "postgres-auditable.spdx.json",
            "vulnerability_report": "postgres-auditable-trivy.json",
            "vex": vex_path.name,
            "runtime": "runtime-verification.txt",
            "gosu_analysis": "gosu-analysis.json",
            "slsa": "GitHub attest-build-provenance registry attestation",
        },
    }
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": DESTINATION_IMAGE,
                "digest": {"sha256": image_digest.removeprefix("sha256:")},
            }
        ],
        "predicateType": "https://github.com/j4meshub/SmartScan/attestations/auditable-postgres/v1",
        "predicate": mapping,
    }
    markdown = "\n".join(
        [
            "# 可审计 PostgreSQL 17 运行镜像发布清单",
            "",
            f"- 上游：`{BASE_IMAGE}@{BASE_DIGEST}`",
            f"- 最终：`{DESTINATION_IMAGE}@{image_digest}`",
            f"- 源提交：`{source_commit}`",
            f"- Actions：`{workflow_run_url}`",
            "- 变更：升级Alpine系统包、删除gosu、固定`USER 70:70`",
            "- VEX：仅精确声明`CVE-2025-68121`因最终组件不存在而不受影响",
            "",
            "> 本镜像由SmartScan构建，不是Docker Official Image原样复制。首次发布后必须人工检查并设置Package公开；用户接受固定digest前不得进入UAT配置。",
            "",
        ]
    )
    _write_json(output_dir / "postgres-source-mapping.json", mapping)
    _write_json(output_dir / "postgres-source-mapping.intoto.json", statement)
    (output_dir / "postgres-source-mapping.md").write_text(markdown, encoding="utf-8")
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="SmartScan可审计PostgreSQL运行镜像证据工具")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze-gosu")
    analyze.add_argument("--image-binary", type=Path, required=True)
    analyze.add_argument("--release-binary", type=Path, required=True)
    analyze.add_argument("--govuln-json", type=Path, required=True)
    analyze.add_argument("--govuln-status", type=Path, required=True)
    analyze.add_argument("--nm-evidence", type=Path, required=True)
    analyze.add_argument("--go-version-evidence", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)

    vex = commands.add_parser("generate-vex")
    vex.add_argument("--analysis", type=Path, required=True)
    vex.add_argument("--sbom", type=Path, required=True)
    vex.add_argument("--image-digest", required=True)
    vex.add_argument("--source-commit", required=True)
    vex.add_argument("--output", type=Path, required=True)

    gate = commands.add_parser("evaluate")
    gate.add_argument("--report", type=Path, required=True)
    gate.add_argument("--vex", type=Path, required=True)
    gate.add_argument("--image-digest", required=True)
    gate.add_argument("--output", type=Path, required=True)

    finish = commands.add_parser("finalize")
    finish.add_argument("--image-digest", required=True)
    finish.add_argument("--source-commit", required=True)
    finish.add_argument("--workflow-run-url", required=True)
    finish.add_argument("--vex", type=Path, required=True)
    finish.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "analyze-gosu":
        analyze_gosu(
            image_binary=args.image_binary,
            release_binary=args.release_binary,
            govuln_json=args.govuln_json,
            govuln_status=args.govuln_status,
            nm_evidence=args.nm_evidence,
            go_version_evidence=args.go_version_evidence,
            output=args.output,
        )
    elif args.command == "generate-vex":
        generate_vex(
            analysis_path=args.analysis,
            sbom_path=args.sbom,
            image_digest=args.image_digest,
            source_commit=args.source_commit,
            output=args.output,
        )
    elif args.command == "evaluate":
        evaluate_scan(
            report_path=args.report,
            vex_path=args.vex,
            image_digest=args.image_digest,
            output=args.output,
        )
    else:
        finalize(
            image_digest=args.image_digest,
            source_commit=args.source_commit,
            workflow_run_url=args.workflow_run_url,
            vex_path=args.vex,
            output_dir=args.output_dir,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
