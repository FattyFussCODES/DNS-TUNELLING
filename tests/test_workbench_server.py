"""The workbench bridge stays local and only serves known content."""

from __future__ import annotations

import http.client
import json
from pathlib import Path

import pytest

from app.workbench.server import MAX_BODY_BYTES, serve
from app.workbench.service import WorkbenchService


class FakeService:
    def __init__(self, report: Path, report_format: str = "txt") -> None:
        self.report = report
        self.report_format = report_format
        self.closed = False

    def request(self, action: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        if action == "bootstrap":
            return {"ok": True, "data": {"version": "test"}}
        if action == "export_report":
            return {"ok": True, "data": {
                "id": 7, "filename": self.report.name,
                "format": self.report_format,
            }}
        if action == "report_content":
            if payload.get("id") != 7:
                return {"ok": False, "error": "Report not found."}
            return {"ok": True, "data": {
                "filename": self.report.name,
                "format": self.report_format,
                "path": str(self.report),
            }}
        if action == "snapshot":
            return {"ok": True, "data": {"total": 0}}
        return {"ok": False, "error": f"Unknown action: {action}"}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def bridge(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>Workbench</title>",
                                    encoding="utf-8")
    (web / "app.js").write_text("const ready = true;\n", encoding="utf-8")
    (web / "ignored.ini").write_text("not served\n", encoding="utf-8")
    report = tmp_path / "workbench-report.txt"
    report.write_bytes(b"Observed 0 queries.\n")
    service = FakeService(report)
    server, thread = serve(service, web)
    yield server, service
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _request(server, method: str, path: str, body: bytes | None = None,
             headers: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    result = (response.status, dict(response.getheaders()), payload)
    connection.close()
    return result


def test_assets_require_the_launch_token(bridge):
    server, _ = bridge
    status, _, body = _request(server, "GET", "/index.html")
    assert status == 404
    assert b"Workbench" not in body

    status, headers, body = _request(server, "GET", f"/{server.token}/")
    assert status == 200
    assert b"Workbench" in body
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in headers["Content-Security-Policy"]


def test_foreign_host_header_is_rejected(bridge):
    server, _ = bridge
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    connection.putrequest("GET", f"/{server.token}/", skip_host=True)
    connection.putheader("Host", "rebind.example")
    connection.endheaders()
    response = connection.getresponse()
    body = response.read()
    assert response.status == 403
    assert b"Workbench" not in body
    connection.close()


def test_static_files_are_limited_to_the_web_directory(bridge):
    server, _ = bridge
    assert _request(server, "GET", f"/{server.token}/app.js")[0] == 200
    assert _request(server, "GET", f"/{server.token}/ignored.ini")[0] == 404
    assert _request(server, "GET", f"/{server.token}/../pyproject.toml")[0] == 404
    assert _request(server, "GET", f"/{server.token}/%2e%2e/pyproject.toml")[0] == 404


def test_actions_reject_foreign_origins_and_invalid_bodies(bridge):
    server, _ = bridge
    path = f"/{server.token}/api"
    payload = json.dumps({"action": "bootstrap"}).encode()
    status, _, body = _request(
        server, "POST", path, payload,
        {"Content-Type": "application/json", "Origin": "https://example.test"},
    )
    assert status == 403

    status, _, body = _request(
        server, "POST", path, b"{not json",
        {"Content-Type": "application/json"},
    )
    assert status == 400

    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    connection.putrequest("POST", path)
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
    connection.endheaders()
    response = connection.getresponse()
    response.read()
    assert response.status == 413
    connection.close()


def test_actions_round_trip_and_reports_download_by_id(bridge):
    server, _ = bridge
    path = f"/{server.token}/api"
    payload = json.dumps({"action": "snapshot", "payload": {"hours": 24}}).encode()
    status, headers, body = _request(
        server, "POST", path, payload, {"Content-Type": "application/json"},
    )
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body) == {"ok": True, "data": {"total": 0}}

    export = json.dumps({"action": "export_report", "payload": {"id": 7}}).encode()
    status, _, body = _request(
        server, "POST", path, export, {"Content-Type": "application/json"},
    )
    result = json.loads(body)
    assert result["ok"] is True
    download_path = result["data"]["url"]

    status, headers, body = _request(server, "GET", download_path)
    assert status == 200
    assert body == b"Observed 0 queries.\n"
    assert headers["Content-Disposition"] == 'attachment; filename="workbench-report.txt"'


def test_unknown_report_is_not_read(bridge):
    server, _ = bridge
    status, headers, body = _request(server, "GET", f"/{server.token}/reports/999")
    assert status == 404
    assert "Content-Disposition" not in headers
    assert b"Observed" not in body


def test_real_service_exports_generated_report(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    service = WorkbenchService(tmp_path / "data")
    server, thread = serve(service, web)
    try:
        report = service.request("generate_report", {"hours": 24, "format": "txt"})
        assert report["ok"]
        report_id = report["data"]["id"]
        path = f"/{server.token}/api"
        body = json.dumps({"action": "export_report", "payload": {"id": report_id}}).encode()
        status, _, raw = _request(server, "POST", path, body)
        assert status == 200
        exported = json.loads(raw)
        assert exported["ok"]
        status, _, raw = _request(server, "GET", exported["data"]["url"])
        assert status == 200
        assert b"DNSmuggle Research Report" in raw
        body = json.dumps({"action": "export_report", "payload": {"id": 999}}).encode()
        status, _, raw = _request(server, "POST", path, body)
        assert status == 200
        assert not json.loads(raw)["ok"]
        for invalid in ([], False, "", None):
            body = json.dumps({"action": "bootstrap", "payload": invalid}).encode()
            assert _request(server, "POST", path, body)[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()