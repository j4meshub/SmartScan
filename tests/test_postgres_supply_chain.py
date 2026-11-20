import json
import re
from pathlib import Path

import pytest
import yaml

from tools.postgres_supply_chain import (
    DESTINATION_REPOSITORY,
    DIGEST,
    UPSTREAM_DIGEST,
    SupplyChainError,
    _parse_official_metadata,
    build_upstream_evidence,
    extract_destination,
    finalize,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "postgres-supply-chain.yml"
FIXED_SMARTSCAN_DIGESTS = {
    "api": "80aea0a272791ea44d76895dbd825d091620e0f43ad76c32f32fb6ba97c646d0",
    "worker": "f1cb15e434e99fdced69885667e8646346c75bc293e8ecf9f6b0fa24951768a6",
    "ai-gateway": "1813ada8bda225530d71e5afa9e1c3fd640d5e23d05000d370fdccad0e5e8b00",
    "web": "3d701a4bcaf24c03ead231f10abd316ba83ab89a6984894dfe31af404d3c930c",
    "ops": "be6c50fbdbc9404a9d9589a53799dbc6084470a63f2306ec6bee5736adf94cae",
}


def _index() -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:" + "a" * 64,
                "platform": {"os": "linux", "architecture": "amd64"},
            },
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:" + "b" * 64,
                "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"},
            },
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:" + "c" * 64,
                "platform": {"os": "unknown", "architecture": "unknown"},
            },
        ],
    }


def _upstream_evidence(tag_digest: str = UPSTREAM_DIGEST) -> dict[str, object]:
    return build_upstream_evidence(
        index=_index(),
        registry_digest=UPSTREAM_DIGEST,
        registry_content_type="application/vnd.oci.image.index.v1+json",
        tag_17_digest=tag_digest,
        official_metadata={
            "git_repository": "https://github.com/docker-library/postgres.git",
            "git_commit": "d" * 40,
            "directory": "17/bookworm",
            "tags": "17, 17-bookworm",
        },
        amd64_manifest={"config": {"digest": "sha256:" + "e" * 64}},
        amd64_descriptor_digest="sha256:" + "a" * 64,
        amd64_config={"config": {"Env": ["PG_MAJOR=17", "PG_VERSION=17.7-1.pgdg13+1"]}},
    )


def test_workflow_is_pinned_read_only_on_pr_and_main_only_publish() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "evaluate-postgres-candidates",
        "verify-postgres-upstream",
        "verify-smartscan-critical",
        "publish-postgres-mirror",
    }
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in text
    assert "packages: write" in text
    assert "docker buildx imagetools create" in text
    assert "Dockerfile" not in text
    assert ":latest" not in text and ":main" not in text
    action_refs = re.findall(r"uses:\s+([^\s]+)@([^\s#]+)", text)
    assert action_refs
    assert all(re.fullmatch(r"[a-f0-9]{40}", ref) for _, ref in action_refs)
    publish = jobs["publish-postgres-mirror"]
    assert publish["permissions"] == {"contents": "read", "packages": "write"}
    for forbidden in ("ssh ", "scp ", "sudo ", "docker pull", "docker login"):
        assert forbidden not in text.lower()


def test_workflow_enforces_both_postgres_scans_and_fixed_candidate_critical() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ignore-unfixed: false" in text
    assert "severity: CRITICAL" in text
    assert "ignore-unfixed: true" in text
    assert "severity: HIGH,CRITICAL" in text
    assert "记录全部 High 漏洞供风险复核" in text
    assert "postgres-high-all.json" in text
    for service, digest in FIXED_SMARTSCAN_DIGESTS.items():
        assert f"service: {service}" in text
        assert digest in text
    assert text.count("ignore-unfixed: false") == 6


def test_candidate_matrix_uses_only_frozen_digests_and_does_not_publish() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    candidates = workflow["jobs"]["evaluate-postgres-candidates"]
    rows = candidates["strategy"]["matrix"]["include"]
    assert {row["tag"] for row in rows} == {"17", "17-bookworm", "17-trixie", "17-alpine"}
    assert all(re.fullmatch(r"sha256:[a-f0-9]{64}", row["digest"]) for row in rows)
    assert all(row["digest"] in text for row in rows)
    candidate_text = yaml.safe_dump(candidates, allow_unicode=True)
    assert "packages: write" not in candidate_text
    assert "docker buildx imagetools create" not in candidate_text
    assert "docker login" not in candidate_text.lower()
    for contract in (
        "id -u postgres",
        "id -g postgres",
        "docker-entrypoint.sh",
        "pg_isready",
        "initdb",
        "pg_dump",
        "pg_restore",
        "locale -a",
        "/usr/share/zoneinfo/UTC",
        "$PGDATA",
    ):
        assert contract in text


def test_candidate_snapshot_records_discovery_time_and_fixed_digests() -> None:
    snapshot = json.loads(
        (ROOT / "deploy" / "postgres" / "postgres-17-candidates-20261120.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["work_package"] == "OPS-REG-003A"
    assert snapshot["queried_at"].startswith("2026-11-20T09:37:32")
    assert {item["discovery_tag"] for item in snapshot["candidates"]} == {
        "17",
        "17-bookworm",
        "17-trixie",
        "17-alpine",
    }
    assert all(DIGEST.fullmatch(item["fixed_digest"]) for item in snapshot["candidates"])


def test_build_upstream_evidence_accepts_mutable_tag_drift_but_proves_version() -> None:
    moved = "sha256:" + "f" * 64
    evidence = _upstream_evidence(moved)
    assert evidence["upstream"]["tag_17"]["matches_fixed_digest"] is False
    assert "标签已移动" in evidence["upstream"]["tag_17"]["relation_zh"]
    assert evidence["linux_amd64"]["pg_major"] == "17"
    assert evidence["linux_amd64"]["pg_version"].startswith("17.")
    assert any(
        item["os"] == "linux" and item["architecture"] == "amd64" for item in evidence["platforms"]
    )


def test_upstream_evidence_rejects_wrong_digest_platform_or_version() -> None:
    with pytest.raises(SupplyChainError, match="固定digest"):
        build_upstream_evidence(
            index=_index(),
            registry_digest="sha256:" + "1" * 64,
            registry_content_type="application/vnd.oci.image.index.v1+json",
            tag_17_digest=UPSTREAM_DIGEST,
            official_metadata={},
            amd64_manifest={"config": {"digest": "sha256:" + "e" * 64}},
            amd64_descriptor_digest="sha256:" + "a" * 64,
            amd64_config={"config": {"Env": ["PG_MAJOR=17", "PG_VERSION=17.7"]}},
        )

    index = _index()
    index["manifests"] = [index["manifests"][1]]
    with pytest.raises(SupplyChainError, match="linux/amd64"):
        build_upstream_evidence(
            index=index,
            registry_digest=UPSTREAM_DIGEST,
            registry_content_type="application/vnd.oci.image.index.v1+json",
            tag_17_digest=UPSTREAM_DIGEST,
            official_metadata={},
            amd64_manifest={"config": {"digest": "sha256:" + "e" * 64}},
            amd64_descriptor_digest="sha256:" + "a" * 64,
            amd64_config={"config": {"Env": ["PG_MAJOR=17", "PG_VERSION=17.7"]}},
        )

    with pytest.raises(SupplyChainError, match="PG_MAJOR"):
        build_upstream_evidence(
            index=_index(),
            registry_digest=UPSTREAM_DIGEST,
            registry_content_type="application/vnd.oci.image.index.v1+json",
            tag_17_digest=UPSTREAM_DIGEST,
            official_metadata={},
            amd64_manifest={"config": {"digest": "sha256:" + "e" * 64}},
            amd64_descriptor_digest="sha256:" + "a" * 64,
            amd64_config={"config": {"Env": ["PG_MAJOR=16", "PG_VERSION=16.9"]}},
        )


def test_official_metadata_requires_exact_17_and_official_repo() -> None:
    metadata = _parse_official_metadata(
        "Maintainers: Example\nGitRepo: https://github.com/docker-library/postgres.git\n\n"
        f"GitCommit: {'a' * 40}\nDirectory: 17/bookworm\nTags: 17, 17-bookworm\n"
    )
    assert metadata["directory"] == "17/bookworm"
    with pytest.raises(SupplyChainError, match="官方源码"):
        _parse_official_metadata(
            f"GitRepo: https://example.invalid/postgres.git\nGitCommit: {'a' * 40}\nTags: 17\n"
        )


def test_extract_and_finalize_create_non_build_mapping(tmp_path: Path) -> None:
    digest = UPSTREAM_DIGEST
    metadata_path = tmp_path / "metadata.json"
    output_path = tmp_path / "github-output.txt"
    metadata_path.write_text(
        json.dumps({"containerimage.descriptor": {"digest": digest}}), encoding="utf-8"
    )
    assert extract_destination(metadata_path, output_path) == digest
    assert output_path.read_text(encoding="utf-8") == f"digest={digest}\n"

    evidence = _upstream_evidence("sha256:" + "f" * 64)
    upstream_path = tmp_path / "upstream.json"
    destination_path = tmp_path / "destination.json"
    upstream_path.write_text(json.dumps(evidence), encoding="utf-8")
    destination_path.write_text(json.dumps(_index()), encoding="utf-8")
    output_dir = tmp_path / "release"
    mapping = finalize(
        upstream_evidence_path=upstream_path,
        destination_index_path=destination_path,
        destination_digest=digest,
        source_commit="1" * 40,
        workflow_run_url="https://github.com/j4meshub/SmartScan/actions/runs/123",
        output_dir=output_dir,
    )
    assert mapping["destination"]["immutable_ref"] == f"{DESTINATION_REPOSITORY}@{digest}"
    assert mapping["manifest_relation"]["same_digest"] is True
    assert "不是源码重建" in mapping["description_zh"]
    statement = json.loads(
        (output_dir / "postgres-source-mapping.intoto.json").read_text(encoding="utf-8")
    )
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    assert statement["predicate"]["metadata"]["layersModified"] is False
    assert statement["predicate"]["metadata"]["sourceCodeRebuilt"] is False
    assert statement["predicate"]["metadata"]["dockerOfficialGhcrPublicationClaimed"] is False


def test_finalize_rejects_changed_index_and_bad_destination_digest(tmp_path: Path) -> None:
    evidence = _upstream_evidence()
    upstream_path = tmp_path / "upstream.json"
    destination_path = tmp_path / "destination.json"
    upstream_path.write_text(json.dumps(evidence), encoding="utf-8")
    changed = _index()
    changed["manifests"] = changed["manifests"][:-1]
    destination_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(SupplyChainError, match="索引结构"):
        finalize(
            upstream_evidence_path=upstream_path,
            destination_index_path=destination_path,
            destination_digest=UPSTREAM_DIGEST,
            source_commit="1" * 40,
            workflow_run_url="https://github.com/j4meshub/SmartScan/actions/runs/123",
            output_dir=tmp_path / "release",
        )
    with pytest.raises(SupplyChainError, match="目标digest"):
        finalize(
            upstream_evidence_path=upstream_path,
            destination_index_path=destination_path,
            destination_digest="latest",
            source_commit="1" * 40,
            workflow_run_url="https://github.com/j4meshub/SmartScan/actions/runs/123",
            output_dir=tmp_path / "release",
        )
