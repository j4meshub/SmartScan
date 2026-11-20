from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from services.api.app.config import Settings
from services.worker.app.ocr import validate_model_pack
from tools.ocr_model_artifact import ArtifactError, assemble, verify


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive(path: Path, root: str, files: dict[str, bytes], *, symlink: bool = False) -> bytes:
    with tarfile.open(path, "w:") as bundle:
        for name, value in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(value)
            bundle.addfile(info, io.BytesIO(value))
        if symlink:
            info = tarfile.TarInfo(f"{root}/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            bundle.addfile(info)
    return path.read_bytes()


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "LICENSE").write_text("Apache-2.0", encoding="utf-8")
    (evidence / "THIRD_PARTY_NOTICES.md").write_text("PaddleOCR", encoding="utf-8")
    (evidence / "UPSTREAM_MODEL_DESCRIPTION.md").write_text("PP-OCRv6", encoding="utf-8")
    model_files = {
        "inference.json": b"json",
        "inference.pdiparams": b"weights",
        "inference.yml": b"config",
    }
    det = tmp_path / "det.tar"
    rec = tmp_path / "rec.tar"
    det_bytes = _archive(det, "det_infer", model_files)
    rec_bytes = _archive(rec, "rec_infer", model_files)

    def model(name: str, root: str, archive: bytes) -> dict[str, object]:
        return {
            "name": name,
            "archive_root": root,
            "url": "https://official.example/model.tar",
            "archive_sha256": _sha(archive),
            "archive_size": len(archive),
            "huggingface_repo": f"PaddlePaddle/{name}",
            "huggingface_commit": "a" * 40,
            "files": {
                filename: {"sha256": _sha(value), "size": len(value)}
                for filename, value in model_files.items()
            },
        }

    lock = {
        "schema_version": 1,
        "artifact_version": "PP-OCRv6-small-v1",
        "runtime": {
            "backend": "paddle_static",
            "paddleocr_version": "3.7.0",
            "paddlepaddle_version": "3.3.1",
        },
        "upstream": {"license": "Apache-2.0", "commit": "b" * 40},
        "models": {
            "detection": model("PP-OCRv6_small_det", "det_infer", det_bytes),
            "recognition": model("PP-OCRv6_small_rec", "rec_infer", rec_bytes),
        },
    }
    lock_path = evidence / "source-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return lock_path, det, rec


def test_assemble_and_verify_offline_artifact(tmp_path: Path) -> None:
    lock, det, rec = _inputs(tmp_path)
    output = tmp_path / "package"
    manifest = assemble(lock, det, rec, output)
    assert manifest["schema_version"] == 1
    assert manifest["conversion"]["performed"] is False
    assert verify(output)["status"] == "passed"
    assert set(manifest["files"]) == {
        f"{directory}/{name}"
        for directory in ("PP-OCRv6_small_det", "PP-OCRv6_small_rec")
        for name in ("inference.json", "inference.pdiparams", "inference.yml")
    }
    settings = Settings(_env_file=None, ocr_model_root=output)
    assert validate_model_pack(settings) == (
        output / "PP-OCRv6_small_det",
        output / "PP-OCRv6_small_rec",
    )


@pytest.mark.parametrize("failure", ["missing", "extra", "tamper", "symlink", "manifest"])
def test_verify_rejects_invalid_artifacts(tmp_path: Path, failure: str) -> None:
    lock, det, rec = _inputs(tmp_path)
    output = tmp_path / "package"
    assemble(lock, det, rec, output)
    target = output / "PP-OCRv6_small_det" / "inference.json"
    if failure == "missing":
        target.unlink()
    elif failure == "extra":
        (output / "extra.bin").write_bytes(b"extra")
    elif failure == "tamper":
        target.write_bytes(b"tampered")
    elif failure == "symlink":
        target.unlink()
        try:
            target.symlink_to(output / "LICENSE")
        except OSError:
            pytest.skip("当前平台不允许创建测试符号链接")
    else:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        manifest["schema_version"] = 99
        (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactError):
        verify(output)


def test_assemble_rejects_unsafe_archive(tmp_path: Path) -> None:
    lock, det, rec = _inputs(tmp_path)
    data = _archive(
        det,
        "det_infer",
        {
            "inference.json": b"json",
            "inference.pdiparams": b"weights",
            "inference.yml": b"config",
        },
        symlink=True,
    )
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    lock_data["models"]["detection"]["archive_sha256"] = _sha(data)
    lock_data["models"]["detection"]["archive_size"] = len(data)
    lock.write_text(json.dumps(lock_data), encoding="utf-8")
    with pytest.raises(ArtifactError, match="不安全"):
        assemble(lock, det, rec, tmp_path / "package")
