"""核验并记录 Docker Official Image PostgreSQL 固定制品的复制证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UPSTREAM_REPOSITORY = "docker.io/library/postgres"
UPSTREAM_REGISTRY_REPOSITORY = "library/postgres"
UPSTREAM_DIGEST = "sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac"
DESTINATION_REPOSITORY = "ghcr.io/j4meshub/smartscan-postgres"
OFFICIAL_IMAGES_METADATA = (
    "https://raw.githubusercontent.com/docker-library/official-images/master/library/postgres"
)
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


class SupplyChainError(ValueError):
    """PostgreSQL 制品或来源证据未满足失败关闭要求。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SupplyChainError(message)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _request_json(url: str, *, headers: dict[str, str] | None = None) -> tuple[Any, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), response.headers


def _request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "SmartScan-OPS-REG-003"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def _docker_token() -> str:
    query = urllib.parse.urlencode(
        {
            "service": "registry.docker.io",
            "scope": f"repository:{UPSTREAM_REGISTRY_REPOSITORY}:pull",
        }
    )
    payload, _ = _request_json(f"https://auth.docker.io/token?{query}")
    token = payload.get("token") if isinstance(payload, dict) else None
    _require(isinstance(token, str) and token, "无法取得Docker Hub匿名只读令牌")
    return token


def _registry_get(token: str, kind: str, reference: str) -> tuple[dict[str, Any], str, str]:
    url = f"https://registry-1.docker.io/v2/{UPSTREAM_REGISTRY_REPOSITORY}/{kind}/{reference}"
    headers = {"Authorization": f"Bearer {token}"}
    if kind == "manifests":
        headers["Accept"] = MANIFEST_ACCEPT
    payload, response_headers = _request_json(url, headers=headers)
    _require(isinstance(payload, dict), "Registry响应必须是JSON对象")
    content_digest = response_headers.get("Docker-Content-Digest", "")
    content_type = response_headers.get_content_type()
    return payload, content_digest, content_type


def _parse_official_metadata(text: str, expected_tag: str = "17") -> dict[str, str]:
    global_git_repository = ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        fields: dict[str, str] = {}
        last_key = ""
        for line in paragraph.splitlines():
            if line.startswith(" ") and last_key:
                fields[last_key] += " " + line.strip()
                continue
            key, separator, value = line.partition(":")
            if separator:
                last_key = key.strip()
                fields[last_key] = value.strip()
        if fields.get("GitRepo"):
            global_git_repository = fields["GitRepo"]
        tags = {tag.strip() for tag in fields.get("Tags", "").split(",")}
        if expected_tag in tags:
            git_repository = fields.get("GitRepo", global_git_repository)
            _require(
                git_repository == "https://github.com/docker-library/postgres.git",
                "17标签不是docker-library/postgres官方源码定义",
            )
            _require(
                bool(COMMIT.fullmatch(fields.get("GitCommit", ""))), "官方定义缺少固定GitCommit"
            )
            return {
                "git_repository": git_repository,
                "git_commit": fields["GitCommit"],
                "directory": fields.get("Directory", ""),
                "tags": fields.get("Tags", ""),
            }
    raise SupplyChainError(f"Docker Official Images元数据中没有找到精确{expected_tag}标签")


def _platforms(index: dict[str, Any]) -> list[dict[str, Any]]:
    manifests = index.get("manifests")
    _require(isinstance(manifests, list) and manifests, "上游索引缺少平台manifest")
    result = []
    for descriptor in manifests:
        _require(isinstance(descriptor, dict), "平台descriptor格式无效")
        platform = descriptor.get("platform") or {}
        digest = descriptor.get("digest", "")
        _require(DIGEST.fullmatch(digest) is not None, "平台descriptor digest无效")
        result.append(
            {
                "digest": digest,
                "media_type": descriptor.get("mediaType", ""),
                "os": platform.get("os", "unknown"),
                "architecture": platform.get("architecture", "unknown"),
                "variant": platform.get("variant"),
            }
        )
    return result


def build_upstream_evidence(
    *,
    index: dict[str, Any],
    registry_digest: str,
    registry_content_type: str,
    tag_17_digest: str,
    official_metadata: dict[str, str],
    amd64_manifest: dict[str, Any],
    amd64_descriptor_digest: str,
    amd64_config: dict[str, Any],
    fixed_digest: str = UPSTREAM_DIGEST,
    observed_tag: str = "17",
) -> dict[str, Any]:
    _require(DIGEST.fullmatch(fixed_digest) is not None, "候选固定digest无效")
    _require(registry_digest == fixed_digest, "固定digest的Registry响应不一致")
    _require(registry_content_type in INDEX_MEDIA_TYPES, "固定制品不是OCI/Docker多平台索引")
    _require(index.get("mediaType") in INDEX_MEDIA_TYPES, "索引mediaType不受支持")
    platforms = _platforms(index)
    amd64 = [
        item for item in platforms if item["os"] == "linux" and item["architecture"] == "amd64"
    ]
    _require(len(amd64) == 1, "固定索引必须且只能包含一个linux/amd64运行镜像")
    _require(amd64[0]["digest"] == amd64_descriptor_digest, "linux/amd64 descriptor不一致")
    config_descriptor = amd64_manifest.get("config") or {}
    _require(
        config_descriptor.get("digest") and DIGEST.fullmatch(config_descriptor["digest"]),
        "linux/amd64 manifest缺少有效config digest",
    )
    env_values = (amd64_config.get("config") or {}).get("Env") or []
    env = {
        key: value
        for item in env_values
        if isinstance(item, str) and "=" in item
        for key, value in [item.split("=", 1)]
    }
    _require(env.get("PG_MAJOR") == "17", "linux/amd64配置未声明PG_MAJOR=17")
    _require(
        env.get("PG_VERSION", "").startswith("17."), "linux/amd64配置缺少PostgreSQL 17版本证据"
    )
    _require(DIGEST.fullmatch(tag_17_digest) is not None, "当前17标签digest无效")
    tag_matches = tag_17_digest == fixed_digest
    return {
        "schema_version": 1,
        "artifact_kind": "docker_official_image_fixed_digest_verification",
        "generated_at": _now(),
        "description_zh": "Docker Official Image postgres固定上游制品核验证据，不代表GHCR复制品由SmartScan构建或由Docker官方发布。",
        "upstream": {
            "repository": UPSTREAM_REPOSITORY,
            "registry_namespace": "library/postgres",
            "fixed_digest": fixed_digest,
            "media_type": registry_content_type,
            "tag_17": {
                "observed_tag": observed_tag,
                "observed_digest": tag_17_digest,
                "matches_fixed_digest": tag_matches,
                "relation_zh": (
                    "当前可变17标签仍指向固定候选"
                    if tag_matches
                    else "当前可变17标签已移动；固定候选仍由镜像配置证明属于PostgreSQL 17"
                ),
            },
            "official_images": official_metadata,
        },
        "platforms": platforms,
        "linux_amd64": {
            "manifest_digest": amd64_descriptor_digest,
            "config_digest": config_descriptor["digest"],
            "pg_major": env["PG_MAJOR"],
            "pg_version": env["PG_VERSION"],
        },
        "index_manifest": index,
    }


def inspect_upstream(
    output_dir: Path,
    *,
    fixed_digest: str = UPSTREAM_DIGEST,
    observed_tag: str = "17",
) -> dict[str, Any]:
    token = _docker_token()
    index, digest, content_type = _registry_get(token, "manifests", fixed_digest)
    _, tag_17_digest, _ = _registry_get(token, "manifests", observed_tag)
    platforms = _platforms(index)
    amd64_descriptor = next(
        item for item in platforms if item["os"] == "linux" and item["architecture"] == "amd64"
    )
    amd64_manifest, child_digest, _ = _registry_get(token, "manifests", amd64_descriptor["digest"])
    _require(child_digest == amd64_descriptor["digest"], "linux/amd64 manifest响应digest不一致")
    config_digest = (amd64_manifest.get("config") or {}).get("digest", "")
    _require(DIGEST.fullmatch(config_digest) is not None, "linux/amd64 config digest无效")
    amd64_config, config_response_digest, _ = _registry_get(token, "blobs", config_digest)
    if config_response_digest:
        _require(config_response_digest == config_digest, "linux/amd64 config响应digest不一致")
    official_text = _request_text(OFFICIAL_IMAGES_METADATA)
    official = _parse_official_metadata(official_text, observed_tag)
    official["metadata_url"] = OFFICIAL_IMAGES_METADATA
    official["metadata_sha256"] = hashlib.sha256(official_text.encode()).hexdigest()
    evidence = build_upstream_evidence(
        index=index,
        registry_digest=digest,
        registry_content_type=content_type,
        tag_17_digest=tag_17_digest,
        official_metadata=official,
        amd64_manifest=amd64_manifest,
        amd64_descriptor_digest=amd64_descriptor["digest"],
        amd64_config=amd64_config,
        fixed_digest=fixed_digest,
        observed_tag=observed_tag,
    )
    _write_json(output_dir / "upstream-verification.json", evidence)
    print(
        json.dumps(
            {
                "result": "passed",
                "upstream_digest": fixed_digest,
                "observed_tag": observed_tag,
                "tag_17_digest": tag_17_digest,
                "tag_17_matches": tag_17_digest == fixed_digest,
                "platform_count": len(evidence["platforms"]),
                "linux_amd64": True,
                "pg_version": evidence["linux_amd64"]["pg_version"],
            },
            ensure_ascii=False,
        )
    )
    return evidence


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupplyChainError(f"无法读取JSON证据：{path.name}") from exc


def extract_destination(metadata_path: Path, github_output: Path) -> str:
    metadata = _load_json(metadata_path)
    digest = (metadata.get("containerimage.descriptor") or {}).get("digest", "")
    _require(DIGEST.fullmatch(digest) is not None, "复制元数据缺少目标固定digest")
    with github_output.open("a", encoding="utf-8") as stream:
        stream.write(f"digest={digest}\n")
    print(json.dumps({"result": "passed", "destination_digest": digest}))
    return digest


def finalize(
    *,
    upstream_evidence_path: Path,
    destination_index_path: Path,
    destination_digest: str,
    source_commit: str,
    workflow_run_url: str,
    output_dir: Path,
) -> dict[str, Any]:
    _require(DIGEST.fullmatch(destination_digest) is not None, "GHCR目标digest无效")
    _require(COMMIT.fullmatch(source_commit) is not None, "来源提交必须是完整SHA")
    _require(workflow_run_url.startswith("https://github.com/"), "Actions运行URL无效")
    upstream = _load_json(upstream_evidence_path)
    destination_index = _load_json(destination_index_path)
    _require(
        upstream.get("upstream", {}).get("fixed_digest") == UPSTREAM_DIGEST,
        "上游证据未绑定批准的固定digest",
    )
    _require(
        destination_index == upstream.get("index_manifest"),
        "GHCR索引结构与固定上游索引不一致",
    )
    same_digest = destination_digest == UPSTREAM_DIGEST
    copied_at = _now()
    mapping = {
        "schema_version": 1,
        "artifact_kind": "fixed_upstream_artifact_copy",
        "description_zh": "固定Docker Official Image上游制品的内容寻址复制；不是源码重建，不声称由SmartScan构建或由Docker官方在GHCR发布。",
        "copied_at": copied_at,
        "workflow_run_url": workflow_run_url,
        "source_commit": source_commit,
        "upstream": {
            "repository": UPSTREAM_REPOSITORY,
            "digest": UPSTREAM_DIGEST,
            "tag_17": upstream["upstream"]["tag_17"],
            "official_images": upstream["upstream"]["official_images"],
        },
        "destination": {
            "repository": DESTINATION_REPOSITORY,
            "digest": destination_digest,
            "immutable_ref": f"{DESTINATION_REPOSITORY}@{destination_digest}",
            "visibility": "private_pending_manual_publication_check",
        },
        "manifest_relation": {
            "same_digest": same_digest,
            "same_index_structure": True,
            "explanation_zh": (
                "GHCR与上游顶层manifest字节身份一致，因此固定digest相同。"
                if same_digest
                else "顶层索引结构一致，但Registry序列化产生不同digest；必须按各自Registry的固定digest追溯。"
            ),
        },
        "platforms": upstream["platforms"],
        "linux_amd64": upstream["linux_amd64"],
        "evidence": {
            "sbom": "postgres-linux-amd64.spdx.json",
            "critical_all": "postgres-critical-all.json",
            "high_critical_fixable": "postgres-high-critical-fixable.json",
            "high_all_risk_review": "postgres-high-all.json",
        },
    }
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": DESTINATION_REPOSITORY,
                "digest": {"sha256": destination_digest.removeprefix("sha256:")},
            }
        ],
        "predicateType": "https://github.com/j4meshub/SmartScan/attestations/upstream-copy/v1",
        "predicate": {
            "operation": "fixed_upstream_artifact_copy",
            "buildType": "registry-copy-without-rebuild",
            "source": {
                "repository": UPSTREAM_REPOSITORY,
                "digest": UPSTREAM_DIGEST,
            },
            "invocation": {
                "sourceCommit": source_commit,
                "workflowRun": workflow_run_url,
            },
            "metadata": {
                "copiedAt": copied_at,
                "layersModified": False,
                "sourceCodeRebuilt": False,
                "dockerOfficialGhcrPublicationClaimed": False,
            },
        },
    }
    markdown = "\n".join(
        [
            "# PostgreSQL 固定上游制品复制清单",
            "",
            f"- 上游：`{UPSTREAM_REPOSITORY}@{UPSTREAM_DIGEST}`",
            f"- GHCR：`{DESTINATION_REPOSITORY}@{destination_digest}`",
            f"- 当前17标签：`{upstream['upstream']['tag_17']['observed_digest']}`",
            f"- digest是否相同：`{'是' if same_digest else '否'}`",
            f"- 平台数：`{len(upstream['platforms'])}`（包含 `linux/amd64`）",
            f"- PostgreSQL版本证据：`{upstream['linux_amd64']['pg_version']}`",
            f"- 复制时间：`{copied_at}`",
            f"- Actions运行：`{workflow_run_url}`",
            f"- 源提交：`{source_commit}`",
            "",
            "> 本制品是固定上游镜像复制，不是SmartScan源码构建，也不是Docker官方在GHCR发布。首次推送后必须人工检查并设为公开；在用户明确接受前不得进入UAT配置。",
            "",
        ]
    )
    _write_json(output_dir / "postgres-source-mapping.json", mapping)
    _write_json(output_dir / "postgres-source-mapping.intoto.json", statement)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "postgres-source-mapping.md").write_text(markdown, encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "passed",
                "destination_digest": destination_digest,
                "same_digest": same_digest,
            }
        )
    )
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="核验PostgreSQL固定上游制品和GHCR复制证据")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser(
        "inspect-upstream", help="只读核验Docker Official Image固定制品"
    )
    inspect.add_argument("--output-dir", type=Path, required=True)
    inspect.add_argument("--digest", default=UPSTREAM_DIGEST)
    inspect.add_argument("--tag", default="17")

    extract = subparsers.add_parser("extract-destination", help="从Buildx元数据读取GHCR固定digest")
    extract.add_argument("--metadata", type=Path, required=True)
    extract.add_argument("--github-output", type=Path, required=True)

    finish = subparsers.add_parser("finalize", help="生成中文来源映射和in-toto声明")
    finish.add_argument("--upstream-evidence", type=Path, required=True)
    finish.add_argument("--destination-index", type=Path, required=True)
    finish.add_argument("--destination-digest", required=True)
    finish.add_argument("--source-commit", required=True)
    finish.add_argument("--workflow-run-url", required=True)
    finish.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "inspect-upstream":
        inspect_upstream(args.output_dir, fixed_digest=args.digest, observed_tag=args.tag)
    elif args.command == "extract-destination":
        extract_destination(args.metadata, args.github_output)
    else:
        finalize(
            upstream_evidence_path=args.upstream_evidence,
            destination_index_path=args.destination_index,
            destination_digest=args.destination_digest,
            source_commit=args.source_commit,
            workflow_run_url=args.workflow_run_url,
            output_dir=args.output_dir,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
