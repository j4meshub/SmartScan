from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "deploy/ocr-models/source-lock.json"
WORKFLOW = ROOT / ".github/workflows/ocr-model-supply-chain.yml"
EXECUTOR = ROOT / "deploy/ops/smartscan-uat-ocr-model"
HELPER = ROOT / "deploy/ops/smartscan_uat_ocr_model.py"
SUDOERS = ROOT / "deploy/ops/smartscan-uat-ocr-model.sudoers"


def test_official_sources_and_exact_hashes_are_locked() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert lock["artifact_version"] == "PP-OCRv6-small-v1"
    assert lock["upstream"] == {
        "project": "PaddlePaddle/PaddleOCR",
        "tag": "v3.7.0",
        "commit": "b03f46425e8ff4442b268ce449e3eef758146cd4",
        "license": "Apache-2.0",
        "license_url": "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/v3.7.0/LICENSE",
    }
    for model in lock["models"].values():
        assert model["url"].startswith("https://paddle-model-ecology.bj.bcebos.com/")
        assert re.fullmatch(r"[a-f0-9]{64}", model["archive_sha256"])
        assert re.fullmatch(r"[a-f0-9]{40}", model["huggingface_commit"])
        assert set(model["files"]) == {
            "inference.json",
            "inference.pdiparams",
            "inference.yml",
        }


def test_workflow_pr_never_publishes_and_main_uses_minimal_permissions() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "docs/**" not in workflow[True]["pull_request"]["paths"]
    assert "deploy/ocr-models/**" in workflow[True]["pull_request"]["paths"]
    assert workflow[True]["push"]["paths"] == workflow[True]["pull_request"]["paths"]
    verify = workflow["jobs"]["verify"]
    publish = workflow["jobs"]["publish"]
    assert verify["permissions"] == {"contents": "read"}
    assert "github.event_name == 'push'" in publish["if"]
    assert publish["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    text = WORKFLOW.read_text(encoding="utf-8")
    assert ":latest" not in text
    assert "provenance: mode=max" in text
    assert "sbom: true" in text
    assert "real-cpu-evidence.json" in text
    for action in re.findall(r"uses:\s*([^\s]+)", text):
        assert re.search(r"@[a-f0-9]{40}(?:\s|$)", action)


def test_restricted_installer_has_only_three_exact_commands() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    sudoers = SUDOERS.read_text(encoding="utf-8")
    helper_digest = hashlib.sha256(HELPER.read_bytes()).hexdigest()
    assert helper_digest in executor
    for action in ("install", "verify", "status"):
        assert f"smartscan-uat-ocr-model {action}" in sudoers
    for forbidden in (" bash", " sh", "*", " rm", "curl", "wget", "docker", "prune"):
        assert forbidden not in sudoers.lower()
    assert EXECUTOR.stat().st_size > 0 and HELPER.stat().st_size > 0
    assert "[[ $# -eq 1 ]]" in executor
    assert "install|verify|status" in executor
    assert "/mnt/data/smartscan/uat/models/.ocr-staging/PP-OCRv6-small-v1" in HELPER.read_text(
        encoding="utf-8"
    )


def test_license_and_notice_are_preserved() -> None:
    license_text = (ROOT / "deploy/ocr-models/LICENSE").read_text(encoding="utf-8")
    notice = (ROOT / "deploy/ocr-models/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Apache License" in license_text and "Version 2.0" in license_text
    assert "PaddlePaddle/PaddleOCR" in notice
    assert "没有独立 `NOTICE`" in notice
