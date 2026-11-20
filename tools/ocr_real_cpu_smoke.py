from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from services.api.app.config import Settings
from services.worker.app.ocr import PaddleOcrEngine

try:
    import resource
except ImportError:  # pragma: no cover - 真实CPU门禁运行在Linux
    resource = None  # type: ignore[assignment]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _disable_network() -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("real_ocr_runtime_network_forbidden")

    socket.create_connection = denied  # type: ignore[assignment]
    original_socket = socket.socket

    class OfflineSocket(original_socket):
        def connect(self, _address: object) -> None:
            denied()

        def connect_ex(self, _address: object) -> int:
            denied()
            return 1

    socket.socket = OfflineSocket  # type: ignore[assignment,misc]


def _settings(model_root: Path) -> Settings:
    return Settings(
        _env_file=None,
        ocr_model_root=model_root,
        ocr_model_version="PP-OCRv6-small-v1",
        ocr_package_version="3.7.0",
        ocr_engine_version="3.3.1",
        ocr_cpu_threads=2,
    )


def run_one(model_root: str, sample_path: str) -> dict[str, object]:
    _disable_network()
    started = time.perf_counter()
    engine = PaddleOcrEngine(_settings(Path(model_root)))
    with Image.open(sample_path) as image:
        lines = engine.recognize(image)
    elapsed = time.perf_counter() - started
    return {
        "text": "\n".join(line.text for line in lines),
        "line_count": len(lines),
        "elapsed_seconds": round(elapsed, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None,
    }


def run(model_root: Path, samples_root: Path, sample_manifest: Path) -> dict[str, object]:
    source = json.loads(sample_manifest.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    for sample in source["samples"]:
        path = samples_root / f"{sample['id']}{Path(sample['url']).suffix}"
        if (
            not path.is_file()
            or path.stat().st_size != sample["size"]
            or _sha256(path) != sample["sha256"]
        ):
            raise RuntimeError(f"real_sample_invalid:{sample['id']}")
        result = run_one(str(model_root), str(path))
        normalized = str(result["text"]).casefold()
        if not any(str(value).casefold() in normalized for value in sample["expected_any"]):
            raise RuntimeError(f"real_sample_expectation_failed:{sample['id']}")
        results.append({"id": sample["id"], **result})
    concurrency_sample = samples_root / "zh-cn.png"
    with ProcessPoolExecutor(max_workers=2) as executor:
        concurrent = list(
            executor.map(
                run_one,
                (str(model_root), str(model_root)),
                (str(concurrency_sample), str(concurrency_sample)),
            )
        )
    if any(not item["line_count"] for item in concurrent):
        raise RuntimeError("concurrent_worker_result_empty")
    return {
        "status": "passed",
        "runtime": "paddle_static/cpu",
        "network": "blocked",
        "samples": results,
        "two_worker_concurrency": concurrent,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartScan真实离线OCR CPU验收")
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = run(args.model_root, args.samples_root, args.sample_manifest)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "passed", "samples": 3, "workers": 2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
