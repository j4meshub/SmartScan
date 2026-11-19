from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EXECUTOR = ROOT / "deploy" / "ops" / "smartscan-uat-loop-storage"
MOUNT_UNIT = ROOT / "deploy" / "systemd" / "mnt-data-smartscan-uat.mount.template"
SUDOERS = ROOT / "deploy" / "sudoers" / "smartscan-uat-loop-storage"


def _sha256(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
    return hashlib.sha256(canonical).hexdigest()


def test_executor_has_fixed_security_contract() -> None:
    text = EXECUTOR.read_text(encoding="utf-8")

    assert text.startswith("#!/bin/bash\nset -euo pipefail\n")
    assert "umask 077" in text
    assert 'readonly EXPECTED_HOSTNAME="ctiecaiserver"' in text
    assert 'readonly EXPECTED_SUDO_USER="szhzx"' in text
    assert 'readonly BACKING_FILE="/mnt/data/smartscan-loop/uat.ext4"' in text
    assert 'readonly MOUNT_POINT="/mnt/data/smartscan/uat"' in text
    assert 'readonly UNIT_PATH="/etc/systemd/system/mnt-data-smartscan-uat.mount"' in text
    assert "create|verify|status|stop|recreate-empty" in text
    assert 'if [[ "$#" -ne 1 ]]' in text
    assert "docker" not in text.casefold()
    assert "nginx" not in text.casefold()
    assert 'readonly UNLINK_CMD="/usr/bin/unlink"' in text
    assert '"$UNLINK_CMD" -- "$BACKING_FILE"' in text
    assert "rm " not in text
    assert "losetup -d" not in text
    assert "$@" in text  # 只用于单次固定参数校验入口。


def test_executor_pins_reviewed_mount_unit_sha256() -> None:
    text = EXECUTOR.read_text(encoding="utf-8")
    assert f'readonly UNIT_SHA256="{_sha256(MOUNT_UNIT)}"' in text


def test_manual_upgrade_guide_pins_current_asset_sha256() -> None:
    guide = (ROOT / "docs" / "OPS001_LOOP_SUDO_EXECUTOR.md").read_text(encoding="utf-8")

    assert _sha256(EXECUTOR) in guide
    assert _sha256(MOUNT_UNIT) in guide
    assert _sha256(SUDOERS) in guide


def test_sudoers_allows_only_five_exact_commands() -> None:
    text = SUDOERS.read_text(encoding="utf-8")
    command = "/usr/local/libexec/smartscan/smartscan-uat-loop-storage"

    assert text.count(command) == 5
    for action in ("create", "verify", "status", "stop", "recreate-empty"):
        assert f"{command} {action}" in text
    assert "szhzx ALL=(root) NOPASSWD: SMARTSCAN_UAT_LOOP_STORAGE" in text
    assert "sha256:" not in text
    assert "sudo bash" not in text
    assert "sudo sh" not in text
    assert "systemctl" not in text
    assert "*" not in text
    assert "?" not in text


def test_mkfs_disables_discard_and_lazy_initialization() -> None:
    text = EXECUTOR.read_text(encoding="utf-8")

    assert "-E nodiscard,lazy_itable_init=0,lazy_journal_init=0" in text
    assert "-E nodiscard -L" not in text


def test_executor_bash_syntax_on_linux(bash_path: str) -> None:
    result = subprocess.run(
        [bash_path, "-n", str(EXECUTOR)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_sudoers_visudo_syntax_on_linux() -> None:
    visudo = shutil.which("visudo")
    if visudo is None or os.name == "nt":
        pytest.skip("sudoers语法测试需要Linux visudo；Windows由GitHub Linux Runner补证")
    result = subprocess.run(
        [visudo, "-cf", str(SUDOERS)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def bash_path() -> str:
    value = shutil.which("bash")
    if value is None or os.name == "nt":
        pytest.skip("动态执行器测试需要Linux Bash；Windows由GitHub Linux Runner补证")
    return value


def _replace_paths(text: str, replacements: dict[str, str]) -> str:
    pattern = re.compile(
        "|".join(re.escape(source) for source in sorted(replacements, key=len, reverse=True))
    )
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def _write_fake_dispatcher(fake_dir: Path) -> Path:
    dispatcher = fake_dir / "dispatch.py"
    dispatcher.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())

def save():
    state_path.write_text(json.dumps(state))

if name == "hostname":
    print("test-host")
elif name == "logger":
    pass
elif name == "findmnt":
    if "--target" in args:
        print(os.environ["FAKE_DATA_MOUNT"])
    elif "--mountpoint" in args and state["mounted"]:
        print("/dev/loop42 ext4 rw,nodev,nosuid,noatime")
    else:
        raise SystemExit(1)
elif name == "df":
    target = args[-1]
    print(" Size Avail")
    if target == os.environ["FAKE_DATA_MOUNT"]:
        available = 2_097_152 if state["low_space"] else 8_388_608
        print(f" 16777216 {available}")
    else:
        print(" 1048576 900000")
elif name == "systemctl":
    if args[0] == "daemon-reload":
        pass
    elif args[0] == "enable":
        state["enabled"] = True
        state["active"] = True
        state["mounted"] = True
        save()
    elif args[0] == "is-enabled":
        raise SystemExit(0 if state["enabled"] else 1)
    elif args[0] == "is-active":
        raise SystemExit(0 if state["active"] else 1)
    elif args[0] == "stop":
        state["active"] = False
        state["mounted"] = False
        save()
    elif args[0] == "disable":
        state["enabled"] = False
        save()
    else:
        raise SystemExit(2)
elif name == "mkfs.ext4":
    state["filesystem"] = True
    state["mkfs_args"].append(args)
    mount_point = Path(os.environ["FAKE_MOUNT_POINT"])
    mount_point.mkdir(parents=True, exist_ok=True)
    (mount_point / "lost+found").mkdir(exist_ok=True)
    save()
elif name == "blkid":
    if not state["filesystem"]:
        raise SystemExit(2)
    field = args[args.index("-s") + 1]
    print("ext4" if field == "TYPE" else state["label"])
elif name == "dumpe2fs":
    if not state["filesystem"]:
        raise SystemExit(2)
    print("Reserved block count: 0")
elif name == "losetup":
    if state["mounted"]:
        fields = args[args.index("--output") + 1]
        loop_name = "/dev/loop42" if state["loop_matches"] else "/dev/loop99"
        print(f"{loop_name} 1" if fields == "NAME,AUTOCLEAR" else loop_name)
else:
    raise SystemExit(f"unexpected fake command: {name}")
""",
        encoding="utf-8",
    )
    dispatcher.chmod(0o755)
    for name in (
        "hostname",
        "logger",
        "findmnt",
        "df",
        "systemctl",
        "mkfs.ext4",
        "blkid",
        "dumpe2fs",
        "losetup",
    ):
        target = fake_dir / name
        target.symlink_to(dispatcher)
    return dispatcher


def _build_harness(tmp_path: Path, *, low_space: bool = False) -> tuple[Path, dict[str, str]]:
    if os.name == "nt":
        raise AssertionError("Linux only")
    import grp
    import pwd

    uid = os.getuid()
    gid = os.getgid()
    user = pwd.getpwuid(uid).pw_name
    group = grp.getgrgid(gid).gr_name

    data_mount = tmp_path / "mnt" / "data"
    backing = data_mount / "smartscan-loop" / "uat.ext4"
    mount_point = data_mount / "smartscan" / "uat"
    unit_path = tmp_path / "etc" / "systemd" / "system" / "mnt-data-smartscan-uat.mount"
    executor_path = (
        tmp_path / "usr" / "local" / "libexec" / "smartscan" / "smartscan-uat-loop-storage"
    )
    fake_dir = tmp_path / "fake-bin"
    fake_dir.mkdir(parents=True)
    _write_fake_dispatcher(fake_dir)
    data_mount.mkdir(parents=True)
    unit_path.parent.mkdir(parents=True)
    executor_path.parent.mkdir(parents=True)

    path_replacements = {
        "/usr/local/libexec/smartscan/smartscan-uat-loop-storage": str(executor_path),
        "/mnt/data/smartscan-loop/uat.ext4": str(backing),
        "/mnt/data/smartscan-loop": str(backing.parent),
        "/mnt/data/smartscan/uat": str(mount_point),
        "/mnt/data/smartscan": str(mount_point.parent),
        "/mnt/data": str(data_mount),
        "/etc/systemd/system/mnt-data-smartscan-uat.mount": str(unit_path),
    }
    unit_text = _replace_paths(MOUNT_UNIT.read_text(encoding="utf-8"), path_replacements)
    unit_path.write_text(unit_text, encoding="utf-8")
    unit_path.chmod(0o644)
    unit_sha = _sha256(unit_path)

    script = _replace_paths(EXECUTOR.read_text(encoding="utf-8"), path_replacements)
    script = script.replace(
        'readonly EXPECTED_HOSTNAME="ctiecaiserver"', 'readonly EXPECTED_HOSTNAME="test-host"'
    )
    script = script.replace(
        'readonly EXPECTED_SUDO_USER="szhzx"', 'readonly EXPECTED_SUDO_USER="tester"'
    )
    script = script.replace('readonly ROOT_OWNER="root"', f'readonly ROOT_OWNER="{user}"')
    script = script.replace('readonly ROOT_GROUP="root"', f'readonly ROOT_GROUP="{group}"')
    script = script.replace('readonly ROOT_UID="0"', f'readonly ROOT_UID="{uid}"')
    script = script.replace('readonly ROOT_GID="0"', f'readonly ROOT_GID="{gid}"')
    script = script.replace("readonly BACKING_BYTES=53687091200", "readonly BACKING_BYTES=1048576")
    script = script.replace(
        "readonly MINIMUM_USABLE_BYTES=51539607552", "readonly MINIMUM_USABLE_BYTES=786432"
    )
    script = script.replace(
        "readonly MINIMUM_HOST_RESERVE_BYTES=214748364800",
        "readonly MINIMUM_HOST_RESERVE_BYTES=2097152",
    )
    script = script.replace(
        'readonly UNIT_SHA256="e48feb8db96f5fe42b21249846e12a2165b639504afdf99ded882e28eeedd5a3"',
        f'readonly UNIT_SHA256="{unit_sha}"',
    )
    fake_commands = {
        "/usr/bin/hostname": fake_dir / "hostname",
        "/usr/bin/findmnt": fake_dir / "findmnt",
        "/usr/bin/df": fake_dir / "df",
        "/usr/bin/systemctl": fake_dir / "systemctl",
        "/usr/bin/logger": fake_dir / "logger",
        "/usr/sbin/blkid": fake_dir / "blkid",
        "/usr/sbin/dumpe2fs": fake_dir / "dumpe2fs",
        "/usr/sbin/losetup": fake_dir / "losetup",
        "/usr/sbin/mkfs.ext4": fake_dir / "mkfs.ext4",
    }
    script = _replace_paths(script, {key: str(value) for key, value in fake_commands.items()})
    script = script.replace(
        '"$INSTALL_CMD" -d -o "$ROOT_OWNER" -g "$ROOT_GROUP"', '"$INSTALL_CMD" -d'
    )
    script = script.replace('"$CHOWN_CMD" "$ROOT_OWNER:$ROOT_GROUP" "$BACKING_FILE"', "true")
    executor_path.write_text(script, encoding="utf-8")
    executor_path.chmod(0o755)

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "low_space": low_space,
                "filesystem": False,
                "mounted": False,
                "enabled": False,
                "active": False,
                "label": "smartscan-uat",
                "loop_matches": True,
                "mkfs_args": [],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "SUDO_USER": "tester",
            "FAKE_STATE": str(state_path),
            "FAKE_DATA_MOUNT": str(data_mount),
            "FAKE_MOUNT_POINT": str(mount_point),
        }
    )
    return executor_path, env


def _run(
    bash: str, executor: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    run_env = env.copy()
    run_env["SUDO_COMMAND"] = f"{executor} {args[0]}" if args else str(executor)
    return subprocess.run(
        [bash, str(executor), *args],
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )


def _make_backing_sparse(backing: Path, size: int = 1_048_576) -> None:
    with backing.open("r+b") as stream:
        stream.truncate(0)
        stream.truncate(size)


def _update_state(env: dict[str, str], **changes: object) -> None:
    state_path = Path(env["FAKE_STATE"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(changes)
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_create_is_idempotent_and_stop_retains_backing(tmp_path: Path, bash_path: str) -> None:
    executor, env = _build_harness(tmp_path)

    created = _run(bash_path, executor, env, "create")
    repeated = _run(bash_path, executor, env, "create")
    stopped = _run(bash_path, executor, env, "stop")

    assert created.returncode == 0, created.stderr
    assert "result=created" in created.stdout
    assert repeated.returncode == 0, repeated.stderr
    assert "result=already_ready" in repeated.stdout
    assert stopped.returncode == 0, stopped.stderr
    assert "backing_file_retained=true" in stopped.stdout
    assert (tmp_path / "mnt" / "data" / "smartscan-loop" / "uat.ext4").is_file()


def test_create_rejects_abnormal_existing_object(tmp_path: Path, bash_path: str) -> None:
    executor, env = _build_harness(tmp_path)
    backing = tmp_path / "mnt" / "data" / "smartscan-loop" / "uat.ext4"
    backing.parent.mkdir()
    backing.symlink_to(tmp_path / "unexpected")

    result = _run(bash_path, executor, env, "create")

    assert result.returncode != 0
    assert "backing_file_invalid" in result.stderr


def test_create_rejects_insufficient_space(tmp_path: Path, bash_path: str) -> None:
    executor, env = _build_harness(tmp_path, low_space=True)

    result = _run(bash_path, executor, env, "create")

    assert result.returncode != 0
    assert "host_reserve_insufficient" in result.stderr
    assert not (tmp_path / "mnt" / "data" / "smartscan-loop").exists()


def test_create_rejects_mount_unit_hash_mismatch(tmp_path: Path, bash_path: str) -> None:
    executor, env = _build_harness(tmp_path)
    unit = tmp_path / "etc" / "systemd" / "system" / "mnt-data-smartscan-uat.mount"
    unit.write_text(unit.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    result = _run(bash_path, executor, env, "create")

    assert result.returncode != 0
    assert "unit_sha256_mismatch" in result.stderr


def test_executor_rejects_extra_arguments_and_command_injection(
    tmp_path: Path, bash_path: str
) -> None:
    executor, env = _build_harness(tmp_path)

    extra = _run(bash_path, executor, env, "create", ";id")
    recreate_extra = _run(bash_path, executor, env, "recreate-empty", ";id")
    unknown = _run(bash_path, executor, env, "bash")

    assert extra.returncode == 64
    assert recreate_extra.returncode == 64
    assert unknown.returncode == 64
    assert not (tmp_path / "mnt" / "data" / "smartscan-loop").exists()


def test_recreate_empty_repairs_sparse_empty_uat_and_verify_is_repeatable(
    tmp_path: Path, bash_path: str
) -> None:
    executor, env = _build_harness(tmp_path)
    backing = tmp_path / "mnt" / "data" / "smartscan-loop" / "uat.ext4"

    created = _run(bash_path, executor, env, "create")
    assert created.returncode == 0, created.stderr
    _make_backing_sparse(backing)

    recreated = _run(bash_path, executor, env, "recreate-empty")
    first_verify = _run(bash_path, executor, env, "verify")
    second_verify = _run(bash_path, executor, env, "verify")

    assert recreated.returncode == 0, recreated.stderr
    assert "result=recreated" in recreated.stdout
    assert first_verify.returncode == 0, first_verify.stderr
    assert second_verify.returncode == 0, second_verify.stderr
    state = json.loads(Path(env["FAKE_STATE"]).read_text(encoding="utf-8"))
    assert len(state["mkfs_args"]) == 2
    for args in state["mkfs_args"]:
        assert "nodiscard,lazy_itable_init=0,lazy_journal_init=0" in args


def test_recreate_empty_rejects_business_content(tmp_path: Path, bash_path: str) -> None:
    executor, env = _build_harness(tmp_path)
    backing = tmp_path / "mnt" / "data" / "smartscan-loop" / "uat.ext4"
    business_file = tmp_path / "mnt" / "data" / "smartscan" / "uat" / "scan.pdf"
    assert _run(bash_path, executor, env, "create").returncode == 0
    _make_backing_sparse(backing)
    business_file.write_bytes(b"must-not-delete")

    result = _run(bash_path, executor, env, "recreate-empty")

    assert result.returncode != 0
    assert "uat_not_empty" in result.stderr
    assert business_file.read_bytes() == b"must-not-delete"
    assert json.loads(Path(env["FAKE_STATE"]).read_text())["mounted"] is True


def test_recreate_empty_rejects_non_sparse_backing(tmp_path: Path, bash_path: str) -> None:
    executor, env = _build_harness(tmp_path)
    assert _run(bash_path, executor, env, "create").returncode == 0

    result = _run(bash_path, executor, env, "recreate-empty")

    assert result.returncode != 0
    assert "backing_not_sparse" in result.stderr
    assert json.loads(Path(env["FAKE_STATE"]).read_text())["mounted"] is True


@pytest.mark.parametrize(
    ("scenario", "expected_reason"),
    [
        ("path", "backing_file_invalid"),
        ("mount", "mount_missing"),
        ("loop", "loop_autoclear_invalid"),
        ("label", "filesystem_label_invalid"),
        ("permissions", "backing_permissions_invalid"),
    ],
)
def test_recreate_empty_rejects_abnormal_fixed_state(
    tmp_path: Path, bash_path: str, scenario: str, expected_reason: str
) -> None:
    case_root = tmp_path / scenario
    executor, env = _build_harness(case_root)
    backing = case_root / "mnt" / "data" / "smartscan-loop" / "uat.ext4"
    assert _run(bash_path, executor, env, "create").returncode == 0
    _make_backing_sparse(backing)

    if scenario == "path":
        backing.unlink()
        backing.symlink_to(case_root / "unexpected")
    elif scenario == "mount":
        _update_state(env, mounted=False)
    elif scenario == "loop":
        _update_state(env, loop_matches=False)
    elif scenario == "label":
        _update_state(env, label="unexpected")
    elif scenario == "permissions":
        backing.chmod(0o644)

    result = _run(bash_path, executor, env, "recreate-empty")

    assert result.returncode != 0
    assert expected_reason in result.stderr


def test_recreate_empty_only_changes_fixed_smartscan_objects(
    tmp_path: Path, bash_path: str
) -> None:
    executor, env = _build_harness(tmp_path)
    data_mount = tmp_path / "mnt" / "data"
    backing = data_mount / "smartscan-loop" / "uat.ext4"
    unrelated = data_mount / "unrelated-service.keep"
    unrelated.write_bytes(b"untouched")
    assert _run(bash_path, executor, env, "create").returncode == 0
    _make_backing_sparse(backing)

    result = _run(bash_path, executor, env, "recreate-empty")

    assert result.returncode == 0, result.stderr
    assert unrelated.read_bytes() == b"untouched"
