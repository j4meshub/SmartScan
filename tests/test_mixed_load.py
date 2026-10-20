from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from tools.mixed_load import (
    NON_PRODUCTION_CONFIRMATION,
    LoadConfigurationError,
    LoadRecorder,
    MixedLoadRunner,
    load_accounts,
    load_resource_metrics,
    markdown_report,
    percentile,
    summarize_records,
    validate_target,
    write_reports,
)


def account_manifest(path: Path, *, duplicate: bool = False) -> Path:
    accounts = [
        {
            "username": "load-01" if duplicate else f"load-{index:02d}",
            "password_env": "LOAD_PASSWORD",
        }
        for index in range(1, 17)
    ]
    path.write_text(json.dumps({"accounts": accounts}), encoding="utf-8")
    return path


def test_target_defaults_to_loopback_and_requires_explicit_staging_acknowledgement() -> None:
    assert validate_target("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert validate_target("http://localhost:8000") == "http://localhost:8000"

    with pytest.raises(LoadConfigurationError, match="精确允许"):
        validate_target("https://staging.example.com")
    with pytest.raises(LoadConfigurationError, match="确认"):
        validate_target("https://staging.example.com", allowed_hosts={"staging.example.com"})
    assert (
        validate_target(
            "https://staging.example.com",
            allowed_hosts={"staging.example.com"},
            confirmation=NON_PRODUCTION_CONFIRMATION,
        )
        == "https://staging.example.com"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/server",
        "https://user:secret@example.com",
        "https://example.com/api",
        "https://example.com?token=secret",
    ],
)
def test_target_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(LoadConfigurationError):
        validate_target(
            url,
            allowed_hosts={"example.com"},
            confirmation=NON_PRODUCTION_CONFIRMATION,
        )


def test_account_manifest_assigns_exact_mixed_roles_without_exposing_password(
    tmp_path: Path,
) -> None:
    path = account_manifest(tmp_path / "accounts.json")
    accounts = load_accounts(path, {"LOAD_PASSWORD": "not-written-to-report"})

    assert len(accounts) == 16
    assert [account.role for account in accounts[:8]] == ["book_upload"] * 8
    assert [account.role for account in accounts[8:12]] == ["browse"] * 4
    assert [account.role for account in accounts[12:]] == ["document_upload"] * 4
    assert accounts[0].virtual_user == "vu-01"
    assert "not-written-to-report" not in repr(accounts[0])


def test_account_manifest_rejects_missing_secret_or_duplicate_user(tmp_path: Path) -> None:
    path = account_manifest(tmp_path / "accounts.json")
    with pytest.raises(LoadConfigurationError, match="未设置"):
        load_accounts(path, {})

    duplicate_path = account_manifest(tmp_path / "duplicate.json", duplicate=True)
    with pytest.raises(LoadConfigurationError, match="重复"):
        load_accounts(duplicate_path, {"LOAD_PASSWORD": "secret"})


def test_recorder_summary_and_reports_contain_metrics_but_no_credentials(tmp_path: Path) -> None:
    recorder = LoadRecorder()
    started = time.perf_counter() - 0.01
    recorder.record("login", "vu-01", started, success=True, status_code=200)
    recorder.record(
        "list_jobs",
        "vu-01",
        started,
        success=False,
        status_code=503,
        error_code="http_503",
    )
    operations = summarize_records(recorder.records)
    assert operations["login"]["success_rate"] == 1.0
    assert operations["list_jobs"]["failures"] == 1
    assert operations["list_jobs"]["errors"] == {"http_503": 1}

    report = {
        "run_id": "run-1",
        "target": "http://127.0.0.1:8000",
        "configured_duration_seconds": 5.0,
        "actual_duration_seconds": 5.0,
        "virtual_users": 16,
        "roles": {"book_upload": 8, "browse": 4, "document_upload": 4},
        "non_processing_latency_ms_p95": 10.0,
        "accepted_pages": 2,
        "observed_job_pages": 2,
        "missing_job_count": 0,
        "task_visible_within_2s_rate": 1.0,
        "isolation_violations": 0,
        "job_statuses": {"ready": 2},
        "server_resource_metrics": None,
        "acceptance_duration_met": False,
        "gate_passed": False,
        "operations": operations,
    }
    json_path, markdown_path = write_reports(report, tmp_path)
    combined = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert "not-written-to-report" not in combined
    assert "密码" not in json_path.read_text(encoding="utf-8")
    assert "正式时长满足：否" in markdown_report(report)


def test_percentile_is_interpolated_and_validated() -> None:
    assert percentile([], 0.95) == 0
    assert percentile([10], 0.95) == 10
    assert percentile([0, 100], 0.95) == 95
    with pytest.raises(ValueError, match="分位数"):
        percentile([1], 2)


def test_full_mixed_runner_tracks_tasks_and_isolation_with_mock_transport(tmp_path: Path) -> None:
    accounts = load_accounts(
        account_manifest(tmp_path / "accounts.json"), {"LOAD_PASSWORD": "secret"}
    )
    projects: dict[str, list[dict[str, str]]] = {}
    pages: dict[str, list[str]] = {}
    upload_owner: dict[str, str] = {}
    sequence = 0

    def token(request: httpx.Request) -> str:
        return request.headers.get("Authorization", "Bearer anonymous").split(" ", 1)[-1]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sequence
        path = request.url.path
        owner = token(request)
        if path == "/v1/auth/login":
            username = json.loads(request.content)["username"]
            return httpx.Response(200, json={"access_token": f"token-{username}"})
        if path == "/v1/me":
            return httpx.Response(200, json={"id": owner})
        if path == "/v1/projects" and request.method == "POST":
            project = {"id": f"project-{owner}", "owner_user_id": owner}
            projects.setdefault(owner, []).append(project)
            return httpx.Response(201, json=project)
        if path == "/v1/projects":
            return httpx.Response(200, json=projects.get(owner, []))
        if path == "/v1/uploads" and request.method == "POST":
            sequence += 1
            upload_id = f"upload-{sequence}"
            upload_owner[upload_id] = owner
            size = json.loads(request.content)["size_bytes"]
            return httpx.Response(201, json={"id": upload_id, "chunk_size": size})
        if "/chunks/" in path:
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/complete"):
            upload_id = path.split("/")[-2]
            page_id = f"page-{upload_id}"
            pages.setdefault(upload_owner[upload_id], []).append(page_id)
            return httpx.Response(202, json={"id": page_id})
        if path == "/v1/jobs":
            return httpx.Response(
                200,
                json=[{"page_id": page_id, "status": "queued"} for page_id in pages.get(owner, [])],
            )
        if path.endswith("/pages"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    runner = MixedLoadRunner(
        base_url="http://127.0.0.1:8000",
        accounts=accounts,
        duration_seconds=0.1,
        upload_interval_seconds=0.2,
        browse_interval_seconds=0.02,
        request_timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    report = asyncio.run(runner.run())

    assert report["virtual_users"] == 16
    assert report["accepted_pages"] == 12
    assert report["missing_job_count"] == 0
    assert report["task_visible_within_2s_rate"] == 1.0
    assert report["isolation_violations"] == 0
    assert report["job_statuses"] == {"queued": 12}
    assert report["acceptance_duration_met"] is False
    assert report["gate_passed"] is False


def test_resource_metrics_are_strict_and_require_nonzero_worker_concurrency(
    tmp_path: Path,
) -> None:
    metrics = {
        "source": "test-monitor",
        "observed_from": "2026-10-20T00:00:00Z",
        "observed_to": "2026-10-20T00:30:00Z",
        "cpu_peak_percent": 180.0,
        "memory_peak_bytes": 1024,
        "oom_events": 0,
        "disk_free_start_bytes": 4096,
        "disk_free_end_bytes": 3072,
        "temp_directory_peak_bytes": 512,
        "worker_concurrency": 2,
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics), encoding="utf-8")
    assert load_resource_metrics(path) == metrics

    metrics["worker_concurrency"] = 0
    path.write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(LoadConfigurationError, match="Worker"):
        load_resource_metrics(path)
