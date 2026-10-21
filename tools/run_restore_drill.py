"""按备份证据中的精确快照执行隔离恢复演练。"""

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

from tools.backup_evidence import atomic_write_json, load_successful_backup
from tools.validate_backup_config import validate_backup_config
from tools.validate_staging_config import PROJECT_ROOT, load_env_file, validate_staging_config

BASE_COMPOSE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.staging.yml"
BACKUP_COMPOSE = PROJECT_ROOT / "deploy" / "compose" / "docker-compose.backup.yml"


def _is_successful_evidence(path: Path) -> bool:
    try:
        load_successful_backup(path)
    except Exception:
        return False
    return True


def _run(command: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(command, check=True, env=env, capture_output=True, text=True)
    return result.stdout


def execute_drill(
    deploy_env: Path, backup_env: Path, password_file: Path, evidence: Path
) -> dict[str, object]:
    validate_staging_config(deploy_env, require_host_paths=True)
    config = validate_backup_config(deploy_env, backup_env, password_file, require_host_paths=True)
    backup = load_successful_backup(evidence)
    deploy = load_env_file(deploy_env)
    restore_root = Path(deploy["SMARTSCAN_STAGING_RESTORE_ROOT"])
    evidence_root = Path(deploy["SMARTSCAN_STAGING_BACKUP_EVIDENCE_ROOT"])
    drill_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + backup["git_commit"][:12]
    target = (restore_root / drill_id).resolve()
    if target.parent != restore_root.resolve() or target.exists():
        raise RuntimeError("恢复演练目录无效或已存在")
    target.mkdir(mode=0o700)
    env = os.environ.copy()
    env["SMARTSCAN_RESTORE_DRILL_ID"] = drill_id
    env["COMPOSE_PROJECT_NAME"] = f"smartscan-restore-{drill_id.casefold()}"
    base = [
        "docker",
        "compose",
        "--env-file",
        str(deploy_env),
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(BACKUP_COMPOSE),
        "--profile",
        "restore",
    ]
    started = time.monotonic()
    stage = "restore_snapshots"
    try:
        for snapshot in backup["snapshots"].values():
            _run(
                base
                + [
                    "run",
                    "--rm",
                    "backup-restic",
                    "restore",
                    snapshot,
                    "--target",
                    f"/restore/{drill_id}",
                ],
                env,
            )
        stage = "start_database"
        _run(base + ["up", "-d", "--wait", "restore-database"], env)
        stage = "verify_consistency"
        audit_output = _run(base + ["run", "--rm", "restore-audit"], env)
        verification_path = evidence_root / f"{drill_id}.json"
        try:
            verification = json.loads(
                next(line for line in reversed(audit_output.splitlines()) if line.strip())
            )
        except (StopIteration, json.JSONDecodeError) as exc:
            raise RuntimeError("恢复审计未返回有效证据") from exc
        elapsed = round(time.monotonic() - started, 3)
        verification.update(
            {
                "drill_id": drill_id,
                "backup_run_id": backup["run_id"],
                "snapshot_ids": backup["snapshots"],
                "duration_seconds": elapsed,
                "rto_target_hours": config.rto_hours,
                "rto_met": elapsed <= config.rto_hours * 3600,
            }
        )
        if not verification["rto_met"]:
            raise RuntimeError("恢复演练超过 RTO 目标")
        atomic_write_json(verification_path, verification)
        return verification
    except Exception:
        atomic_write_json(
            evidence_root / f"restore-failed-{drill_id}.json",
            {
                "schema_version": 1,
                "status": "failed",
                "drill_id": drill_id,
                "backup_run_id": backup["run_id"],
                "failed_stage": stage,
                "duration_seconds": round(time.monotonic() - started, 3),
                "secrets_included": False,
            },
        )
        raise
    finally:
        subprocess.run(base + ["down", "--remove-orphans"], env=env, check=False)
        if target.parent == restore_root.resolve() and target.exists():
            shutil.rmtree(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 SmartScan 月度隔离恢复演练")
    parser.add_argument("--deploy-env", required=True, type=Path)
    parser.add_argument("--backup-env", required=True, type=Path)
    parser.add_argument("--password-file", required=True, type=Path)
    evidence_group = parser.add_mutually_exclusive_group(required=True)
    evidence_group.add_argument("--backup-evidence", type=Path)
    evidence_group.add_argument("--latest-evidence", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ci-fixture", action="store_true", help="仅允许仓库合成测试夹具")
    args = parser.parse_args()
    evidence = args.backup_evidence
    if evidence is None:
        candidates = sorted(args.latest_evidence.glob("backup-*.json"), reverse=True)
        evidence = next(
            (item for item in candidates if _is_successful_evidence(item)),
            None,
        )
        if evidence is None:
            raise RuntimeError("没有可用于恢复演练的成功备份证据")
    load_successful_backup(evidence)
    if not args.execute:
        validate_backup_config(
            args.deploy_env,
            args.backup_env,
            args.password_file,
            ci_fixture=args.ci_fixture,
        )
        print(json.dumps({"status": "validated", "secrets_included": False}))
        return 0
    if sys.platform != "linux":
        raise RuntimeError("真实恢复演练只能在目标 Linux staging 主机执行")
    result = execute_drill(
        args.deploy_env.resolve(),
        args.backup_env.resolve(),
        args.password_file.resolve(),
        evidence.resolve(),
    )
    print(json.dumps({"status": result["status"], "drill_id": result["drill_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
