"""Loopback-only HTTP bridge for the bundled workbench interface.

The workbench is a local application, not a web service. It binds an ephemeral
port on 127.0.0.1 behind an unguessable per-launch path token, rejects foreign
Host/Origin headers, and exposes an explicit action allowlist through the
service. Only bundled interface files and service-authorized reports are read
from disk; the bridge never accepts arbitrary paths from the frontend.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_BODY_BYTES = 256 * 1024
ASSET_SUFFIXES = {
    ".html", ".css", ".js", ".woff2", ".svg", ".txt", ".png", ".ico",
}
ASSET_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], handler, *, service,
                 web_root: Path) -> None:
        super().__init__(address, handler)
        self.service = service
        self.web_root = web_root.resolve()
        self.token = secrets.token_urlsafe(24)
        self.host = address[0]
        self.port = self.server_address[1]

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.origin}/{self.token}/"

    def allowed_hosts(self) -> set[str]:
        return {
            f"{self.host}:{self.port}",
            f"localhost:{self.port}",
        }


class BridgeHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer
    protocol_version = "HTTP/1.1"
    server_version = "DNSMuggle-Workbench"
    sys_version = ""

    # -- request validation -------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Never write request paths/tokens to a terminal.
        return

    def _trusted(self) -> bool:
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts():
            return False
        origin = self.headers.get("Origin")
        if origin is not None:
            allowed = {f"http://{name}" for name in self.server.allowed_hosts()}
            if origin not in allowed:
                return False
        return True

    def _send(self, status: int, body: bytes, content_type: str,
              *, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

    def _error(self, status: int, message: str) -> None:
        payload = json.dumps({"ok": False, "error": message}).encode("utf-8")
        self._send(status, payload, "application/json; charset=utf-8")

    # -- routes -------------------------------------------------------------

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        if not self._trusted():
            self._error(403, "This bridge accepts only the local workbench.")
            return
        prefix = f"/{self.server.token}/"
        path = unquote(urlsplit(self.path).path)
        if not path.startswith(prefix):
            self._error(404, "Not found.")
            return
        relative = path[len(prefix):]
        if relative.startswith("reports/"):
            self._serve_report(relative[len("reports/"):])
            return
        self._serve_asset(relative or "index.html")

    def do_POST(self) -> None:  # noqa: N802
        if not self._trusted():
            self._error(403, "This bridge accepts only the local workbench.")
            return
        if urlsplit(self.path).path != f"/{self.server.token}/api":
            self._error(404, "Not found.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "Invalid request length.")
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._error(413, "Request body is too large.")
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "Request body must be JSON.")
            return
        if not isinstance(body, dict) or not isinstance(body.get("action"), str):
            self._error(400, "A JSON object with an action is required.")
            return
        action = body["action"]
        payload = body.get("payload", {})
        if not isinstance(payload, dict):
            self._error(400, "Payload must be a JSON object.")
            return
        try:
            result = self._dispatch(action, payload)
        except Exception as exc:  # noqa: BLE001 - surfaced to the interface
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self._send(200, encoded, "application/json; charset=utf-8",
                   extra={"Content-Security-Policy": CSP})

    # -- files and actions --------------------------------------------------

    def _serve_asset(self, relative: str) -> None:
        candidate = (self.server.web_root / relative).resolve()
        try:
            candidate.relative_to(self.server.web_root)
        except ValueError:
            self._error(404, "Not found.")
            return
        relative_parts = Path(relative).parts
        if (candidate.suffix.lower() not in ASSET_SUFFIXES
                or any(part.startswith(".") for part in relative_parts)
                or not candidate.is_file()):
            self._error(404, "Not found.")
            return
        content_type = ASSET_TYPES.get(
            candidate.suffix.lower(), "application/octet-stream"
        )
        body = candidate.read_bytes()
        self._send(200, body, content_type,
                   extra={"Content-Security-Policy": CSP})

    def _serve_report(self, raw_id: str) -> None:
        try:
            report_id = int(raw_id)
        except ValueError:
            self._error(404, "Not found.")
            return
        result = self.server.service.request("report_content", {"id": report_id})
        if not result.get("ok"):
            self._error(404, result.get("error", "Report not found."))
            return
        info = result["data"]
        path = Path(info["path"])
        try:
            body = path.read_bytes()
        except OSError as exc:
            self._error(404, f"Report file is unavailable: {exc}")
            return
        content_type = "application/pdf" if info["format"] == "pdf" else "text/plain; charset=utf-8"
        safe_name = Path(info["filename"]).name.replace('"', "")
        disposition = f'attachment; filename="{safe_name}"'
        self._send(200, body, content_type, extra={
            "Content-Disposition": disposition,
            "Content-Security-Policy": CSP,
        })

    def _dispatch(self, action: str, payload: dict) -> dict:
        service = self.server.service
        if action == "open_lab":
            return launch_lab_tools()
        result = service.request(action, payload)
        if action == "export_report" and result.get("ok"):
            report_id = int(result["data"]["id"])
            result["data"]["url"] = f"/{self.server.token}/reports/{report_id}"
        return result


def launch_lab_tools() -> dict:
    """Start the legacy Tkinter lab window in its own process."""
    subprocess.Popen(
        [sys.executable, "-m", "app.lab_main"],
        close_fds=True,
    )
    return {"ok": True, "data": {"started": True}}


def build_server(service, web_root: Path) -> WorkbenchServer:
    return WorkbenchServer(("127.0.0.1", 0), BridgeHandler,
                           service=service, web_root=web_root)


def serve(service, web_root: Path) -> tuple[WorkbenchServer, threading.Thread]:
    server = build_server(service, web_root)
    thread = threading.Thread(target=server.serve_forever,
                              name="workbench-http", daemon=True)
    thread.start()
    return server, thread