from __future__ import annotations

import argparse
import ctypes
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

TRIAL_USERNAME = "demo"
TRIAL_PASSWORD = "SmartScan2026!"
TRIAL_PHONE = "+8613800000001"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "SmartScanAdmin2026!"
API_URL = "http://localhost:8000"
H5_URL = "http://localhost:8080"
PROCESS_MARKERS = {
    "api": "services.api.app.main:app",
    "worker": "services.worker.app.main",
    "ai_gateway": "services/ai-gateway",
    "ai_worker": "services.worker.app.ai_main",
    "h5": "http.server 8080",
}
CONTROLLED_AI_NETWORKS = tuple(
    ipaddress.ip_network(item)
    for item in (
        "10.0.0.0/8",
        "100.64.0.0/10",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)


@dataclass(frozen=True)
class TrialPaths:
    root: Path
    trial: Path
    state: Path
    logs: Path
    storage: Path
    database: Path
    runtime_config: Path
    ai_provider_config: Path
    dependency_fingerprint: Path
    venv_python: Path


def trial_paths(root: Path | None = None) -> TrialPaths:
    project_root = (root or Path(__file__).resolve().parents[1]).resolve()
    trial = project_root / ".smartscan-trial"
    python_name = "python.exe" if os.name == "nt" else "python"
    python_dir = "Scripts" if os.name == "nt" else "bin"
    return TrialPaths(
        root=project_root,
        trial=trial,
        state=trial / "state.json",
        logs=trial / "logs",
        storage=trial / "storage",
        database=trial / "smartscan-trial.db",
        runtime_config=trial / "runtime-config.json",
        ai_provider_config=trial / "ai-provider.local.json",
        dependency_fingerprint=project_root / ".venv" / ".smartscan-trial-dependency.sha256",
        venv_python=project_root / ".venv" / python_dir / python_name,
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_state(paths: TrialPaths) -> dict[str, object]:
    if not paths.state.exists():
        return {"processes": {}}
    try:
        payload = json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"试用状态文件损坏：{paths.state}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("processes"), dict):
        raise TypeError(f"试用状态文件格式无效：{paths.state}")
    return payload


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _command_line(pid: int) -> str:
    if os.name == "nt":
        command = (
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
            "if ($p) { $p.CommandLine }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    proc_command = Path(f"/proc/{pid}/cmdline")
    if proc_command.exists():
        return proc_command.read_bytes().replace(b"\0", b" ").decode(errors="replace")
    return ""


def _process_matches(pid: int, marker: str) -> bool:
    return marker in _command_line(pid)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.25)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def _dependency_hash(paths: TrialPaths) -> str:
    digest = hashlib.sha256()
    for relative in ("pyproject.toml", "services/api/Dockerfile", "services/worker/Dockerfile"):
        candidate = paths.root / relative
        if candidate.exists():
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def _run_checked(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode:
        raise RuntimeError(f"命令执行失败（退出码 {result.returncode}）：{' '.join(command)}")


def ensure_environment(paths: TrialPaths) -> Path:
    if not paths.venv_python.exists():
        print("首次试用：正在创建 Python 虚拟环境……")
        _run_checked([sys.executable, "-m", "venv", str(paths.root / ".venv")], cwd=paths.root)

    expected = _dependency_hash(paths)
    current = ""
    if paths.dependency_fingerprint.exists():
        current = paths.dependency_fingerprint.read_text(encoding="utf-8").strip()
    import_check = subprocess.run(
        [str(paths.venv_python), "-c", "import cv2, fastapi, sqlalchemy, uvicorn"],
        cwd=paths.root,
        capture_output=True,
        check=False,
        text=True,
    )
    if current != expected or import_check.returncode:
        print("首次试用或依赖已更新：正在安装本机试用依赖，请稍候……")
        _run_checked(
            [str(paths.venv_python), "-m", "pip", "install", "-e", ".[dev,vision]"],
            cwd=paths.root,
        )
        paths.trial.mkdir(parents=True, exist_ok=True)
        paths.dependency_fingerprint.write_text(expected, encoding="utf-8")
    return paths.venv_python


def _load_or_create_runtime_config(paths: TrialPaths) -> dict[str, str]:
    if paths.runtime_config.exists():
        try:
            payload = json.loads(paths.runtime_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"试用运行配置损坏：{paths.runtime_config}") from exc
        if isinstance(payload, dict) and all(
            isinstance(payload.get(key), str) for key in ("secret_key", "phone_pepper")
        ):
            if not isinstance(payload.get("ai_internal_token"), str):
                payload["ai_internal_token"] = secrets.token_urlsafe(48)
                _write_json(paths.runtime_config, payload)
            return {
                key: str(payload[key])
                for key in ("secret_key", "phone_pepper", "ai_internal_token")
            }
        raise RuntimeError(f"试用运行配置格式无效：{paths.runtime_config}")
    payload = {
        "secret_key": secrets.token_urlsafe(48),
        "phone_pepper": secrets.token_urlsafe(48),
        "ai_internal_token": secrets.token_urlsafe(48),
    }
    _write_json(paths.runtime_config, payload)
    return payload


def _validate_trial_https_url(value: object, *, trailing_slash: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("真实 AI 配置中的 URL 不能为空。")
    parsed = urlsplit(value.strip())
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("真实 AI URL 端口无效。") from exc
    hostname = parsed.hostname
    try:
        ipaddress.ip_address(hostname or "")
    except ValueError:
        pass
    else:
        raise RuntimeError("真实 AI URL 必须使用完整域名，不能使用 IP 地址。")
    if (
        parsed.scheme != "https"
        or not hostname
        or "." not in hostname
        or hostname.endswith(".")
        or "\\" in value
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise RuntimeError("真实 AI URL 必须是无账号、查询参数和片段的标准 HTTPS 地址。")
    if trailing_slash and not parsed.path.endswith("/"):
        raise RuntimeError("真实 AI 媒体地址必须以 / 结尾。")
    return value.strip()


def _controlled_private_cidrs(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError("allowed_private_cidrs 必须是字符串数组。")
    result: list[str] = []
    for item in value:
        try:
            network = ipaddress.ip_network(item, strict=True)
        except ValueError as exc:
            raise RuntimeError(f"受控网段格式无效：{item}") from exc
        controlled = any(
            network.version == allowed.version and network.subnet_of(allowed)
            for allowed in CONTROLLED_AI_NETWORKS
        )
        if not controlled or network.prefixlen < (16 if network.version == 4 else 48):
            raise RuntimeError(f"受控网段范围过宽或不是私网：{item}")
        result.append(str(network))
    if len(result) != len(set(result)):
        raise RuntimeError("受控网段不能重复。")
    return result


def load_trial_ai_config(paths: TrialPaths) -> dict[str, object]:
    if not paths.ai_provider_config.exists():
        return {
            "mode": "mock",
            "provider_id": "local-mock",
            "model": "mock-v1",
            "api_style": "openai_responses",
            "base_url": "https://mock.smartscan.test/v1",
            "media_base_url": "https://local.smartscan.test/api/v1/ai-media/",
            "api_key": "local-mock-only-not-a-real-secret",
            "allowed_private_cidrs": [],
        }
    if paths.ai_provider_config.stat().st_size > 64 * 1024:
        raise RuntimeError("真实 AI 本机 Secret 文件超过 64 KiB，已拒绝读取。")
    try:
        payload = json.loads(paths.ai_provider_config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"真实 AI 本机 Secret 文件无效：{paths.ai_provider_config}") from exc
    allowed_keys = {
        "mode",
        "base_url",
        "api_key",
        "model",
        "api_style",
        "media_base_url",
        "allowed_private_cidrs",
    }
    if not isinstance(payload, dict) or set(payload) - allowed_keys:
        raise RuntimeError("真实 AI 本机 Secret 含有未知字段。")
    if payload.get("mode") != "real":
        raise RuntimeError('真实 AI 本机 Secret 的 mode 必须为 "real"。')
    api_style = payload.get("api_style")
    if api_style not in {"openai_chat", "openai_responses"}:
        raise RuntimeError("api_style 必须为 openai_chat 或 openai_responses。")
    api_key = payload.get("api_key")
    model = payload.get("model")
    if not isinstance(api_key, str) or not api_key.strip():
        raise RuntimeError("真实 AI api_key 不能为空。")
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 200:
        raise RuntimeError("真实 AI model 长度必须为 1～200。")
    return {
        "mode": "real",
        "provider_id": "local-real",
        "base_url": _validate_trial_https_url(payload.get("base_url"), trailing_slash=False),
        "api_key": api_key.strip(),
        "model": model.strip(),
        "api_style": api_style,
        "media_base_url": _validate_trial_https_url(
            payload.get("media_base_url"), trailing_slash=True
        ),
        "allowed_private_cidrs": _controlled_private_cidrs(payload.get("allowed_private_cidrs")),
    }


def build_trial_environment(paths: TrialPaths) -> dict[str, str]:
    runtime_config = _load_or_create_runtime_config(paths)
    ai_config = load_trial_ai_config(paths)
    provider = {
        "id": ai_config["provider_id"],
        "display_name": "本机模拟 AI" if ai_config["mode"] == "mock" else "本机真实 AI",
        "kind": "custom_vlm",
        "api_style": ai_config["api_style"],
        "enabled": True,
        "base_url": ai_config["base_url"],
        "api_key_env": "SMARTSCAN_LOCAL_AI_KEY",
        "model": ai_config["model"],
        "supports_images": True,
        "capabilities": [
            "ocr",
            "document_understanding",
            "image_classification",
            "layout_analysis",
        ],
        "media_url_prefixes": [ai_config["media_base_url"]],
        "allowed_private_cidrs": ai_config["allowed_private_cidrs"],
    }
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "SMARTSCAN_ENV": "development",
            "SMARTSCAN_DATABASE_URL": f"sqlite:///{paths.database.as_posix()}",
            "SMARTSCAN_AUTO_MIGRATE": "true",
            "SMARTSCAN_STORAGE_ROOT": str(paths.storage),
            "SMARTSCAN_SECRET_KEY": runtime_config["secret_key"],
            "SMARTSCAN_PHONE_PEPPER": runtime_config["phone_pepper"],
            "SMARTSCAN_SUPERADMIN_PASSWORD": ADMIN_PASSWORD,
            "SMARTSCAN_CORS_ORIGINS": json.dumps(
                ["http://localhost:8080", "http://localhost:8081"]
            ),
            "SMARTSCAN_DEV_SMS_CODE": "246810",
            "SMARTSCAN_SMS_MODE": "disabled",
            "SMARTSCAN_WECOM_MODE": "disabled",
            "SMARTSCAN_OCR_ENABLED": "false",
            "SMARTSCAN_AI_GATEWAY_URL": "http://127.0.0.1:8010",
            "SMARTSCAN_AI_INTERNAL_TOKEN": runtime_config["ai_internal_token"],
            "SMARTSCAN_AI_PROVIDER_ID": str(ai_config["provider_id"]),
            "SMARTSCAN_AI_MEDIA_BASE_URL": str(ai_config["media_base_url"]),
            "SMARTSCAN_AI_MOCK_MODE": "true" if ai_config["mode"] == "mock" else "false",
            "SMARTSCAN_AI_PROVIDERS": json.dumps([provider], ensure_ascii=False),
            "SMARTSCAN_LOCAL_AI_KEY": str(ai_config["api_key"]),
        }
    )
    return environment


def _launch(
    paths: TrialPaths,
    role: str,
    command: list[str],
    environment: dict[str, str],
) -> subprocess.Popen[bytes]:
    paths.logs.mkdir(parents=True, exist_ok=True)
    log_path = paths.logs / f"{role}.log"
    log = log_path.open("ab", buffering=0)
    options: dict[str, object] = {
        "cwd": paths.root,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **options)
    finally:
        log.close()
    return process


def _wait_for_url(url: str, *, timeout_seconds: float = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise RuntimeError(f"服务未在 {timeout_seconds:.0f} 秒内就绪：{url}")


def _json_request(path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Device-ID": "web:local-trial-bootstrap",
            "X-Device-Name": "SmartScan%20local%20trial",
            "X-Device-Platform": "web",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode() or "{}")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode() or "{}")
        return exc.code, body


def ensure_trial_account() -> None:
    status, response = _json_request(
        "/v1/auth/register",
        {
            "phone": TRIAL_PHONE,
            "sms_code": "246810",
            "username": TRIAL_USERNAME,
            "password": TRIAL_PASSWORD,
            "locale": "zh-CN",
        },
    )
    if status == 201:
        return
    if status != 409:
        raise RuntimeError(f"自动创建试用账号失败（HTTP {status}）：{response}")
    login_status, login_response = _json_request(
        "/v1/auth/login",
        {"username": TRIAL_USERNAME, "password": TRIAL_PASSWORD},
    )
    if login_status != 200:
        raise RuntimeError(
            f"现有试用账号无法登录（HTTP {login_status}）：{login_response}。"
            "请在启动器中选择“清理试用数据”后重试。"
        )


def _save_process(paths: TrialPaths, role: str, process: subprocess.Popen[bytes]) -> None:
    state = _load_state(paths)
    processes = state["processes"]
    assert isinstance(processes, dict)
    processes[role] = {
        "pid": process.pid,
        "marker": PROCESS_MARKERS[role],
        "started_at": time.time(),
    }
    state["started_at"] = state.get("started_at", time.time())
    _write_json(paths.state, state)


def _save_ai_mode(paths: TrialPaths, mode: str) -> None:
    state = _load_state(paths)
    state["ai_mode"] = mode
    _write_json(paths.state, state)


def _running_roles(paths: TrialPaths) -> list[str]:
    roles: list[str] = []
    state = _load_state(paths)
    processes = state["processes"]
    assert isinstance(processes, dict)
    for role, raw in processes.items():
        if not isinstance(raw, dict):
            continue
        pid = raw.get("pid")
        marker = raw.get("marker")
        if (
            isinstance(pid, int)
            and isinstance(marker, str)
            and _pid_is_running(pid)
            and _process_matches(pid, marker)
        ):
            roles.append(str(role))
    return roles


def start_trial(paths: TrialPaths, *, open_browser: bool = True) -> None:
    running = _running_roles(paths)
    if set(running) == set(PROCESS_MARKERS):
        print(f"本机试用已经在运行：{', '.join(running)}")
        _print_access_information(paths)
        if open_browser:
            webbrowser.open(H5_URL)
        return
    if running:
        print(f"检测到未完整退出的试用进程：{', '.join(running)}，正在先行停止。")
        stop_trial(paths)
    for port in (8000, 8010, 8080):
        if _port_in_use(port):
            raise RuntimeError(f"端口 {port} 已被其他程序占用，请先关闭占用程序后重试。")

    paths.logs.mkdir(parents=True, exist_ok=True)
    paths.storage.mkdir(parents=True, exist_ok=True)
    python = ensure_environment(paths)
    environment = build_trial_environment(paths)
    service_environment = environment.copy()
    service_environment.pop("SMARTSCAN_LOCAL_AI_KEY", None)
    service_environment.pop("SMARTSCAN_AI_PROVIDERS", None)
    ai_config = load_trial_ai_config(paths)
    commands = {
        "api": [
            str(python),
            "-m",
            "uvicorn",
            "services.api.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        "worker": [str(python), "-m", "services.worker.app.main"],
        "ai_gateway": [
            str(python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "services/ai-gateway",
            "--host",
            "127.0.0.1",
            "--port",
            "8010",
        ],
        "ai_worker": [str(python), "-m", "services.worker.app.ai_main"],
        "h5": [
            str(python),
            "-m",
            "http.server",
            "8080",
            "--bind",
            "127.0.0.1",
            "--directory",
            "apps/h5",
        ],
    }
    try:
        api = _launch(paths, "api", commands["api"], service_environment)
        _save_process(paths, "api", api)
        _wait_for_url(f"{API_URL}/openapi.json")
        ensure_trial_account()

        ai_gateway = _launch(paths, "ai_gateway", commands["ai_gateway"], environment)
        _save_process(paths, "ai_gateway", ai_gateway)
        _wait_for_url("http://localhost:8010/health")

        ai_worker = _launch(paths, "ai_worker", commands["ai_worker"], service_environment)
        _save_process(paths, "ai_worker", ai_worker)
        worker = _launch(paths, "worker", commands["worker"], service_environment)
        _save_process(paths, "worker", worker)
        h5 = _launch(paths, "h5", commands["h5"], service_environment)
        _save_process(paths, "h5", h5)
        _wait_for_url(H5_URL, timeout_seconds=20)
        _save_ai_mode(paths, str(ai_config["mode"]))
    except Exception:
        stop_trial(paths)
        raise

    print("本机试用已启动，试用账号已自动创建。")
    _print_access_information(paths)
    if open_browser:
        webbrowser.open(H5_URL)


def _terminate_process(pid: int, marker: str) -> bool:
    if not _pid_is_running(pid):
        return False
    if not _process_matches(pid, marker):
        print(f"为避免误停其他程序，已跳过 PID {pid}（命令行标记不匹配）。")
        return False
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
    return True


def stop_trial(paths: TrialPaths) -> None:
    state = _load_state(paths)
    processes = state["processes"]
    assert isinstance(processes, dict)
    stopped: list[str] = []
    remaining: dict[str, object] = {}
    for role in ("h5", "ai_worker", "worker", "ai_gateway", "api"):
        raw = processes.get(role)
        if not isinstance(raw, dict):
            continue
        pid = raw.get("pid")
        marker = raw.get("marker")
        if isinstance(pid, int) and isinstance(marker, str):
            if _terminate_process(pid, marker):
                stopped.append(role)
            elif _pid_is_running(pid):
                remaining[role] = raw
    if remaining:
        state["processes"] = remaining
        _write_json(paths.state, state)
    elif paths.state.exists():
        paths.state.unlink()
    if stopped:
        print(f"本机试用已停止：{', '.join(stopped)}。试用数据仍保留。")
    else:
        print("本机试用当前未运行。")


def assert_safe_trial_directory(paths: TrialPaths) -> None:
    resolved_root = paths.root.resolve()
    resolved_trial = paths.trial.resolve()
    if resolved_trial != resolved_root / ".smartscan-trial":
        raise RuntimeError(f"拒绝清理非标准试用目录：{resolved_trial}")
    if resolved_trial.parent != resolved_root:
        raise RuntimeError(f"试用目录不在项目根目录内：{resolved_trial}")


def clean_trial(
    paths: TrialPaths,
    *,
    confirmed: bool = False,
    stop: Callable[[TrialPaths], None] = stop_trial,
) -> bool:
    if not confirmed:
        answer = input("这会删除全部本机试用账号、扫描文件和日志。请输入“清理”确认：").strip()
        if answer != "清理":
            print("已取消清理。")
            return False
    assert_safe_trial_directory(paths)
    stop(paths)
    if paths.state.exists():
        raise RuntimeError("仍有无法安全确认的试用进程，已拒绝清理数据。请查看状态和日志。")
    if paths.trial.exists():
        shutil.rmtree(paths.trial)
    print("试用数据已清理；Python 虚拟环境已保留，下次启动无需重复安装。")
    return True


def show_status(paths: TrialPaths) -> None:
    running = _running_roles(paths)
    if running:
        print(f"运行中：{', '.join(running)}")
        _print_access_information(paths)
        return
    print("本机试用未运行。")
    if paths.database.exists():
        print("试用数据仍保留，可直接再次启动。")


def _print_access_information(paths: TrialPaths) -> None:
    state = _load_state(paths)
    mode = state.get("ai_mode")
    if mode not in {"mock", "real"}:
        mode = load_trial_ai_config(paths)["mode"]
    print(f"H5 地址：{H5_URL}")
    print(f"试用账号：{TRIAL_USERNAME}")
    print(f"试用密码：{TRIAL_PASSWORD}")
    print(f"API 文档：{API_URL}/docs")
    print(
        "AI 模式：模拟 AI（不访问真实模型，不计入质量验收）"
        if mode == "mock"
        else "AI 模式：真实 AI（使用本机未跟踪 Secret）"
    )


def run_menu(paths: TrialPaths) -> int:
    print("\nSmartScan 本机一键试用")
    print("1. 启动试用")
    print("2. 停止试用（保留数据）")
    print("3. 清理试用数据")
    print("4. 查看状态")
    print("0. 退出")
    action = input("请选择：").strip()
    actions: dict[str, Callable[[], None]] = {
        "1": lambda: start_trial(paths),
        "2": lambda: stop_trial(paths),
        "3": lambda: clean_trial(paths),
        "4": lambda: show_status(paths),
    }
    if action == "0":
        return 0
    selected = actions.get(action)
    if selected is None:
        print("无效选择。")
        return 2
    selected()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SmartScan 本机一键试用工具")
    parser.add_argument(
        "action",
        nargs="?",
        default="menu",
        choices=("menu", "start", "stop", "clean", "status"),
    )
    parser.add_argument("--yes", action="store_true", help="清理时跳过交互确认")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    paths = trial_paths()
    try:
        if arguments.action == "menu":
            return run_menu(paths)
        if arguments.action == "start":
            start_trial(paths, open_browser=not arguments.no_browser)
        elif arguments.action == "stop":
            stop_trial(paths)
        elif arguments.action == "clean":
            clean_trial(paths, confirmed=arguments.yes)
        else:
            show_status(paths)
    except (OSError, RuntimeError, TypeError, subprocess.SubprocessError) as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        if paths.logs.exists():
            print(f"日志目录：{paths.logs}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
