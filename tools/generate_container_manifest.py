"""生成不含凭据的 SmartScan 容器镜像发布清单。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SERVICES = ("ai-gateway", "api", "ops", "web", "worker")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
IMAGE = re.compile(r"^ghcr\.io/j4meshub/smartscan-[a-z0-9-]+$")


class ContainerManifestError(ValueError):
    """容器发布清单不满足失败关闭要求。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContainerManifestError(message)


def build_entry(
    *,
    service: str,
    image: str,
    digest: str,
    source_commit: str,
    sbom_artifact: str,
) -> dict[str, Any]:
    _require(service in SERVICES, "服务名称不在允许列表")
    _require(IMAGE.fullmatch(image) is not None, "GHCR 镜像名称无效")
    _require(image.endswith(f"smartscan-{service}"), "服务与镜像名称不匹配")
    _require(DIGEST.fullmatch(digest) is not None, "镜像 digest 无效")
    _require(COMMIT.fullmatch(source_commit) is not None, "源提交必须是完整 SHA")
    _require(
        sbom_artifact == f"container-evidence-{service}",
        "SBOM Artifact 名称与服务不匹配",
    )
    return {
        "service": service,
        "image": image,
        "digest": digest,
        "immutable_ref": f"{image}@{digest}",
        "source_commit": source_commit,
        "sbom_artifact": sbom_artifact,
    }


def _read_entry(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContainerManifestError(f"无法读取镜像条目：{path.name}") from exc
    _require(isinstance(value, dict), f"镜像条目必须是对象：{path.name}")
    return build_entry(
        service=value.get("service"),
        image=value.get("image"),
        digest=value.get("digest"),
        source_commit=value.get("source_commit"),
        sbom_artifact=value.get("sbom_artifact"),
    )


def combine_entries(entries_dir: Path) -> dict[str, Any]:
    entries = [_read_entry(path) for path in sorted(entries_dir.glob("*.json"))]
    _require(entries, "没有找到镜像条目")
    services = [entry["service"] for entry in entries]
    _require(len(services) == len(set(services)), "镜像条目包含重复服务")
    _require(tuple(sorted(services)) == SERVICES, "镜像条目必须完整覆盖五类服务")
    commits = {entry["source_commit"] for entry in entries}
    _require(len(commits) == 1, "镜像条目的源提交不一致")
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_commit": commits.pop(),
        "registry": "ghcr.io",
        "visibility": "public_pending_manual_confirmation",
        "deployment_mode": "manual_digest_only",
        "images": sorted(entries, key=lambda item: item["service"]),
        "secrets_included": False,
    }


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# SmartScan 容器镜像发布清单",
        "",
        f"- 源提交：`{manifest['source_commit']}`",
        "- Registry：`ghcr.io`",
        "- 可见性：首次发布后等待人工检查并设为公开",
        "- 部署方式：仅允许人工按 digest 拉取",
        "",
        "| 服务 | 不可变镜像 | SBOM 证据 |",
        "|---|---|---|",
    ]
    for image in manifest["images"]:
        lines.append(
            f"| {image['service']} | `{image['immutable_ref']}` | `{image['sbom_artifact']}` |"
        )
    lines.extend(
        [
            "",
            "> `main` 等可变标签只用于识别，不得用于 UAT 或生产部署。",
            "",
        ]
    )
    return "\n".join(lines)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 SmartScan 容器镜像发布清单")
    subparsers = parser.add_subparsers(dest="command", required=True)

    entry = subparsers.add_parser("entry", help="生成单个服务的镜像条目")
    entry.add_argument("--service", required=True, choices=SERVICES)
    entry.add_argument("--image", required=True)
    entry.add_argument("--digest", required=True)
    entry.add_argument("--source-commit", required=True)
    entry.add_argument("--sbom-artifact", required=True)
    entry.add_argument("--output", required=True, type=Path)

    combine = subparsers.add_parser("combine", help="合并五个服务的发布清单")
    combine.add_argument("--entries-dir", required=True, type=Path)
    combine.add_argument("--output-json", required=True, type=Path)
    combine.add_argument("--output-markdown", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "entry":
        value = build_entry(
            service=args.service,
            image=args.image,
            digest=args.digest,
            source_commit=args.source_commit,
            sbom_artifact=args.sbom_artifact,
        )
        _write(args.output, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        return 0

    manifest = combine_entries(args.entries_dir)
    _write(args.output_json, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _write(args.output_markdown, render_markdown(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
