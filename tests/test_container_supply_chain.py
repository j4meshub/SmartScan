import json
import re
from pathlib import Path

import pytest
import yaml

from tools.generate_container_manifest import (
    SERVICES,
    ContainerManifestError,
    build_entry,
    combine_entries,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container-publish.yml"


def _entry(service: str, commit: str = "a" * 40) -> dict[str, object]:
    return build_entry(
        service=service,
        image=f"ghcr.io/j4meshub/smartscan-{service}",
        digest=f"sha256:{service.encode().hex().ljust(64, '0')[:64]}",
        source_commit=commit,
        sbom_artifact=f"container-evidence-{service}",
    )


def test_container_workflow_covers_five_images_and_pins_actions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow["jobs"]
    matrix = jobs["verify-images"]["strategy"]["matrix"]["include"]

    assert tuple(sorted(item["service"] for item in matrix)) == SERVICES
    for item in matrix:
        assert (ROOT / item["dockerfile"]).is_file()
        assert item["image"] == f"smartscan-{item['service']}"

    action_refs = re.findall(r"uses:\s+([^\s]+)@([^\s#]+)", text)
    assert action_refs
    assert all(re.fullmatch(r"[a-f0-9]{40}", ref) for _, ref in action_refs)


def test_pull_requests_cannot_publish_or_deploy() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in text
    assert "push: false" in text
    assert "push: true" in text
    assert "packages: write" in text
    assert "attestations: write" in text
    for forbidden in ("ssh ", "scp ", "rsync ", "docker context", "appleboy/"):
        assert forbidden not in text.lower()


def test_manifest_is_complete_sorted_and_secret_free(tmp_path: Path) -> None:
    for service in reversed(SERVICES):
        (tmp_path / f"{service}.json").write_text(json.dumps(_entry(service)), encoding="utf-8")

    manifest = combine_entries(tmp_path)

    assert [item["service"] for item in manifest["images"]] == list(SERVICES)
    assert manifest["visibility"] == "public_pending_manual_confirmation"
    assert manifest["deployment_mode"] == "manual_digest_only"
    assert manifest["secrets_included"] is False
    markdown = render_markdown(manifest)
    assert "仅允许人工按 digest 拉取" in markdown
    assert "main` 等可变标签" in markdown


def test_manifest_rejects_missing_and_mismatched_entries(tmp_path: Path) -> None:
    for service in SERVICES[:-1]:
        (tmp_path / f"{service}.json").write_text(json.dumps(_entry(service)), encoding="utf-8")
    with pytest.raises(ContainerManifestError, match="完整覆盖"):
        combine_entries(tmp_path)

    with pytest.raises(ContainerManifestError, match="服务与镜像"):
        build_entry(
            service="api",
            image="ghcr.io/j4meshub/smartscan-worker",
            digest="sha256:" + "b" * 64,
            source_commit="c" * 40,
            sbom_artifact="container-evidence-api",
        )
