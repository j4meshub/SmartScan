from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path != "/v1/file":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", "attachment; filename=fixture.bin")
        self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
        self.send_header("ETag", '"smartscan-nginx-fixture"')
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Accel-Redirect", "/_smartscan_files/fixture/sample.bin")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
