"""SmartScan 16 会话混合负载驱动器；仅用于隔离的本地或 staging 环境。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import ipaddress
import json
import os
import platform
import statistics
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw

LoadRole = Literal["book_upload", "browse", "document_upload"]
NON_PRODUCTION_CONFIRMATION = "I_CONFIRM_STAGING_NOT_PRODUCTION"


class LoadConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class LoadAccount:
    virtual_user: str
    username: str
    password: str = field(repr=False)
    role: LoadRole


@dataclass(frozen=True)
class OperationRecord:
    operation: str
    virtual_user: str
    latency_ms: float
    success: bool
    status_code: int | None
    error_code: str | None


@dataclass
class LoadRecorder:
    records: list[OperationRecord] = field(default_factory=list)
    accepted_pages: set[str] = field(default_factory=set)
    observed_job_pages: set[str] = field(default_factory=set)
    latest_job_status_by_page: dict[str, str] = field(default_factory=dict)
    isolation_violations: int = 0

    def record(
        self,
        operation: str,
        virtual_user: str,
        started: float,
        *,
        success: bool,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.records.append(
            OperationRecord(
                operation=operation,
                virtual_user=virtual_user,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                success=success,
                status_code=status_code,
                error_code=error_code,
            )
        )


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if not 0 <= quantile <= 1:
        raise ValueError("分位数必须位于 0 到 1")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def validate_target(
    base_url: str,
    *,
    allowed_hosts: set[str] | None = None,
    confirmation: str | None = None,
) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LoadConfigurationError("目标必须是明确的 HTTP 或 HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LoadConfigurationError("目标 URL 不能包含凭据、查询参数或片段")
    if parsed.path not in {"", "/"}:
        raise LoadConfigurationError("目标 URL 不能包含路径")
    host = parsed.hostname.lower()
    loopback = host == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if not loopback:
        normalized_hosts = {item.lower() for item in allowed_hosts or set()}
        if host not in normalized_hosts:
            raise LoadConfigurationError("非回环目标必须通过 --allowed-host 精确允许")
        if confirmation != NON_PRODUCTION_CONFIRMATION:
            raise LoadConfigurationError("非回环目标必须显式确认是隔离的非生产环境")
    return f"{parsed.scheme}://{parsed.netloc}"


def load_accounts(path: Path, environment: dict[str, str] | None = None) -> list[LoadAccount]:
    environment = os.environ if environment is None else environment
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadConfigurationError("无法读取负载账号清单") from exc
    if not isinstance(payload, dict) or set(payload) != {"accounts"}:
        raise LoadConfigurationError("账号清单根节点只能包含 accounts")
    entries = payload["accounts"]
    if not isinstance(entries, list) or len(entries) != 16:
        raise LoadConfigurationError("混合负载必须恰好配置 16 个账号")
    usernames: set[str] = set()
    accounts: list[LoadAccount] = []
    roles: list[LoadRole] = ["book_upload"] * 8 + ["browse"] * 4 + ["document_upload"] * 4
    for index, (entry, role) in enumerate(zip(entries, roles, strict=True), start=1):
        if not isinstance(entry, dict) or set(entry) != {"username", "password_env"}:
            raise LoadConfigurationError(f"账号 {index} 字段无效")
        username = entry["username"]
        password_env = entry["password_env"]
        if not isinstance(username, str) or not username.strip():
            raise LoadConfigurationError(f"账号 {index} 缺少用户名")
        if username in usernames:
            raise LoadConfigurationError(f"用户名重复：{username}")
        if not isinstance(password_env, str) or not password_env.strip():
            raise LoadConfigurationError(f"账号 {index} 缺少密码环境变量名")
        password = environment.get(password_env, "")
        if not password:
            raise LoadConfigurationError(f"环境变量 {password_env} 未设置")
        usernames.add(username)
        accounts.append(LoadAccount(f"vu-{index:02d}", username, password, role))
    return accounts


def load_resource_metrics(path: Path) -> dict[str, Any]:
    required = {
        "source",
        "observed_from",
        "observed_to",
        "cpu_peak_percent",
        "memory_peak_bytes",
        "oom_events",
        "disk_free_start_bytes",
        "disk_free_end_bytes",
        "temp_directory_peak_bytes",
        "worker_concurrency",
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadConfigurationError("无法读取服务器资源指标") from exc
    if not isinstance(payload, dict) or set(payload) != required:
        raise LoadConfigurationError("服务器资源指标字段不完整或包含未知字段")
    for field_name in ("source", "observed_from", "observed_to"):
        if not isinstance(payload[field_name], str) or not payload[field_name].strip():
            raise LoadConfigurationError(f"服务器资源指标缺少 {field_name}")
    for field_name in required - {"source", "observed_from", "observed_to"}:
        value = payload[field_name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise LoadConfigurationError(f"服务器资源指标 {field_name} 必须是非负数")
    if payload["worker_concurrency"] < 1:
        raise LoadConfigurationError("Worker 并发必须大于零")
    return payload


def make_synthetic_jpeg() -> bytes:
    image = Image.new("RGB", (1280, 960), (242, 242, 236))
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 50, 1220, 910), outline=(30, 30, 30), width=8)
    for y in range(140, 850, 55):
        draw.line((130, y, 1130, y + 8), fill=(45, 45, 45), width=5)
    output = io.BytesIO()
    image.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


def summarize_records(records: list[OperationRecord]) -> dict[str, Any]:
    grouped: dict[str, list[OperationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.operation].append(record)
    summary: dict[str, Any] = {}
    for operation, items in sorted(grouped.items()):
        latencies = [item.latency_ms for item in items]
        successes = sum(item.success for item in items)
        errors = Counter(item.error_code for item in items if item.error_code)
        summary[operation] = {
            "requests": len(items),
            "successes": successes,
            "failures": len(items) - successes,
            "success_rate": round(successes / len(items), 6),
            "latency_ms_p50": round(statistics.median(latencies), 3),
            "latency_ms_p95": round(percentile(latencies, 0.95), 3),
            "latency_ms_max": round(max(latencies), 3),
            "errors": dict(sorted(errors.items())),
        }
    return summary


class MixedLoadRunner:
    def __init__(
        self,
        *,
        base_url: str,
        accounts: list[LoadAccount],
        duration_seconds: float,
        upload_interval_seconds: float,
        browse_interval_seconds: float,
        request_timeout_seconds: float,
        resource_metrics: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.accounts = accounts
        self.duration_seconds = duration_seconds
        self.upload_interval_seconds = upload_interval_seconds
        self.browse_interval_seconds = browse_interval_seconds
        self.recorder = LoadRecorder()
        self.run_id = uuid.uuid4().hex[:12]
        self.image_bytes = make_synthetic_jpeg()
        self.image_sha256 = hashlib.sha256(self.image_bytes).hexdigest()
        self.resource_metrics = resource_metrics
        limits = httpx.Limits(max_connections=32, max_keepalive_connections=20)
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(request_timeout_seconds),
            limits=limits,
            follow_redirects=False,
            transport=transport,
        )

    async def _request(
        self,
        account: LoadAccount,
        operation: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        expected_statuses: set[int] = frozenset({200}),
        **kwargs: Any,
    ) -> httpx.Response | None:
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        started = time.perf_counter()
        try:
            response = await self.client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            self.recorder.record(
                operation,
                account.virtual_user,
                started,
                success=False,
                error_code=type(exc).__name__,
            )
            return None
        success = response.status_code in expected_statuses
        self.recorder.record(
            operation,
            account.virtual_user,
            started,
            success=success,
            status_code=response.status_code,
            error_code=None if success else f"http_{response.status_code}",
        )
        return response if success else None

    async def _login(self, account: LoadAccount) -> tuple[str, str] | None:
        response = await self._request(
            account,
            "login",
            "POST",
            "/v1/auth/login",
            json={"username": account.username, "password": account.password},
        )
        if response is None:
            return None
        try:
            token = response.json()["access_token"]
        except (ValueError, KeyError, TypeError):
            return None
        me = await self._request(account, "me", "GET", "/v1/me", token=token)
        if me is None:
            return None
        try:
            return token, str(me.json()["id"])
        except (ValueError, KeyError, TypeError):
            return None

    async def _create_project(self, account: LoadAccount, token: str, mode: str) -> str | None:
        response = await self._request(
            account,
            "create_project",
            "POST",
            "/v1/projects",
            token=token,
            expected_statuses={201},
            json={
                "title": f"负载测试-{self.run_id}-{account.virtual_user}",
                "mode": mode,
                "reading_order": "ltr",
            },
        )
        if response is None:
            return None
        try:
            return str(response.json()["id"])
        except (ValueError, KeyError, TypeError):
            return None

    async def _observe_job(
        self,
        account: LoadAccount,
        token: str,
        page_id: str,
        upload_started: float,
    ) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            response = await self._request(account, "list_jobs", "GET", "/v1/jobs", token=token)
            if response is not None:
                try:
                    jobs = response.json()
                except ValueError:
                    jobs = []
                for item in jobs:
                    if isinstance(item, dict) and item.get("page_id"):
                        observed_page = str(item["page_id"])
                        self.recorder.observed_job_pages.add(observed_page)
                        if item.get("status"):
                            self.recorder.latest_job_status_by_page[observed_page] = str(
                                item["status"]
                            )
                if page_id in self.recorder.observed_job_pages:
                    self.recorder.observed_job_pages.add(page_id)
                    self.recorder.record(
                        "task_visible",
                        account.virtual_user,
                        upload_started,
                        success=True,
                        status_code=200,
                    )
                    return
            await asyncio.sleep(0.1)
        self.recorder.record(
            "task_visible",
            account.virtual_user,
            upload_started,
            success=False,
            error_code="task_not_visible_within_2s",
        )

    async def _upload_once(
        self,
        account: LoadAccount,
        token: str,
        project_id: str,
        counter: int,
    ) -> None:
        upload_started = time.perf_counter()
        response = await self._request(
            account,
            "create_upload",
            "POST",
            "/v1/uploads",
            token=token,
            expected_statuses={201},
            json={
                "project_id": project_id,
                "file_name": f"synthetic-{counter:05d}.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": len(self.image_bytes),
                "sha256": self.image_sha256,
                "idempotency_key": f"load:{self.run_id}:{account.virtual_user}:{counter}",
            },
        )
        if response is None:
            return
        try:
            upload = response.json()
            upload_id = str(upload["id"])
            chunk_size = int(upload["chunk_size"])
        except (ValueError, KeyError, TypeError):
            return
        for chunk_index, offset in enumerate(range(0, len(self.image_bytes), chunk_size)):
            chunk = self.image_bytes[offset : offset + chunk_size]
            receipt = await self._request(
                account,
                "upload_chunk",
                "PUT",
                f"/v1/uploads/{upload_id}/chunks/{chunk_index}",
                token=token,
                headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
                content=chunk,
            )
            if receipt is None:
                return
        completed = await self._request(
            account,
            "complete_upload",
            "POST",
            f"/v1/uploads/{upload_id}/complete",
            token=token,
            expected_statuses={202},
        )
        if completed is None:
            return
        try:
            page_id = str(completed.json()["id"])
        except (ValueError, KeyError, TypeError):
            return
        self.recorder.accepted_pages.add(page_id)
        await self._observe_job(account, token, page_id, upload_started)

    async def _browse_once(
        self,
        account: LoadAccount,
        token: str,
        user_id: str,
    ) -> None:
        projects_response = await self._request(
            account, "list_projects", "GET", "/v1/projects", token=token
        )
        projects: list[dict[str, Any]] = []
        if projects_response is not None:
            try:
                projects = [item for item in projects_response.json() if isinstance(item, dict)]
            except (ValueError, TypeError):
                projects = []
            self.recorder.isolation_violations += sum(
                item.get("owner_user_id") != user_id for item in projects
            )
        jobs_response = await self._request(account, "list_jobs", "GET", "/v1/jobs", token=token)
        if jobs_response is not None:
            try:
                for item in jobs_response.json():
                    if isinstance(item, dict) and item.get("page_id"):
                        page_id = str(item["page_id"])
                        self.recorder.observed_job_pages.add(page_id)
                        if item.get("status"):
                            self.recorder.latest_job_status_by_page[page_id] = str(item["status"])
            except (ValueError, TypeError):
                pass
        if projects:
            project_id = projects[0].get("id")
            if project_id:
                pages_response = await self._request(
                    account,
                    "list_pages",
                    "GET",
                    f"/v1/projects/{project_id}/pages",
                    token=token,
                )
                if pages_response is not None:
                    try:
                        pages = pages_response.json()
                    except ValueError:
                        pages = []
                    if pages and isinstance(pages[0], dict) and pages[0].get("id"):
                        await self._request(
                            account,
                            "download_page",
                            "GET",
                            f"/v1/pages/{pages[0]['id']}/content",
                            token=token,
                        )

    async def _run_account(self, account: LoadAccount, deadline: float) -> None:
        authenticated = await self._login(account)
        if authenticated is None:
            return
        token, user_id = authenticated
        project_id = None
        if account.role != "browse":
            mode = "book" if account.role == "book_upload" else "document"
            project_id = await self._create_project(account, token, mode)
            if project_id is None:
                return
        counter = 0
        next_relogin = time.monotonic() + 30
        while time.monotonic() < deadline:
            if account.role == "browse":
                if time.monotonic() >= next_relogin:
                    refreshed = await self._login(account)
                    if refreshed is not None:
                        token, user_id = refreshed
                    next_relogin = time.monotonic() + 30
                await self._browse_once(account, token, user_id)
                await asyncio.sleep(self.browse_interval_seconds)
            else:
                counter += 1
                assert project_id is not None
                await self._upload_once(account, token, project_id, counter)
                await asyncio.sleep(self.upload_interval_seconds)

    async def run(self) -> dict[str, Any]:
        started_at = datetime.now(UTC)
        monotonic_start = time.monotonic()
        deadline = monotonic_start + self.duration_seconds
        try:
            await asyncio.gather(
                *(self._run_account(account, deadline) for account in self.accounts)
            )
        finally:
            await self.client.aclose()
        actual_duration = time.monotonic() - monotonic_start
        missing_jobs = self.recorder.accepted_pages - self.recorder.observed_job_pages
        roles = Counter(account.role for account in self.accounts)
        job_statuses = Counter(self.recorder.latest_job_status_by_page.values())
        operations = summarize_records(self.recorder.records)
        non_processing = [
            record.latency_ms
            for record in self.recorder.records
            if record.operation in {"login", "me", "list_projects", "list_jobs", "list_pages"}
        ]
        task_visible = [
            record for record in self.recorder.records if record.operation == "task_visible"
        ]
        report = {
            "schema_version": 1,
            "run_id": self.run_id,
            "target": self.base_url,
            "started_at": started_at.isoformat(),
            "configured_duration_seconds": self.duration_seconds,
            "actual_duration_seconds": round(actual_duration, 3),
            "acceptance_duration_met": actual_duration >= 1800,
            "virtual_users": len(self.accounts),
            "roles": dict(sorted(roles.items())),
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
            },
            "synthetic_image": {
                "size_bytes": len(self.image_bytes),
                "sha256": self.image_sha256,
            },
            "operations": operations,
            "non_processing_latency_ms_p95": round(percentile(non_processing, 0.95), 3),
            "accepted_pages": len(self.recorder.accepted_pages),
            "observed_job_pages": len(self.recorder.observed_job_pages),
            "missing_job_count": len(missing_jobs),
            "task_visible_within_2s_rate": 0.0
            if not task_visible
            else round(sum(item.success for item in task_visible) / len(task_visible), 6),
            "isolation_violations": self.recorder.isolation_violations,
            "job_statuses": dict(sorted(job_statuses.items())),
            "server_resource_metrics": self.resource_metrics,
        }
        report["gate_passed"] = bool(
            report["acceptance_duration_met"]
            and report["virtual_users"] == 16
            and report["non_processing_latency_ms_p95"] < 1000
            and report["missing_job_count"] == 0
            and report["isolation_violations"] == 0
            and report["task_visible_within_2s_rate"] == 1.0
            and report["server_resource_metrics"] is not None
            and report["server_resource_metrics"]["oom_events"] == 0
            and report["job_statuses"].get("failed", 0) == 0
            and operations.get("download_page", {}).get("successes", 0) > 0
            and all(item["failures"] == 0 for item in operations.values())
        )
        return report


def markdown_report(report: dict[str, Any]) -> str:
    rows = [
        "# SmartScan 16 会话混合负载报告",
        "",
        f"- 运行 ID：`{report['run_id']}`",
        f"- 目标：`{report['target']}`",
        f"- 配置/实际时长：{report['configured_duration_seconds']:.1f} / {report['actual_duration_seconds']:.1f} 秒",
        f"- 虚拟用户：{report['virtual_users']}（书页上传 {report['roles'].get('book_upload', 0)}、浏览 {report['roles'].get('browse', 0)}、普通扫描 {report['roles'].get('document_upload', 0)}）",
        f"- 非处理请求 P95：{report['non_processing_latency_ms_p95']:.3f} ms",
        f"- 已受理页面 / 已观察任务：{report['accepted_pages']} / {report['observed_job_pages']}",
        f"- 任务缺失：{report['missing_job_count']}",
        f"- 2 秒内任务可见率：{report['task_visible_within_2s_rate']:.2%}",
        f"- 隔离违规：{report['isolation_violations']}",
        f"- 最新任务状态：`{json.dumps(report['job_statuses'], ensure_ascii=False, sort_keys=True)}`",
        f"- 正式时长满足：{'是' if report['acceptance_duration_met'] else '否'}",
        f"- 服务器资源指标：{'已提供' if report['server_resource_metrics'] is not None else '未提供'}",
        f"- 门禁结果：{'通过' if report['gate_passed'] else '未通过'}",
        "",
        "| 操作 | 请求 | 成功 | 失败 | 成功率 | P50 ms | P95 ms | 最大 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for operation, item in report["operations"].items():
        rows.append(
            f"| {operation} | {item['requests']} | {item['successes']} | {item['failures']} | "
            f"{item['success_rate']:.2%} | {item['latency_ms_p50']:.3f} | "
            f"{item['latency_ms_p95']:.3f} | {item['latency_ms_max']:.3f} |"
        )
    rows.extend(
        [
            "",
            "报告不包含用户名、密码、令牌、图片内容或响应正文。短时冒烟和非目标硬件结果不能解除正式容量门禁。",
        ]
    )
    return "\n".join(rows) + "\n"


def write_reports(report: dict[str, Any], output_directory: Path) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "mixed-load-report.json"
    markdown_path = output_directory / "mixed-load-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 SmartScan 16 会话混合负载")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--accounts", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=1800)
    parser.add_argument("--upload-interval-seconds", type=float, default=15)
    parser.add_argument("--browse-interval-seconds", type=float, default=1)
    parser.add_argument("--request-timeout-seconds", type=float, default=15)
    parser.add_argument("--allowed-host", action="append", default=[])
    parser.add_argument("--confirm-non-production")
    parser.add_argument("--allow-short-run", action="store_true")
    parser.add_argument("--resource-metrics", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/load"))
    parser.add_argument("--fail-on-gate", action="store_true")
    args = parser.parse_args()
    if args.duration_seconds < 1800 and not args.allow_short_run:
        raise LoadConfigurationError("少于 1800 秒的运行必须显式使用 --allow-short-run")
    for value, label in (
        (args.duration_seconds, "运行时长"),
        (args.upload_interval_seconds, "上传间隔"),
        (args.browse_interval_seconds, "浏览间隔"),
        (args.request_timeout_seconds, "请求超时"),
    ):
        if value <= 0:
            raise LoadConfigurationError(f"{label}必须大于零")
    base_url = validate_target(
        args.base_url,
        allowed_hosts=set(args.allowed_host),
        confirmation=args.confirm_non_production,
    )
    accounts = load_accounts(args.accounts)
    resource_metrics = (
        load_resource_metrics(args.resource_metrics) if args.resource_metrics is not None else None
    )
    runner = MixedLoadRunner(
        base_url=base_url,
        accounts=accounts,
        duration_seconds=args.duration_seconds,
        upload_interval_seconds=args.upload_interval_seconds,
        browse_interval_seconds=args.browse_interval_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        resource_metrics=resource_metrics,
    )
    report = asyncio.run(runner.run())
    json_path, markdown_path = write_reports(report, args.output)
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{markdown_path}")
    print(f"门禁结果：{'通过' if report['gate_passed'] else '未通过'}")
    return 2 if args.fail_on_gate and not report["gate_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
