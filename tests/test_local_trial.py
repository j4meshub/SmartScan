from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import local_trial


def test_trial_environment_uses_isolated_development_resources(tmp_path: Path) -> None:
    paths = local_trial.trial_paths(tmp_path)

    environment = local_trial.build_trial_environment(paths)

    assert environment["SMARTSCAN_ENV"] == "development"
    assert environment["SMARTSCAN_DATABASE_URL"] == (
        f"sqlite:///{(tmp_path / '.smartscan-trial/smartscan-trial.db').as_posix()}"
    )
    assert environment["SMARTSCAN_STORAGE_ROOT"] == str(tmp_path / ".smartscan-trial/storage")
    assert environment["SMARTSCAN_SMS_MODE"] == "disabled"
    assert environment["SMARTSCAN_WECOM_MODE"] == "disabled"
    assert environment["SMARTSCAN_OCR_ENABLED"] == "false"
    assert environment["SMARTSCAN_AI_MOCK_MODE"] == "true"
    assert environment["SMARTSCAN_AI_GATEWAY_URL"] == "http://127.0.0.1:8010"
    assert environment["SMARTSCAN_AI_PROVIDER_ID"] == "local-mock"
    providers = json.loads(environment["SMARTSCAN_AI_PROVIDERS"])
    assert providers[0]["display_name"] == "本机模拟 AI"
    assert providers[0]["model"] == "mock-v1"
    assert "api_key" not in providers[0]
    assert environment["SMARTSCAN_SECRET_KEY"] != environment["SMARTSCAN_PHONE_PEPPER"]
    assert len(environment["SMARTSCAN_AI_INTERNAL_TOKEN"]) >= 32

    restarted_environment = local_trial.build_trial_environment(paths)
    assert restarted_environment["SMARTSCAN_SECRET_KEY"] == environment["SMARTSCAN_SECRET_KEY"]
    assert restarted_environment["SMARTSCAN_PHONE_PEPPER"] == environment["SMARTSCAN_PHONE_PEPPER"]
    assert (
        restarted_environment["SMARTSCAN_AI_INTERNAL_TOKEN"]
        == environment["SMARTSCAN_AI_INTERNAL_TOKEN"]
    )


def test_clean_trial_only_removes_isolated_data_and_preserves_venv(tmp_path: Path) -> None:
    paths = local_trial.trial_paths(tmp_path)
    paths.storage.mkdir(parents=True)
    paths.database.write_text("trial", encoding="utf-8")
    venv_marker = tmp_path / ".venv/keep.txt"
    venv_marker.parent.mkdir()
    venv_marker.write_text("keep", encoding="utf-8")
    paths.dependency_fingerprint.write_text("keep-fingerprint", encoding="utf-8")
    stopped: list[Path] = []

    cleaned = local_trial.clean_trial(
        paths,
        confirmed=True,
        stop=lambda selected: stopped.append(selected.trial),
    )

    assert cleaned is True
    assert stopped == [paths.trial]
    assert not paths.trial.exists()
    assert venv_marker.read_text(encoding="utf-8") == "keep"
    assert paths.dependency_fingerprint.read_text(encoding="utf-8") == "keep-fingerprint"


def test_clean_trial_rejects_nonstandard_directory(tmp_path: Path) -> None:
    paths = local_trial.trial_paths(tmp_path)
    unsafe = local_trial.TrialPaths(
        root=paths.root,
        trial=tmp_path / "other-data",
        state=paths.state,
        logs=paths.logs,
        storage=paths.storage,
        database=paths.database,
        runtime_config=paths.runtime_config,
        ai_provider_config=paths.ai_provider_config,
        dependency_fingerprint=paths.dependency_fingerprint,
        venv_python=paths.venv_python,
    )

    with pytest.raises(RuntimeError, match="拒绝清理非标准试用目录"):
        local_trial.assert_safe_trial_directory(unsafe)


def test_clean_trial_refuses_when_managed_process_state_remains(tmp_path: Path) -> None:
    paths = local_trial.trial_paths(tmp_path)
    paths.trial.mkdir()
    paths.state.write_text('{"processes":{"api":{"pid":123}}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="拒绝清理数据"):
        local_trial.clean_trial(paths, confirmed=True, stop=lambda _paths: None)

    assert paths.trial.exists()


def test_running_roles_ignores_stale_and_mismatched_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = local_trial.trial_paths(tmp_path)
    paths.trial.mkdir()
    paths.state.write_text(
        json.dumps(
            {
                "processes": {
                    "api": {"pid": 101, "marker": local_trial.PROCESS_MARKERS["api"]},
                    "worker": {"pid": 202, "marker": local_trial.PROCESS_MARKERS["worker"]},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(local_trial, "_pid_is_running", lambda pid: pid in {101, 202})
    monkeypatch.setattr(local_trial, "_process_matches", lambda pid, marker: pid == 101)

    assert local_trial._running_roles(paths) == ["api"]


def test_existing_trial_account_must_use_expected_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            (409, {"detail": "username already exists"}),
            (401, {"detail": "invalid credentials"}),
        ]
    )
    monkeypatch.setattr(local_trial, "_json_request", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="清理试用数据"):
        local_trial.ensure_trial_account()


def test_real_ai_uses_only_ignored_local_secret_without_persisting_key(tmp_path: Path) -> None:
    paths = local_trial.trial_paths(tmp_path)
    paths.trial.mkdir()
    paths.ai_provider_config.write_text(
        json.dumps(
            {
                "mode": "real",
                "base_url": "https://vlm.corp.example/v1",
                "api_key": "real-key-only-in-process-environment",
                "model": "company-vlm-1",
                "api_style": "openai_responses",
                "media_base_url": "https://scan.corp.example/api/v1/ai-media/",
                "allowed_private_cidrs": ["10.20.0.0/16"],
            }
        ),
        encoding="utf-8",
    )

    environment = local_trial.build_trial_environment(paths)

    assert environment["SMARTSCAN_AI_MOCK_MODE"] == "false"
    assert environment["SMARTSCAN_AI_PROVIDER_ID"] == "local-real"
    assert environment["SMARTSCAN_LOCAL_AI_KEY"] == "real-key-only-in-process-environment"
    provider = json.loads(environment["SMARTSCAN_AI_PROVIDERS"])[0]
    assert provider["base_url"] == "https://vlm.corp.example/v1"
    assert provider["allowed_private_cidrs"] == ["10.20.0.0/16"]
    assert provider["api_key_env"] == "SMARTSCAN_LOCAL_AI_KEY"
    assert "real-key-only-in-process-environment" not in paths.runtime_config.read_text(
        encoding="utf-8"
    )
    assert not paths.state.exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"mode": "mock"}, "mode"),
        ({"api_style": "custom"}, "api_style"),
        ({"base_url": "http://vlm.corp.example/v1"}, "HTTPS"),
        ({"media_base_url": "https://scan.corp.example/media"}, "以 / 结尾"),
        ({"allowed_private_cidrs": ["10.0.0.0/8"]}, "范围过宽"),
        ({"allowed_private_cidrs": ["192.0.2.0/24"]}, "不是私网"),
        ({"base_url": "https://127.0.0.1/v1"}, "不能使用 IP"),
        ({"unexpected": "value"}, "未知字段"),
    ],
)
def test_real_ai_secret_fails_closed_on_unsafe_configuration(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    paths = local_trial.trial_paths(tmp_path)
    paths.trial.mkdir()
    payload: dict[str, object] = {
        "mode": "real",
        "base_url": "https://vlm.corp.example/v1",
        "api_key": "secret",
        "model": "company-vlm-1",
        "api_style": "openai_responses",
        "media_base_url": "https://scan.corp.example/api/v1/ai-media/",
        "allowed_private_cidrs": [],
    }
    payload.update(change)
    paths.ai_provider_config.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        local_trial.load_trial_ai_config(paths)


def test_real_ai_accepts_explicit_carrier_grade_private_subnet(tmp_path: Path) -> None:
    paths = local_trial.trial_paths(tmp_path)
    paths.trial.mkdir()
    paths.ai_provider_config.write_text(
        json.dumps(
            {
                "mode": "real",
                "base_url": "https://vlm.corp.example/v1",
                "api_key": "secret",
                "model": "company-vlm-1",
                "api_style": "openai_chat",
                "media_base_url": "https://scan.corp.example/api/v1/ai-media/",
                "allowed_private_cidrs": ["100.64.1.0/24"],
            }
        ),
        encoding="utf-8",
    )

    config = local_trial.load_trial_ai_config(paths)

    assert config["allowed_private_cidrs"] == ["100.64.1.0/24"]
