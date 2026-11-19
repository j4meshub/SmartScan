from __future__ import annotations

import hashlib
import json
import os
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
    assert "create|verify|status|stop" in text
    assert 'if [[ "$#" -ne 1 ]]' in text
    assert "docker" not in text.casefold()
    assert "nginx" not in text.casefold()
    assert "rm " not in text
    assert "losetup -d" not in text
    assert "$@" in text  # 只用于单次固定参数校验入口。


def test_executor_pins_reviewed_mount_unit_sha256() -> None:
    text = EXECUTOR.read_text(encoding="utf-8")
    assert f'readonly UNIT_SHA256="{_sha256(MOUNT_UNIT)}"' in text


def test_sudoers_allows_only_four_exact_digest_pinned_commands() -> None:
    text = SUDOERS.read_text(encoding="utf-8")
    executor_sha = _sha256(EXECUTOR)
    command = "/usr/local/libexec/smartscan/smartscan-uat-loop-storage"

    assert text.count(f"sha256:{executor_sha} {command}") == 4
    for action in ("create", "verify", "status", "stop"):
        assert f"sha256:{executor_sha} {command} {action}" in text
    assert "szhzx ALL=(root) NOPASSWD: SMARTSCAN_UAT_LOOP_STORAGE" in text
    assert "sudo bash" not in text
    assert "sudo sh" not in text
    assert "systemctl" not in text
    assert "*" not in text
    assert "?" not in text


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
    for source in sorted(replacements, key=len, reverse=True):
        text = text.replace(source, replacements[source])
    return text


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
    save()
elif name == "blkid":
    if not state["filesystem"]:
        raise SystemExit(2)
    field = args[args.index("-s") + 1]
    print("ext4" if field == "TYPE" else "smartscan-uat")
elif name == "dumpe2fs":
    if not state["filesystem"]:
        raise SystemExit(2)
    print("Reserved block count: 0")
elif name == "losetup":
    if state["mounted"]:
        fields = args[args.index("--output") + 1]
        print("/dev/loop42 1" if fields == "NAME,AUTOCLEAR" else "/dev/loop42")
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
    unknown = _run(bash_path, executor, env, "bash")

    assert extra.returncode == 64
    assert unknown.returncode == 64
    assert not (tmp_path / "mnt" / "data" / "smartscan-loop").exists()
