"""执行 staging 加密异机备份并生成可审计证据。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.backup_evidence import KINDS, atomic_write_json
from tools.validate_backup_config import ValidatedBackupConfig, validate_backup_config
from tools.validate_staging_config import PROJECT_ROOT, load_env_file, validate_staging_config

BASE_COMPOSE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.staging.yml"
BACKUP_COMPOSE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.backup.yml"


def _utc_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _compose_base(deploy_env: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(deploy_env),
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(BACKUP_COMPOSE),
        "--profile",
        "backup",
    ]


def build_plan(deploy_env: Path, run_id: str, config: ValidatedBackupConfig) -> list[list[str]]:
    base = _compose_base(deploy_env)
    commands = [base + ["run", "--rm", "backup-database"]]
    parents = {
        "database": f"/source/database/{run_id}",
        "files": "/source",
        "wal": "/source",
    }
    paths = {
        "database": f"/source/database/{run_id}/database",
        "files": "/source/files",
        "wal": "/source/wal",
    }
    for kind in KINDS:
        commands.append(
            base
            + [
                "run",
                "--rm",
                "backup-restic",
                "backup",
                "--json",
                "--tag",
                "smartscan",
                "--tag",
                kind,
                "--parent",
                parents[kind],
                paths[kind],
            ]
        )
    for kind in KINDS:
        commands.append(
            base
            + [
                "run",
                "--rm",
                "backup-restic",
                "forget",
                "--prune",
                "--tag",
                "smartscan",
                "--tag",
                kind,
                "--group-by",
                "tags",
                "--keep-daily",
                str(config.retention_daily),
                "--keep-weekly",
                str(config.retention_weekly),
            ]
        )
    commands.append(base + ["run", "--rm", "backup-restic", "check", "--read-data-subset=5%"])
    return commands


def _run(command: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    return result.stdout


def _snapshot_id(output: str) -> str:
    for line in reversed(output.splitlines()):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("message_type") == "summary" and isinstance(item.get("snapshot_id"), str):
            value = item["snapshot_id"]
            if len(value) == 64 and all(character in "0123456789abcdef" for character in value):
                return value
    raise RuntimeError("Restic 未返回完整快照 ID")


def _safe_cleanup(root: Path, run_id: str) -> None:
    target = (root / run_id).resolve()
    resolved_root = root.resolve()
    if target.parent != resolved_root:
        raise RuntimeError("拒绝清理越界的备份工作目录")
    if target.exists():
        shutil.rmtree(target)


def execute_backup(deploy_env: Path, backup_env: Path, password_file: Path) -> dict[str, Any]:
    validate_staging_config(deploy_env, require_host_paths=True)
    config = validate_backup_config(deploy_env, backup_env, password_file, require_host_paths=True)
    commit = _git_commit()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + commit[:12]
    deploy = load_env_file(deploy_env)
    evidence_root = Path(deploy["SMARTSCAN_STAGING_BACKUP_EVIDENCE_ROOT"])
    work_root = Path(deploy["SMARTSCAN_STAGING_BACKUP_WORK_ROOT"])
    started = _utc_text()
    started_clock = time.monotonic()
    snapshots: dict[str, str] = {}
    stage = "database"
    evidence: dict[str, Any]
    env = os.environ.copy()
    env["SMARTSCAN_BACKUP_RUN_ID"] = run_id
    try:
        commands = build_plan(deploy_env.resolve(), run_id, config)
        _run(commands[0], env)
        for index, kind in enumerate(KINDS, start=1):
            stage = f"snapshot_{kind}"
            snapshots[kind] = _snapshot_id(_run(commands[index], env))
        stage = "retention"
        for command in commands[4:7]:
            _run(command, env)
        stage = "repository_check"
        _run(commands[7], env)
        evidence = {
            "schema_version": 1,
            "status": "success",
            "run_id": run_id,
            "repository": config.safe_summary(),
            "git_commit": commit,
            "started_at": started,
            "finished_at": _utc_text(),
            "duration_seconds": round(time.monotonic() - started_clock, 3),
            "snapshots": snapshots,
            "rpo_target_hours": config.rpo_hours,
            "secrets_included": False,
        }
    except Exception:
        evidence = {
            "schema_version": 1,
            "status": "failed",
            "run_id": run_id,
            "git_commit": commit,
            "failed_stage": stage,
            "started_at": started,
            "finished_at": _utc_text(),
            "duration_seconds": round(time.monotonic() - started_clock, 3),
            "secrets_included": False,
        }
        atomic_write_json(evidence_root / f"backup-{run_id}.json", evidence)
        raise
    finally:
        _safe_cleanup(work_root, run_id)
    atomic_write_json(evidence_root / f"backup-{run_id}.json", evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 SmartScan staging 加密异机备份")
    parser.add_argument("--deploy-env", required=True, type=Path)
    parser.add_argument("--backup-env", required=True, type=Path)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="通过验证后执行真实备份")
    parser.add_argument("--ci-fixture", action="store_true", help="仅允许仓库合成测试夹具")
    args = parser.parse_args()
    if not args.execute:
        config = validate_backup_config(
            args.deploy_env,
            args.backup_env,
            args.password_file,
            ci_fixture=args.ci_fixture,
        )
        print(json.dumps(config.safe_summary(), ensure_ascii=False, indent=2))
        return 0
    if sys.platform != "linux":
        raise RuntimeError("真实备份只能在目标 Linux staging 主机执行")
    evidence = execute_backup(
        args.deploy_env.resolve(), args.backup_env.resolve(), args.password_file.resolve()
    )
    print(
        json.dumps({"status": evidence["status"], "run_id": evidence["run_id"]}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
