"""验证 Nginx internal 文件发送、Range 与外部直访阻断。"""

from __future__ import annotations

import argparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

EXPECTED = b"0123456789abcdefghijklmnopqrstuvwxyz\n"


def _request(url: str, *, range_header: str | None = None) -> tuple[int, bytes, object]:
    headers = {"Range": range_header} if range_header else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=5) as response:
        return response.status, response.read(), response.headers


def verify(base_url: str) -> None:
    base_url = base_url.rstrip("/")
    try:
        _request(f"{base_url}/_smartscan_files/fixture/sample.bin")
    except HTTPError as exc:
        if exc.code != 404:
            raise AssertionError(f"internal 路径直访应返回 404，实际为 {exc.code}") from exc
    else:
        raise AssertionError("internal 路径不能被外部直接访问")

    status, body, headers = _request(f"{base_url}/api/v1/file")
    if status != 200 or body != EXPECTED:
        raise AssertionError("鉴权代理后的完整文件响应不匹配")
    if headers.get("X-Accel-Redirect") is not None:
        raise AssertionError("X-Accel-Redirect 内部头不得泄露给客户端")
    if headers.get("ETag") != '"smartscan-nginx-fixture"':
        raise AssertionError("ETag 未从 API 契约保留")
    if headers.get("Cache-Control") != "private, max-age=0, must-revalidate":
        raise AssertionError("私有缓存策略未保留")
    if "attachment" not in headers.get("Content-Disposition", ""):
        raise AssertionError("附件下载响应头未保留")

    status, body, headers = _request(f"{base_url}/api/v1/file", range_header="bytes=10-15")
    if status != 206 or body != EXPECTED[10:16]:
        raise AssertionError("Nginx 单区间续传结果不匹配")
    if headers.get("Content-Range") != f"bytes 10-15/{len(EXPECTED)}":
        raise AssertionError("Content-Range 不匹配")


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 Nginx internal 文件发送链路")
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    args = parser.parse_args()
    verify(args.base_url)
    print("Nginx internal 文件发送、Range 和直访阻断验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
