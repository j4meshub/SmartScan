from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from deploy.ops import smartscan_uat_validators as validators
from deploy.ops import smartscan_uatctl as uatctl

TEST_UID = os.getuid() if hasattr(os, "getuid") else 0


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.call_options: list[dict[str, object]] = []
        self.outputs: dict[tuple[str, ...], str] = {}
        self.results: dict[tuple[str, ...], uatctl.CommandResult] = {}

    def run(
        self,
        arguments: list[str],
        *,
        check: bool = True,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        self.calls.append(arguments)
        self.call_options.append(
            {
                "check": check,
                "timeout_seconds": timeout_seconds,
                "environment": environment,
            }
        )
        key = tuple(arguments)
        if key in self.outputs:
            return self.outputs[key]
        if arguments[:4] == ["/usr/bin/docker", "network", "ls", "--format"]:
            return "smartscan-uat-data\nsmartscan-uat-edge\nsmartscan-uat-egress"
        if arguments[-1:] == ["verify"] and any("loop" in item for item in arguments):
            return "status=passed"
        if arguments[-1:] == ["verify"] and any("ocr" in item for item in arguments):
            return '{"status":"passed"}'
        if arguments[-1:] == ["status"] and any("ocr" in item for item in arguments):
            return '{"installed":true,"status":"passed"}'
        if arguments[-1:] == ["verify"] and "config" in arguments[1]:
            return '{"status":"passed"}'
        return ""

    def run_result(
        self,
        arguments: list[str],
        *,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> uatctl.CommandResult:
        self.calls.append(arguments)
        self.call_options.append(
            {
                "check": False,
                "timeout_seconds": timeout_seconds,
                "environment": environment,
            }
        )
        return self.results.get(tuple(arguments), uatctl.CommandResult(0, "", ""))


class FakeValidator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _result(self, name: str) -> validators.ValidationResult:
        self.calls.append(name)
        return validators.ValidationResult.success(evidence={"validator": name}, next_state=name)

    def verify_storage(self) -> validators.ValidationResult:
        return self._result("storage_verified")

    def verify_models(self) -> validators.ValidationResult:
        return self._result("models_verified")

    def verify_config(self) -> validators.ValidationResult:
        return self._result("config_verified")


def _set_runtime_inspect(
    runner: FakeRunner,
    image: dict[str, str],
    record: dict,
    *,
    runtime_image_id: str | None = None,
    descriptor: dict | None = None,
) -> None:
    tag = image["local_tag"]
    runtime_image_id = runtime_image_id or record["config_digest"]
    values = {
        "{{.Id}}": runtime_image_id,
        "{{json .RepoTags}}": json.dumps([tag]),
        "{{json .RepoDigests}}": json.dumps([f"{tag.split(':', 1)[0]}@{runtime_image_id}"]),
        "{{.Os}}": "linux",
        "{{.Architecture}}": "amd64",
        "{{json .Config.User}}": json.dumps(record.get("config_user", "")),
        '{{with .Config.Labels}}{{index . "org.opencontainers.image.revision"}}{{end}}': record.get(
            "revision", ""
        ),
        '{{with .Config.Labels}}{{index . "org.opencontainers.image.version"}}{{end}}': record.get(
            "version", ""
        ),
        "{{json .RootFS.Layers}}": json.dumps([item["diff_id"] for item in record["layers"]]),
        "{{json .Descriptor}}": json.dumps(descriptor),
    }
    for template, value in values.items():
        runner.outputs[("/usr/bin/docker", "image", "inspect", "--format", template, tag)] = value


def _paths(tmp_path: Path) -> uatctl.Paths:
    config = tmp_path / "etc" / "smartscan" / "uat"
    data = tmp_path / "mnt" / "data" / "smartscan" / "uat"
    upload = tmp_path / "home" / "szhzx" / "smartscan-uat-offline-images"
    libexec = tmp_path / "usr" / "local" / "libexec" / "smartscan"
    for path in (config, data, upload, libexec):
        path.mkdir(parents=True)
    if os.name != "nt":
        upload.chmod(0o700)
    for name in (
        "docker-compose.uat.yml",
        "shared-8077-smartscan-location.conf",
        "smartscan_uat_validators.py",
        "uat-2026-11-26-worker-fix.json",
    ):
        asset = libexec / name
        asset.write_text("fixed", encoding="utf-8")
        asset.chmod(0o644)
    return uatctl.Paths(
        config_root=config,
        data_root=data,
        upload_root=upload,
        installed_release=config / "release-manifest.json",
        installed_map=config / "release-map.json",
        local_images_env=config / "local-images.env",
        image_identities=config / "image-identities.json",
        state_file=config / "uatctl-state.json",
        migration_failure=config / "migration-failure.json",
        deploy_env=config / "deploy.env",
        runtime_env=config / "runtime.env",
        activation_plan=config / "nginx-activation.json",
        staged_nginx=config / "nginx-smartscan-8077.locations.conf",
        active_nginx=tmp_path / "etc" / "nginx" / "snippets" / "smartscan-uat-8077.locations.conf",
        compose_file=libexec / "docker-compose.uat.yml",
        nginx_template=libexec / "shared-8077-smartscan-location.conf",
        validator_module=libexec / "smartscan_uat_validators.py",
        candidate_release=upload / "candidate-release.json",
        previous_release=config / "previous-release-manifest.json",
        previous_map=config / "previous-release-map.json",
        previous_local_images=config / "previous-local-images.env",
        previous_identities=config / "previous-image-identities.json",
        previous_web_release=config / "previous-web-release-manifest.json",
        previous_web_map=config / "previous-web-release-map.json",
        previous_web_local_images=config / "previous-web-local-images.env",
        previous_web_identities=config / "previous-web-image-identities.json",
        publish_network_evidence=config / "publish-network-evidence.json",
    )


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _write_candidate_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


@pytest.mark.skipif(os.name == "nt", reason="需要POSIX真实权限语义")
@pytest.mark.parametrize("mode", [0o640, 0o644, 0o664, 0o777])
def test_candidate_release_rejects_every_mode_except_exact_0600(tmp_path: Path, mode: int) -> None:
    candidate = tmp_path / "candidate-release.json"
    _write_candidate_json(candidate, {"schema_version": "1.1"})
    candidate.chmod(mode)

    with pytest.raises(uatctl.ControllerError, match="fixed_json_mode_invalid"):
        uatctl._load_json(
            candidate,
            policy=uatctl.FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600,
            expected_deploy_uid=TEST_UID,
        )


@pytest.mark.skipif(os.name == "nt", reason="需要POSIX真实权限语义")
def test_candidate_release_and_internal_json_both_use_exact_0600(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    internal = tmp_path / "internal.json"
    _write_candidate_json(candidate, {"kind": "candidate"})
    _write_json(internal, {"kind": "internal"})

    assert (
        uatctl._load_json(
            candidate,
            policy=uatctl.FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600,
            expected_deploy_uid=TEST_UID,
        )["kind"]
        == "candidate"
    )
    assert (
        uatctl._load_json(
            internal,
            policy=uatctl.FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=TEST_UID,
        )["kind"]
        == "internal"
    )

    internal.chmod(0o644)
    with pytest.raises(uatctl.ControllerError, match="fixed_json_mode_invalid"):
        uatctl._load_json(
            internal,
            policy=uatctl.FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
            expected_root_uid=TEST_UID,
        )


@pytest.mark.skipif(os.name == "nt", reason="需要POSIX真实权限语义")
def test_candidate_release_rejects_wrong_owner_links_and_abnormal_type(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    _write_candidate_json(candidate, {"kind": "candidate"})
    policy = uatctl.FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600

    with pytest.raises(uatctl.ControllerError, match="fixed_json_owner_invalid"):
        uatctl._load_json(candidate, policy=policy, expected_deploy_uid=TEST_UID + 1)

    hardlink = tmp_path / "candidate-hardlink.json"
    os.link(candidate, hardlink)
    with pytest.raises(uatctl.ControllerError, match="fixed_json_links_invalid"):
        uatctl._load_json(candidate, policy=policy, expected_deploy_uid=TEST_UID)
    hardlink.unlink()

    symlink = tmp_path / "candidate-symlink.json"
    symlink.symlink_to(candidate)
    with pytest.raises(uatctl.ControllerError, match="fixed_json_invalid"):
        uatctl._load_json(symlink, policy=policy, expected_deploy_uid=TEST_UID)

    directory = tmp_path / "candidate-directory.json"
    directory.mkdir()
    with pytest.raises(uatctl.ControllerError, match="fixed_json_invalid"):
        uatctl._load_json(directory, policy=policy, expected_deploy_uid=TEST_UID)


def _repository_lf_sha256(path: Path) -> str:
    """安装摘要绑定仓库的 LF 规范字节，不受 Windows 工作树换行影响。"""
    value = path.read_bytes().replace(b"\r\n", b"\n")
    assert b"\r" not in value
    return hashlib.sha256(value).hexdigest()


def test_status_starts_without_state_and_reports_first_step(tmp_path: Path) -> None:
    controller = uatctl.Controller(
        _paths(tmp_path), FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID
    )
    assert controller.status()["next_required"] == "preflight"
    assert not controller.paths.state_file.exists()


def test_preflight_is_idempotent_and_rejects_missing_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    fixed_hash = hashlib.sha256(b"fixed").hexdigest()
    monkeypatch.setattr(
        uatctl,
        "INSTALLED_ASSET_SHA256",
        {
            "docker-compose.uat.yml": fixed_hash,
            "shared-8077-smartscan-location.conf": fixed_hash,
            "smartscan_uat_validators.py": fixed_hash,
        },
    )
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller.preflight()
    before = paths.state_file.read_bytes()
    controller.preflight()
    assert paths.state_file.read_bytes() == before

    runner.outputs[("/usr/bin/docker", "network", "ls", "--format", "{{.Name}}")] = (
        "smartscan-uat-data"
    )
    with pytest.raises(uatctl.ControllerError, match="fixed_network_missing"):
        uatctl.Controller(
            _paths(tmp_path / "missing"),
            runner,
            root_uid=TEST_UID,
            deploy_uid=TEST_UID,
        ).preflight()


def test_state_machine_rejects_skipping_release_and_import(tmp_path: Path) -> None:
    controller = uatctl.Controller(
        _paths(tmp_path), FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID
    )
    with pytest.raises(uatctl.ControllerError, match="state_prerequisite_missing"):
        controller.import_images()
    with pytest.raises(uatctl.ControllerError, match="state_prerequisite_missing"):
        controller.start_database()
    with pytest.raises(uatctl.ControllerError, match="state_prerequisite_missing"):
        controller.start_core()


def test_native_validators_are_structured_and_do_not_spawn_legacy_executors(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    validator = FakeValidator()
    controller = uatctl.Controller(
        paths,
        runner,
        root_uid=TEST_UID,
        deploy_uid=TEST_UID,
        validator=validator,
    )

    controller._record("preflight")
    controller.verify_storage()
    controller.verify_models()
    controller.verify_config()

    assert validator.calls == ["storage_verified", "models_verified", "config_verified"]
    assert runner.calls == []
    source = Path(uatctl.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "smartscan-uat-loop-storage",
        "smartscan-uat-ocr-model",
        "smartscan-uat-deployment-preparation",
        "_run_legacy_executor",
        "SUDO_COMMAND=",
        "SUDO_USER=",
    ):
        assert forbidden not in source


def test_upgrade_continues_after_preflight_without_repeating_it(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(
        paths,
        runner,
        root_uid=TEST_UID,
        deploy_uid=TEST_UID,
        validator=FakeValidator(),
    )
    controller._record("preflight")
    before_history = list(controller._state()["history"])

    assert controller.status()["completed"] == ["preflight"]
    assert controller.status()["next_required"] == "storage_verified"
    controller.verify_storage()

    state = controller._state()
    assert state["completed"] == ["preflight", "storage_verified"]
    assert state["history"][0] == before_history[0]
    assert all("network" not in item for call in runner.calls for item in call)
    with pytest.raises(uatctl.ControllerError, match="state_prerequisite_missing"):
        controller.accept_release()


def test_current_storage_checkpoint_survives_model_failure_and_resumes(tmp_path: Path) -> None:
    class FailingValidator(FakeValidator):
        def verify_models(self) -> validators.ValidationResult:
            raise validators.ValidationError("model_fixture_changed")

    paths = _paths(tmp_path)
    controller = uatctl.Controller(
        paths,
        FakeRunner(),
        root_uid=TEST_UID,
        deploy_uid=TEST_UID,
        validator=FailingValidator(),
    )
    controller._record("preflight")
    controller._record("storage_verified")

    with pytest.raises(uatctl.ControllerError, match="model_fixture_changed"):
        controller.verify_models()
    assert controller.status()["completed"] == ["preflight", "storage_verified"]
    assert controller.status()["next_required"] == "models_verified"

    controller.validator = FakeValidator()
    controller.verify_models()
    assert controller.status()["completed"] == [
        "preflight",
        "storage_verified",
        "models_verified",
    ]


def test_subprocess_runner_fails_closed_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args, **kwargs):
        raise uatctl.subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

    monkeypatch.setattr(uatctl.subprocess, "run", timeout)
    with pytest.raises(uatctl.ControllerError, match="command_timeout:sudo"):
        uatctl.SubprocessRunner().run(["/usr/bin/sudo", "-n"], timeout_seconds=1)


def test_resume_stops_at_irreversible_migration_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    sequence: list[str] = []
    safe_steps = (
        "preflight",
        "storage_verified",
        "models_verified",
        "config_verified",
        "release_accepted",
        "images_imported",
        "images_verified",
        "identities_verified",
        "ownership_applied",
        "database_started",
        "database_verified",
    )
    method_names = (
        "preflight",
        "verify_storage",
        "verify_models",
        "verify_config",
        "accept_release",
        "import_images",
        "verify_images",
        "probe_identities",
        "apply_ownership",
        "start_database",
        "verify_database",
    )
    for completed, method in zip(safe_steps, method_names, strict=True):

        def action(step=completed):
            sequence.append(step)
            return controller._record(step)

        monkeypatch.setattr(controller, method, action)
    result = controller.resume_basic_uat()
    assert result["status"] == "waiting_confirmation"
    assert result["next_required"] == "run-migrations"
    assert sequence == list(safe_steps)
    assert "migrations_completed" not in controller.status()["completed"]


def test_identity_probe_uses_no_network_no_mount_no_secret_and_limits(tmp_path: Path) -> None:
    controller = uatctl.Controller(
        _paths(tmp_path), FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID
    )
    controller.runner.outputs[
        (
            "/usr/bin/docker",
            "run",
            "--rm",
            "--name",
            "smartscan-uat-identity-api-u",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--cpus",
            "0.10",
            "--memory",
            "32m",
            "--pids-limit",
            "16",
            "--entrypoint",
            "/usr/bin/id",
            "smartscan-uat-api:sha256-80aea0a27279",
            "-u",
        )
    ] = "10001"
    assert controller._probe("api", "smartscan-uat-api:sha256-80aea0a27279", "u") == 10001
    command = controller.runner.calls[-1]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command and "--cap-drop" in command
    assert not any("env" in item.casefold() or "mount" in item.casefold() for item in command)


def test_offline_image_mapping_includes_disabled_ai_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    services = ("postgres", "api", "worker", "ai-gateway", "web", "ops")
    images = [
        {
            "service": service,
            "local_tag": f"smartscan-uat-{service}:sha256-{'a' * 12}",
            "runtime_key": f"SMARTSCAN_UAT_{service.upper().replace('-', '_')}_RUNTIME_IMAGE",
            "archive_name": f"smartscan-{service}-{'a' * 12}-linux-amd64.docker.tar",
        }
        for service in services
    ]
    mapping = {
        "images": [
            {
                "service": image["service"],
                "image_id": f"sha256:{index:064x}",
                "config_digest": f"sha256:{index:064x}",
                "config_user": "10001:10001",
                "revision": "fixed-revision",
                "version": "fixed-version",
                "layers": [
                    {
                        "digest": f"sha256:{index + 10:064x}",
                        "diff_id": f"sha256:{index + 20:064x}",
                        "size": 10,
                    }
                ],
            }
            for index, image in enumerate(images, start=1)
        ]
    }
    monkeypatch.setattr(controller, "_fixed_release", lambda: ({"images": images}, mapping))
    controller._record("images_imported")
    for image, record in zip(images, mapping["images"], strict=True):
        _set_runtime_inspect(runner, image, record)
    compose_call = (
        "/usr/bin/docker",
        "compose",
        "--project-name",
        "smartscan-uat",
        "--env-file",
        str(paths.deploy_env),
        "--env-file",
        str(paths.local_images_env),
        "-f",
        str(paths.compose_file),
        "--profile",
        "ai",
        "config",
        "--images",
    )
    runner.outputs[compose_call] = "\n".join(image["local_tag"] for image in images)

    controller.verify_images()

    assert list(runner.calls[-1]) == list(compose_call)
    assert "smartscan-uat-ai-gateway" in paths.local_images_env.read_text(encoding="utf-8")


def test_containerd_runtime_descriptor_binds_archive_config_layers_and_existing_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    config_digest = f"sha256:{'1' * 64}"
    layer_digest = f"sha256:{'2' * 64}"
    diff_id = f"sha256:{'3' * 64}"
    image = {
        "service": "postgres",
        "local_tag": "smartscan-uat-postgres:sha256-94758173bbe1",
        "archive_name": "smartscan-postgres-94758173bbe1-linux-amd64.docker.tar",
    }
    record = {
        "service": "postgres",
        "config_digest": config_digest,
        "config_user": "70:70",
        "revision": "fixed-revision",
        "version": "17.7",
        "layers": [{"digest": layer_digest, "diff_id": diff_id, "size": 19}],
    }
    archive = paths.upload_root / image["archive_name"]
    with tarfile.open(archive, "w") as bundle:
        config = tarfile.TarInfo(f"{config_digest[7:]}.json")
        config.size = 23
        bundle.addfile(config, io.BytesIO(b"x" * 23))
    expected_digest, expected_size = controller._expected_runtime_descriptor(record, archive)
    descriptor = {
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "digest": expected_digest,
        "size": expected_size,
    }
    _set_runtime_inspect(
        runner,
        image,
        record,
        runtime_image_id=expected_digest.removeprefix("sha256:"),
        descriptor=descriptor,
    )
    monkeypatch.setattr(
        controller,
        "_fixed_release",
        lambda: ({"images": [image]}, {"images": [record]}),
    )
    controller._record("release_accepted")

    controller.import_images()

    assert "images_imported" in controller.status()["completed"]
    assert not any(call[:3] == ["/usr/bin/docker", "load", "--input"] for call in runner.calls)
    evidence = controller._state()["evidence"]["images_imported"]["runtime_identities"]
    assert evidence["postgres"]["runtime_identity_kind"] == "containerd_schema2_descriptor"
    assert evidence["postgres"]["runtime_image_id"] == expected_digest


def test_containerd_runtime_descriptor_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    image = {
        "service": "postgres",
        "local_tag": "smartscan-uat-postgres:sha256-94758173bbe1",
        "archive_name": "smartscan-postgres-94758173bbe1-linux-amd64.docker.tar",
    }
    record = {
        "service": "postgres",
        "config_digest": f"sha256:{'1' * 64}",
        "config_user": "70:70",
        "revision": "fixed-revision",
        "version": "17.7",
        "layers": [
            {
                "digest": f"sha256:{'2' * 64}",
                "diff_id": f"sha256:{'3' * 64}",
                "size": 19,
            }
        ],
    }
    archive = paths.upload_root / image["archive_name"]
    with tarfile.open(archive, "w") as bundle:
        config = tarfile.TarInfo(f"{'1' * 64}.json")
        config.size = 23
        bundle.addfile(config, io.BytesIO(b"x" * 23))
    wrong = f"sha256:{'4' * 64}"
    _set_runtime_inspect(
        runner,
        image,
        record,
        runtime_image_id=wrong,
        descriptor={
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "digest": wrong,
            "size": 1,
        },
    )
    monkeypatch.setattr(
        controller,
        "_fixed_release",
        lambda: ({"images": [image]}, {"images": [record]}),
    )
    controller._record("release_accepted")

    with pytest.raises(uatctl.ControllerError, match="runtime_descriptor_digest_mismatch"):
        controller.import_images()
    assert "images_imported" not in controller.status()["completed"]


def test_identity_probe_and_nginx_paths_do_not_use_legacy_executor_bridge(tmp_path: Path) -> None:
    source = Path(uatctl.__file__).read_text(encoding="utf-8")
    assert "deployment-preparation" not in source
    assert "_run_legacy_executor" not in source

    # Docker身份探测和Nginx命令继续由控制器用固定参数列表直接执行。
    assert "shell=True" not in source
    assert '["/usr/sbin/nginx", "-t"]' in source
    assert '["/usr/sbin/nginx", "-s", "reload"]' in source


def test_wrapper_and_sudoers_reject_parameters_shell_prune_and_wildcards() -> None:
    root = Path(__file__).parents[1]
    wrapper = (root / "deploy/ops/smartscan-uatctl").read_text(encoding="utf-8")
    helper = root / "deploy/ops/smartscan_uatctl.py"
    sudoers = (root / "deploy/sudoers/smartscan-uatctl").read_text(encoding="utf-8")
    assert '[[ "$#" -eq 1 ]]' in wrapper
    assert _repository_lf_sha256(helper) in wrapper
    assert _repository_lf_sha256(root / "deploy/ops/smartscan_uat_validators.py") in wrapper
    assert "sudo bash" not in sudoers and "sudo sh" not in sudoers
    assert "*" not in sudoers
    assert "prune" not in wrapper and "down -v" not in wrapper
    for command in uatctl.COMMANDS:
        assert f"smartscan-uatctl {command}" in sudoers


def test_legacy_executors_and_sudoers_remain_byte_for_byte_unchanged() -> None:
    root = Path(__file__).parents[1]
    expected = {
        "deploy/ops/smartscan-uat-loop-storage": (
            "cce1e8040cae9d6ca0a43ed077b878820ae72aeab2a9285c44a129857f85f6a7"
        ),
        "deploy/sudoers/smartscan-uat-loop-storage": (
            "486f13e2aba23e0c4d48a5ba853d824d0afdfb7faf623f5eff79b33fcabde550"
        ),
        "deploy/ops/smartscan-uat-ocr-model": (
            "8623dfe1bdee24f143e1cc7ee2eee5b12ed17ee16873c374c887a4e2d3e914e2"
        ),
        "deploy/ops/smartscan-uat-ocr-model.sudoers": (
            "e9604f687f6eb5fc336e369036ad010e2fa28a2a5f7d906bc6d52d2c70e3d282"
        ),
    }
    assert {name: _repository_lf_sha256(root / name) for name in expected} == expected


def test_installation_guide_pins_all_controller_assets() -> None:
    root = Path(__file__).parents[1]
    guide = (root / "docs/OPS001P_WEB_LOOPBACK_ENTRY.md").read_text(encoding="utf-8")
    for relative in (
        "deploy/ops/smartscan-uatctl",
        "deploy/ops/smartscan_uatctl.py",
        "deploy/ops/smartscan_uat_validators.py",
        "deploy/sudoers/smartscan-uatctl",
        "deploy/compose/docker-compose.uat.yml",
        "deploy/nginx/shared-8077-smartscan-location.conf.template",
    ):
        assert _repository_lf_sha256(root / relative) in guide


def test_compose_uses_only_local_runtime_images_and_pull_never() -> None:
    root = Path(__file__).parents[1]
    compose = (root / "deploy/compose/docker-compose.uat.yml").read_text(encoding="utf-8")
    assert "pull_policy: always" not in compose
    assert compose.count("pull_policy: never") >= 3
    for key in (
        "POSTGRES",
        "API",
        "WORKER",
        "AI_GATEWAY",
        "WEB",
        "OPS",
    ):
        assert f"SMARTSCAN_UAT_{key}_RUNTIME_IMAGE" in compose


def test_ci_uses_one_network_isolated_daemon_for_import_and_probe() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/uat-offline-images.yml").read_text(encoding="utf-8")
    script = (root / "tools/ci_verify_uat_offline_docker.sh").read_text(encoding="utf-8")
    checkpoint = (root / "tools/ci_verify_uatctl_checkpoint.py").read_text(encoding="utf-8")
    assert "tools/ci_verify_uat_offline_docker.sh" in workflow
    assert "unshare --net" in script
    assert "--bridge=none" in script
    assert "--iptables=false" in script
    assert "--userland-proxy=false" in script
    assert "DOCKER_HOST" in script
    assert "ci_verify_uatctl_checkpoint.py" in script
    assert 'state_machine":"nginx_activation_confirmation' in script
    assert "docker/setup-docker-action@7ec28a010822b4626af4874f9448a4b05ac6f3e5" in workflow
    assert "version: v29.0.2" in workflow
    assert 'SMARTSCAN_DOCKER29_CONTAINERD: "1"' in workflow
    assert "containerd-snapshotter" in workflow
    assert "SMARTSCAN_EXTERNAL_DOCKER=1" in script
    assert "--containerd-namespace=smartscan-ci-legacy" in script
    assert '"https-proxy": "http://127.0.0.1:9"' in workflow
    assert "io.containerd.snapshotter.v1" in script
    controller = (root / "deploy/ops/smartscan_uatctl.py").read_text(encoding="utf-8")
    assert '"load",' in controller
    assert '"none",' in controller
    assert "config --format json" in workflow
    assert 'item.get("pull_policy") == "never"' in workflow
    assert "id: changed_archive" in workflow
    assert 'image["archive_name"]' in workflow
    assert "steps.changed_archive.outputs.name" in workflow
    assert "smartscan-worker-4e1e7532f33a-linux-amd64.docker.tar" not in workflow
    assert "prepare_uploaded_candidate" in checkpoint
    assert "isolated_daemon_internal_urlopen" in checkpoint
    assert '"containerd29"' in checkpoint
    assert '"legacy"' in checkpoint
    assert "smartscan-uat-incremental-upload-{CI_VARIANT}" in checkpoint
    assert "candidate.chmod(0o600)" in checkpoint
    assert "FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600" in controller
    assert "CANDIDATE_RELEASE_PUBLIC_ROOT_0644" not in controller


def test_wrapper_and_python_share_stable_uploaded_candidate_contract() -> None:
    root = Path(__file__).parents[1]
    wrapper = (root / "deploy/ops/smartscan-uatctl").read_text(encoding="utf-8")
    controller = (root / "deploy/ops/smartscan_uatctl.py").read_text(encoding="utf-8")

    contract = uatctl.FIXED_FILE_PERMISSION_CONTRACTS[
        uatctl.FixedFilePolicy.UPLOADED_RELEASE_DEPLOY_0600
    ]
    assert contract.owner_role == "deploy"
    assert contract.mode == 0o600
    assert "CANDIDATE_RELEASE_MODE" not in wrapper
    assert "candidate_release_digest_mismatch" not in wrapper
    assert "/home/szhzx/smartscan-uat-offline-images/candidate-release.json" in controller
    assert "UPLOADED_RELEASE_DEPLOY_0600" in controller
    assert "root_owned" not in controller


def test_controller_accepts_docker_archive_with_registry_evidence(tmp_path: Path) -> None:
    layer = b"fixed-compressed-layer"
    layer_digest = f"sha256:{hashlib.sha256(layer).hexdigest()}"
    diff_id = f"sha256:{hashlib.sha256(b'fixed-uncompressed-layer').hexdigest()}"
    config = json.dumps(
        {
            "architecture": "amd64",
            "os": "linux",
            "rootfs": {"type": "layers", "diff_ids": [diff_id]},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    config_digest = f"sha256:{hashlib.sha256(config).hexdigest()}"
    platform = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"digest": config_digest, "size": len(config)},
            "layers": [
                {
                    "digest": layer_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(layer),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    platform_digest = f"sha256:{hashlib.sha256(platform).hexdigest()}"
    local_tag = "smartscan-uat-api:sha256-0123456789ab"
    image = {"source": f"ghcr.io/j4meshub/smartscan-api@{platform_digest}", "local_tag": local_tag}
    record = {
        "archive_format": "docker-image-archive-v1",
        "platform_manifest": platform_digest,
        "config_digest": config_digest,
        "layers": [
            {
                "digest": layer_digest,
                "diff_id": diff_id,
                "media_type": "application/vnd.oci.image.layer.v1.tar+gzip",
                "size": len(layer),
            }
        ],
    }
    config_name = f"{config_digest[7:]}.json"
    layer_name = f"layers/{layer_digest[7:]}.tar.gz"
    docker_manifest = json.dumps(
        [{"Config": config_name, "RepoTags": [local_tag], "Layers": [layer_name]}],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    archive = tmp_path / "fixed.docker.tar"
    with tarfile.open(archive, "w") as bundle:
        for name, value in (
            ("manifest.json", docker_manifest),
            (config_name, config),
            ("smartscan-evidence/source.json", platform),
            ("smartscan-evidence/platform-manifest.json", platform),
            (layer_name, layer),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(value)
            bundle.addfile(member, io.BytesIO(value))

    uatctl.Controller._verify_uploaded_archive(image, record, archive)


def test_state_file_never_contains_secret_values(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("preflight", {"summary": "no-secret"})
    text = paths.state_file.read_text(encoding="utf-8")
    assert "password" not in text.casefold()
    assert json.loads(text)["secrets_included"] is False


def _incremental_fixture() -> tuple[dict, dict]:
    services = ("postgres", "api", "worker", "ai-gateway", "web", "ops")
    images, records = [], []
    for index, service in enumerate(services, start=1):
        digest = f"{index:064x}"
        if service == "worker":
            digest = "9957b27924b0eb7ba6819c917a7b32ee2869a8b0bd560f2199f03e3232f3a742"
        image = {
            "service": service,
            "deploy_key": f"SMARTSCAN_UAT_{service.upper().replace('-', '_')}_IMAGE",
            "runtime_key": f"SMARTSCAN_UAT_{service.upper().replace('-', '_')}_RUNTIME_IMAGE",
            "source": f"ghcr.io/j4meshub/smartscan-{service}@sha256:{digest}",
            "local_tag": f"smartscan-uat-{service}:sha256-{digest[:12]}",
            "archive_name": f"smartscan-{service}-{digest[:12]}-linux-amd64.docker.tar",
        }
        images.append(image)
        records.append(
            {
                "service": service,
                "source": image["source"],
                "local_tag": image["local_tag"],
                "archive_sha256": "a" * 64,
                "platform_manifest": f"sha256:{index + 10:064x}",
                "config_digest": f"sha256:{index + 20:064x}",
                "config_user": "smartscan" if service == "worker" else "10001:10001",
                "revision": "fixed",
                "version": "fixed",
                "layers": [
                    {
                        "digest": f"sha256:{index + 30:064x}",
                        "diff_id": f"sha256:{index + 40:064x}",
                        "size": 1,
                    }
                ],
            }
        )
    return {
        "schema_version": "1.1",
        "release_id": "smartscan-uat-worker-fix",
        "changed_services": ["worker"],
        "images": images,
    }, {"images": records}


def test_incremental_worker_activation_preserves_checkpoint_and_old_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    candidate, mapping = _incremental_fixture()
    _write_candidate_json(paths.candidate_release, candidate)
    candidate_root = paths.upload_root / candidate["release_id"]
    candidate_root.mkdir()
    _write_json(candidate_root / "release-map.json", mapping)
    worker = next(item for item in candidate["images"] if item["service"] == "worker")
    worker_record = next(item for item in mapping["images"] if item["service"] == "worker")
    worker_archive = candidate_root / worker["archive_name"]
    with tarfile.open(worker_archive, "w") as bundle:
        member = tarfile.TarInfo(f"{worker_record['config_digest'][7:]}.json")
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    old_release = {"schema_version": "1.0", "release_id": "old", "images": []}
    old_map = {"images": []}
    _write_json(paths.installed_release, old_release)
    _write_json(paths.installed_map, old_map)
    paths.local_images_env.write_text("OLD=1\n", encoding="utf-8")
    _write_json(
        paths.image_identities,
        {
            "schema_version": "1.1",
            "platform": "linux/amd64",
            "images": {
                "SMARTSCAN_UAT_WORKER_IMAGE": {
                    "runtime_uid": 10001,
                    "runtime_gid": 10001,
                }
            },
        },
    )
    for step in (
        "preflight",
        "storage_verified",
        "models_verified",
        "config_verified",
        "release_accepted",
        "images_imported",
        "images_verified",
        "identities_verified",
        "ownership_applied",
        "database_started",
        "database_verified",
        "migrations_completed",
    ):
        controller._record(step)
    state = controller._state()
    state["pending_release_update"] = {
        "status": "accepted",
        "release_id": candidate["release_id"],
        "manifest_sha256": uatctl._sha256(paths.candidate_release),
    }
    uatctl._atomic_json(paths.state_file, state)
    identity = uatctl.RuntimeImageIdentity(
        runtime_image_id=f"sha256:{'b' * 64}",
        runtime_descriptor_digest=f"sha256:{'b' * 64}",
        runtime_descriptor_size=1,
        runtime_identity_kind="containerd_schema2_descriptor",
        repo_digests=(),
        rootfs_diff_ids=(worker_record["layers"][0]["diff_id"],),
    )
    monkeypatch.setattr(controller, "_candidate_release", lambda: (candidate, mapping))
    monkeypatch.setattr(controller, "_fixed_release", lambda *args, **kwargs: (candidate, mapping))
    monkeypatch.setattr(controller, "_inspect_runtime_image", lambda *args, **kwargs: identity)
    monkeypatch.setattr(controller, "_probe", lambda *args, **kwargs: 10001)
    monkeypatch.setattr(controller, "_verify_incremental_data_ownership", lambda: None)

    result = controller._activate_pending_worker_release()

    assert result["status"] == "passed"
    assert json.loads(paths.previous_release.read_text(encoding="utf-8")) == old_release
    assert json.loads(paths.previous_map.read_text(encoding="utf-8")) == old_map
    assert json.loads(paths.installed_release.read_text(encoding="utf-8")) == candidate
    assert worker["local_tag"] in paths.local_images_env.read_text(encoding="utf-8")
    state = controller._state()
    assert state["pending_release_update"]["status"] == "activated"
    assert state["completed"][-1] == "migrations_completed"


def test_one_step_web_rollback_slot_is_safely_replaced_for_later_release(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    pairs = (
        (paths.installed_release, paths.previous_web_release),
        (paths.installed_map, paths.previous_web_map),
        (paths.local_images_env, paths.previous_web_local_images),
        (paths.image_identities, paths.previous_web_identities),
    )
    for index, (source, backup) in enumerate(pairs):
        source.write_text(f"current-{index}\n", encoding="utf-8")
        backup.write_text(f"older-{index}\n", encoding="utf-8")
        source.chmod(0o600)
        backup.chmod(0o600)

    controller._save_one_step_rollback(pairs)

    for index, (source, backup) in enumerate(pairs):
        assert backup.read_text(encoding="utf-8") == f"current-{index}\n"
        assert source.read_text(encoding="utf-8") == f"current-{index}\n"
        assert not backup.with_name(f".{backup.name}.next.tmp").exists()


def test_one_step_web_rollback_slot_rejects_symbolic_link(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    paths.installed_release.write_text("current\n", encoding="utf-8")
    target = tmp_path / "outside"
    target.write_text("outside\n", encoding="utf-8")
    try:
        paths.previous_web_release.symlink_to(target)
    except OSError:
        pytest.skip("当前环境不允许创建符号链接")

    with pytest.raises(uatctl.ControllerError, match="fixed_json_invalid"):
        controller._save_one_step_rollback(((paths.installed_release, paths.previous_web_release),))


def test_incremental_acceptance_records_pending_without_switching_active_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    candidate, mapping = _incremental_fixture()
    _write_candidate_json(paths.candidate_release, candidate)
    candidate_root = paths.upload_root / candidate["release_id"]
    candidate_root.mkdir()
    _write_json(candidate_root / "release-map.json", mapping)
    active = {"release_id": "accepted-old", "images": []}
    _write_json(paths.installed_release, active)
    for step in (
        "preflight",
        "storage_verified",
        "models_verified",
        "config_verified",
        "release_accepted",
        "migrations_completed",
    ):
        controller._record(step)
    monkeypatch.setattr(controller, "_candidate_release", lambda: (candidate, mapping))

    result = controller.accept_release()

    assert result["step"] == "incremental_release_accepted"
    assert json.loads(paths.installed_release.read_text(encoding="utf-8")) == active
    state = controller._state()
    assert state["completed"][-1] == "migrations_completed"
    assert state["pending_release_update"]["status"] == "accepted"
    assert state["pending_release_update"]["changed_services"] == ["worker"]


def test_web_candidate_accepts_only_at_started_not_verified_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    candidate, mapping = _incremental_fixture()
    candidate["release_id"] = "smartscan-uat-web-fix"
    candidate["changed_services"] = ["web"]
    active = {"release_id": "active-worker-fix", "images": []}
    _write_json(paths.installed_release, active)
    for step in (
        "preflight",
        "storage_verified",
        "models_verified",
        "config_verified",
        "release_accepted",
        "migrations_completed",
        "core_started",
    ):
        controller._record(step)
    monkeypatch.setattr(controller, "_candidate_release", lambda: (candidate, mapping))
    candidate_root = paths.upload_root / candidate["release_id"]
    candidate_root.mkdir(parents=True)
    _write_json(candidate_root / "release-map.json", mapping)
    _write_candidate_json(paths.candidate_release, candidate)

    result = controller.accept_release()

    assert result["step"] == "incremental_release_accepted"
    state = controller._state()
    assert state["pending_release_update"]["changed_services"] == ["web"]
    assert "core_started" in state["completed"]
    assert "core_verified" not in state["completed"]


def test_publish_network_contract_requires_private_slash28_and_explicit_risk(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    candidate = {"release_id": "smartscan-uat-web-fix"}
    root = paths.upload_root / candidate["release_id"]
    root.mkdir()
    evidence = {
        "schema_version": "1.0",
        "network_name": "smartscan-uat-publish",
        "subnet": "172.31.250.0/28",
        "gateway": "172.31.250.1",
        "risk_acknowledgement": "loopback-proxy-has-theoretical-egress",
        "confirmation": {
            "confirmed_by": "shared-server-user",
            "confirmed_at": "2026-11-27T00:00:00+08:00",
            "change_record": "change",
            "validation_record": "validation",
            "rollback_record": "rollback",
        },
    }
    path = root / "publish-network.json"
    _write_json(path, evidence)

    assert controller._publish_network_spec(candidate) == evidence

    evidence["subnet"] = "8.8.8.0/28"
    evidence["gateway"] = "8.8.8.1"
    _write_json(path, evidence)
    with pytest.raises(uatctl.ControllerError, match="publish_network_subnet_invalid"):
        controller._publish_network_spec(candidate)


def test_publish_network_creation_rejects_policy_route_overlap(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    candidate = {"release_id": "smartscan-uat-web-fix"}
    root = paths.upload_root / candidate["release_id"]
    root.mkdir()
    _write_candidate_json(
        root / "publish-network.json",
        {
            "schema_version": "1.0",
            "network_name": "smartscan-uat-publish",
            "subnet": "172.31.250.0/28",
            "gateway": "172.31.250.1",
            "risk_acknowledgement": "loopback-proxy-has-theoretical-egress",
            "confirmation": {
                "confirmed_by": "shared-server-user",
                "confirmed_at": "2026-11-27T00:00:00+08:00",
                "change_record": "change",
                "validation_record": "validation",
                "rollback_record": "rollback",
            },
        },
    )
    runner.results[("/usr/bin/docker", "network", "inspect", "smartscan-uat-publish")] = (
        uatctl.CommandResult(1, "", "not found")
    )
    runner.outputs[("/usr/bin/docker", "network", "ls", "--quiet")] = ""
    runner.outputs[("/usr/sbin/ip", "-j", "-4", "route", "show", "table", "all")] = "[]"
    runner.outputs[("/usr/sbin/ip", "-j", "-4", "address", "show")] = "[]"
    runner.outputs[("/usr/sbin/ip", "-j", "-4", "rule", "show")] = json.dumps(
        [{"from": "172.31.250.4/32", "to": "all", "table": "100"}]
    )

    with pytest.raises(uatctl.ControllerError, match="publish_network_policy_overlap"):
        controller._ensure_publish_network(candidate)

    flattened = [item for command in runner.calls for item in command]
    assert "create" not in flattened


def test_incremental_acceptance_rejects_worker_when_core_already_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    for step in (
        "preflight",
        "storage_verified",
        "models_verified",
        "config_verified",
        "release_accepted",
        "migrations_completed",
        "core_started",
    ):
        controller._record(step)
    candidate, mapping = _incremental_fixture()
    monkeypatch.setattr(controller, "_candidate_release", lambda: (candidate, mapping))

    with pytest.raises(uatctl.ControllerError, match="incremental_core_already_started"):
        controller.accept_release()


def test_start_core_rejects_unrepaired_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("migrations_completed")
    candidate = {
        "changed_services": ["worker"],
        "images": [{"service": "worker", "source": "new"}],
    }
    active = {"images": [{"service": "worker", "source": "old"}]}
    _write_candidate_json(paths.candidate_release, candidate)
    monkeypatch.setattr(controller, "_fixed_release", lambda: (active, {"images": []}))
    with pytest.raises(uatctl.ControllerError, match="repaired_worker_release_not_active"):
        controller.start_core()


def test_completed_migration_is_verified_but_not_run_again(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("database_started")
    controller._record("database_verified")
    controller._record("migrations_completed")

    result = controller.run_migrations()

    assert result["already_complete"] is True
    flattened = [item for command in runner.calls for item in command]
    assert "migrate" not in flattened
    assert "pg_isready" in flattened


def test_migration_uses_fixed_read_only_service_and_records_exact_target(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("database_started")
    controller._record("database_verified")
    prefix = controller._compose_command()
    runner.outputs[
        tuple(
            prefix
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "smartscan",
                "-d",
                "smartscan",
                "-Atqc",
                "SELECT version_num FROM alembic_version",
            ]
        )
    ] = uatctl.MIGRATION_TARGET
    runner.outputs[
        tuple(
            prefix
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "smartscan",
                "-d",
                "smartscan",
                "-Atqc",
                "SELECT to_regclass('public.ai_media_grants')::text",
            ]
        )
    ] = "ai_media_grants"

    result = controller.run_migrations()

    assert result["status"] == "passed"
    migrate = next(command for command in runner.calls if "--exit-code-from" in command)
    assert migrate[-6:] == [
        "up",
        "--no-deps",
        "--abort-on-container-exit",
        "--exit-code-from",
        "migrate",
        "migrate",
    ]
    assert "--rm" not in migrate
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    assert state["evidence"]["migrations_completed"] == {
        "target_revision": "20261022_0024",
        "storage_root": "/tmp/smartscan-data",
        "real_business_storage_mounted": False,
        "raw_output_retained": False,
    }
    assert not paths.migration_failure.exists()


def test_migration_failure_is_redacted_and_does_not_advance_state(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("database_started")
    controller._record("database_verified")
    command = tuple(
        controller._compose_command(
            "up",
            "--no-deps",
            "--abort-on-container-exit",
            "--exit-code-from",
            "migrate",
            "migrate",
        )
    )
    secret = "postgresql://smartscan:never-store-this@postgres/smartscan"
    runner.results[command] = uatctl.CommandResult(
        1,
        "",
        f"OSError: [Errno 30] Read-only file system: data {secret}",
    )

    with pytest.raises(
        uatctl.ControllerError,
        match="migration_failed:migration_storage_read_only:OSError",
    ):
        controller.run_migrations()

    assert "migrations_completed" not in controller.status()["completed"]
    evidence_text = paths.migration_failure.read_text(encoding="utf-8")
    assert secret not in evidence_text
    evidence = json.loads(evidence_text)
    assert evidence["reason_code"] == "migration_storage_read_only"
    assert evidence["exception_type"] == "OSError"
    assert evidence["exit_code"] == 1
    assert evidence["raw_output_retained"] is False
    assert evidence["secrets_included"] is False
    if os.name != "nt":
        assert paths.migration_failure.stat().st_mode & 0o777 == 0o600


def test_migration_partial_revision_failure_closes_without_state_progress(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("database_started")
    controller._record("database_verified", {"observed_revision": "20261022_0023"})
    command = tuple(
        controller._compose_command(
            "up",
            "--no-deps",
            "--abort-on-container-exit",
            "--exit-code-from",
            "migrate",
            "migrate",
        )
    )
    runner.results[command] = uatctl.CommandResult(
        2,
        "",
        "alembic.util.exc.CommandError: Can't locate revision identified by 'invalid'",
    )

    with pytest.raises(uatctl.ControllerError, match="migration_revision_error:CommandError"):
        controller.run_migrations()

    state = controller.status()
    assert "migrations_completed" not in state["completed"]


def test_uat_compose_scopes_bounded_storage_override_to_migrate_only() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "deploy/compose/docker-compose.uat.yml").read_text(encoding="utf-8")
    migrate = text.split("\n  migrate:\n", 1)[1].split("\n  api:\n", 1)[0]
    assert "read_only: true" in text.split("x-common: &common", 1)[1].split("services:", 1)[0]
    assert "SMARTSCAN_STORAGE_ROOT: /tmp/smartscan-data" in migrate
    assert "/tmp:rw,noexec,nosuid,nodev,size=32m" in migrate
    assert "volumes:" not in migrate
    assert "driver: none" in migrate
    assert "SMARTSCAN_STORAGE_ROOT: /tmp/smartscan-data" not in text.split("\n  api:\n", 1)[1]


def test_uat_api_uses_single_bootstrap_process_until_startup_is_concurrency_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "deploy/compose/docker-compose.uat.yml").read_text(encoding="utf-8")
    api = text.split("\n  api:\n", 1)[1].split("\n  worker-cpu-1:\n", 1)[0]
    assert "--workers" in api
    assert '\n      - "1"\n' in api


def test_core_verification_requires_two_workers_and_keeps_ai_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    controller._record("core_started")
    prefix = controller._compose_command()
    runner.outputs[tuple(prefix + ["ps", "--status", "running", "--services"])] = (
        "postgres\napi\nworker-cpu-1\nworker-cpu-2\nnginx\nloopback-proxy"
    )
    runner.outputs[tuple(prefix + ["ps", "-q", "loopback-proxy"])] = "proxy-id"
    runner.outputs[tuple(prefix + ["ps", "-q", "nginx"])] = "web-id"
    runner.outputs[
        tuple(
            prefix
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "smartscan",
                "-d",
                "smartscan",
                "-Atqc",
                (
                    "SELECT count(*) FROM worker_heartbeats "
                    "WHERE heartbeat_at >= CURRENT_TIMESTAMP - INTERVAL '120 seconds'"
                ),
            ]
        )
    ] = "2"
    runner.outputs[("/usr/bin/docker", "inspect", "proxy-id")] = json.dumps(
        [
            {
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18082"}]},
                    "Networks": {
                        "smartscan-uat-edge": {},
                        "smartscan-uat-publish": {},
                    },
                },
                "HostConfig": {
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "NanoCpus": 100_000_000,
                    "Memory": 64 * 1024**2,
                    "PidsLimit": 32,
                    "Tmpfs": {"/tmp": "rw,size=32m"},
                    "LogConfig": {
                        "Type": "json-file",
                        "Config": {"max-file": "3", "max-size": "10m"},
                    },
                },
                "Config": {"User": "101:101", "Env": ["PATH=/usr/bin"]},
                "Mounts": [],
                "State": {"Health": {"Status": "healthy"}},
            }
        ]
    )
    runner.outputs[("/usr/bin/docker", "inspect", "web-id")] = json.dumps(
        [
            {
                "NetworkSettings": {"Networks": {"smartscan-uat-edge": {}}},
                "HostConfig": {
                    "ReadonlyRootfs": True,
                    "PortBindings": {},
                    "NanoCpus": 250_000_000,
                    "Memory": 128 * 1024**2,
                    "PidsLimit": 64,
                },
                "State": {"Health": {"Status": "healthy"}},
            }
        ]
    )
    for service in ("api", "worker-cpu-1", "worker-cpu-2"):
        container_id = f"{service}-id"
        runner.outputs[tuple(prefix + ["ps", "-q", service])] = container_id
        runner.outputs[("/usr/bin/docker", "inspect", container_id)] = json.dumps(
            [{"State": {"Health": {"Status": "healthy"}}}]
        )
    runner.outputs[("/usr/bin/docker", "top", "web-id", "-eo", "comm")] = "COMMAND\nnginx\nnginx"
    runner.outputs[
        ("/usr/bin/docker", "stats", "--no-stream", "--format", "{{.MemPerc}}", "web-id")
    ] = "12.50%"
    runner.results[("/usr/bin/docker", "logs", "--since", "5m", "web-id")] = uatctl.CommandResult(
        0, "", ""
    )
    runner.outputs[("/usr/bin/docker", "port", "proxy-id", "8080/tcp")] = "127.0.0.1:18082"

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(uatctl.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    result = controller.verify_core()

    assert result["status"] == "passed"
    assert "core_verified" in controller.status()["completed"]


def test_stop_core_preserves_database_migrations_release_and_resume_checkpoint(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    runner = FakeRunner()
    controller = uatctl.Controller(paths, runner, root_uid=TEST_UID, deploy_uid=TEST_UID)
    for step in (
        "preflight",
        "storage_verified",
        "models_verified",
        "config_verified",
        "release_accepted",
        "images_imported",
        "images_verified",
        "identities_verified",
        "ownership_applied",
        "database_started",
        "database_verified",
        "migrations_completed",
        "core_started",
    ):
        controller._record(step)

    result = controller.stop_core()

    assert result["next_required"] == "core_started"
    status = controller.status()
    assert "database_started" in status["completed"]
    assert "database_verified" in status["completed"]
    assert "migrations_completed" in status["completed"]
    assert "core_started" not in status["completed"]
    assert status["next_required"] == "core_started"
    assert controller._state()["core_stop_checkpoint"]["status"] == "passed"
    flattened = [item for command in runner.calls for item in command]
    for service in ("loopback-proxy", "nginx", "worker-cpu-2", "worker-cpu-1", "api"):
        assert service in flattened


def test_web_rollback_uses_web_evidence_after_safe_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    controller = uatctl.Controller(paths, FakeRunner(), root_uid=TEST_UID, deploy_uid=TEST_UID)
    release, mapping = _incremental_fixture()
    release["changed_services"] = ["web"]
    release["release_id"] = "previous-web-release"
    release["platform"] = "linux/amd64"
    mapping["platform"] = "linux/amd64"
    _write_json(paths.previous_web_release, release)
    _write_json(paths.previous_web_map, mapping)
    env = (
        "\n".join(f"{item['runtime_key']}={item['local_tag']}" for item in release["images"]) + "\n"
    )
    paths.previous_web_local_images.write_text(env, encoding="utf-8")
    identities: dict[str, dict[str, object]] = {}
    runtime_by_service: dict[str, uatctl.RuntimeImageIdentity] = {}
    for image, record in zip(release["images"], mapping["images"], strict=True):
        runtime = uatctl.RuntimeImageIdentity(
            runtime_image_id=f"sha256:{record['service'][0] * 64}",
            runtime_descriptor_digest=f"sha256:{record['service'][0] * 64}",
            runtime_descriptor_size=1,
            runtime_identity_kind="containerd_schema2_descriptor",
            repo_digests=(),
            rootfs_diff_ids=(record["layers"][0]["diff_id"],),
        )
        runtime_by_service[record["service"]] = runtime
        identities[image["deploy_key"]] = {
            "runtime_image_id": runtime.runtime_image_id,
            "runtime_descriptor_digest": runtime.runtime_descriptor_digest,
            "local_tag": image["local_tag"],
        }
    _write_json(paths.previous_web_identities, {"images": identities})
    for active in (
        paths.installed_release,
        paths.installed_map,
        paths.local_images_env,
        paths.image_identities,
    ):
        active.write_text("active\n", encoding="utf-8")
    state = controller._state()
    state["core_stop_checkpoint"] = {"status": "passed"}
    state["pending_release_update"] = {
        "status": "activated",
        "changed_services": ["web"],
    }
    uatctl._atomic_json(paths.state_file, state)

    monkeypatch.setattr(
        controller,
        "_inspect_runtime_image",
        lambda image, *_args: runtime_by_service[image["service"]],
    )
    result = controller.rollback_images()

    assert result["status"] == "passed"
    assert json.loads(paths.installed_release.read_text(encoding="utf-8")) == release
    assert json.loads(paths.installed_map.read_text(encoding="utf-8")) == mapping
    assert paths.local_images_env.read_text(encoding="utf-8") == env
    assert controller._state()["pending_release_update"]["status"] == "rolled_back"
