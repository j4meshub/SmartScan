#!/usr/bin/env python3
"""通过固定SSH别名以内存载荷运行UAT仓库外证据生成器。"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

try:
    from tools.shared_host_preflight import PreflightError, _bootstrap_networks
except ModuleNotFoundError:  # 允许从仓库根直接执行python tools/<脚本>
    from shared_host_preflight import PreflightError, _bootstrap_networks  # type: ignore[no-redef]

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parents[1]
GENERATOR = ROOT / "tools" / "shared_host_preflight.py"
SSH_ALIAS = "smartscan-server"
REMOTE_COMMAND = "python3 -c " + shlex.quote(
    "import hashlib,io,sys;"
    "n=int(sys.stdin.buffer.readline());"
    "src=sys.stdin.buffer.read(n);"
    "spec=sys.stdin.buffer.read();"
    "sys.argv=['shared_host_preflight.py','prepare-bootstrap'];"
    "sys.stdin=io.TextIOWrapper(io.BytesIO(spec),encoding='utf-8');"
    "ns={'__name__':'__main__','__file__':'shared_host_preflight.py',"
    "'__generator_sha256__':hashlib.sha256(src).hexdigest()};"
    "exec(compile(src,'shared_host_preflight.py','exec'),ns,ns)"
)
Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def build_payload(spec_raw: bytes, *, generator: Path = GENERATOR) -> bytes:
    try:
        spec = json.loads(spec_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreflightError("input_invalid", "标准输入不是有效引导JSON") from exc
    if not isinstance(spec, dict):
        raise PreflightError("input_invalid", "引导输入根节点必须是对象")
    _bootstrap_networks(spec)
    source = generator.read_bytes()
    return str(len(source)).encode("ascii") + b"\n" + source + spec_raw


def run_prepare(
    spec_raw: bytes,
    *,
    runner: Runner = subprocess.run,
) -> int:
    payload = build_payload(spec_raw)
    completed = runner(
        ["ssh", SSH_ALIAS, REMOTE_COMMAND],
        input=payload,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
        check=False,
    )
    return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare",))
    arguments = parser.parse_args()
    if arguments.command != "prepare":  # pragma: no cover - argparse已限制
        return 64
    try:
        return run_prepare(sys.stdin.buffer.read())
    except (OSError, PreflightError) as exc:
        print(
            json.dumps(
                {"status": "failed", "message": str(exc), "contains_sensitive_data": False},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
