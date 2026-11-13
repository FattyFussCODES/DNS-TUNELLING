"""Workbench backend: real observations, aggregates, persistence and reports."""

from __future__ import annotations

import sqlite3
import socket
import time
from pathlib import Path

import pytest

from app import protocol
from app.detector import Detector, name_entropy
from app.workbench.reports import reportlab_available
from app.workbench.service import WorkbenchService
from app.workbench.store import (
    ObservationFilter,
    Store,
    database_path,
    utc_now_ms,
)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "workbench"


@pytest.fixture()
def service(data_dir: Path):
    instance = WorkbenchService(data_dir)
    try:
        yield instance
    finally:
        instance.close()


def _ok(response: dict) -> dict:
    assert response["ok"] is True, response
    return response["data"]


def _snapshot(service: WorkbenchService, **payload) -> dict:
    payload.setdefault("hours", 24)
    return _ok(service.request("snapshot", payload))


def _seed(data_dir: Path, rows: list[dict], session: dict | None = None):
    """Insert observations directly, returning (session_id, observation ids)."""
    store = Store(database_path(data_dir))
    try:
        session_id = None
        if session is not None:
            session_id = store.start_session(
                session.get("host", "127.0.0.1"),
                session.get("port", 15353),
                now_ms=session.get("at"),
            )
        identifiers = []
        for row in rows:
            qname = row["qname"]
            alerts = [
                {"rule": rule, "reason": f"{rule} evidence"}
                for rule in row.get("alerts", ())
            ]
            identifiers.append(
                store.add_observation(
                    observed_ms=row["at"],
                    qname=qname,
                    source=row.get("source", "10.0.0.1"),
                    entropy=row.get("entropy", name_entropy(qname)),
                    length=len(qname),
                    alerts=alerts,
                    warning=row.get("warning", bool(alerts)),
                    session_id=row.get("session_id", session_id),
                )
            )
        return session_id, identifiers
    finally:
        store.close()


def _free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def test_bootstrap_and_empty_snapshot_use_no_seed_data(service, data_dir):
    bootstrap = _ok(service.request("bootstrap"))
    assert bootstrap["data_dir"] == str(data_dir.resolve())
    assert bootstrap["settings"] == {
        "theme": "dark",
        "host": "127.0.0.1",
        "port": 15353,
    }
    assert [rule["id"] for rule in bootstrap["rules"]] == [
        "length",
        "entropy",
        "rate",
    ]
    assert bootstrap["monitor"]["running"] is False
    assert bootstrap["monitor"]["error"] is None
    assert isinstance(bootstrap["pdf_available"], bool)
    assert "No packet capture" in bootstrap["coverage"]
    assert "2-second" in bootstrap["coverage"]

    snapshot = _snapshot(service, hours=24)
    assert snapshot["total_queries"] == 0
    assert snapshot["matched"] == 0
    assert snapshot["anomalies"] == 0
    assert snapshot["detection_rate"] is None
    assert len(snapshot["series"]) == 24
    assert all(bucket["count"] == 0 for bucket in snapshot["series"])
    assert snapshot["observations"] == []
    assert snapshot["sources"] == []
    assert snapshot["sessions"] == []
    assert snapshot["rule_counts"] == [
        {"rule": "length", "count": 0},
        {"rule": "entropy", "count": 0},
        {"rule": "rate", "count": 0},
    ]


def test_invalid_actions_payloads_and_filters_are_explicit(service):
    assert service.request("not_an_action")["ok"] is False
    assert service.request("snapshot", [])["ok"] is False  # type: ignore[arg-type]
    for payload in (
        {"hours": 2},
        {"hours": True},
        {"hours": 24, "rule": "other"},
        {"hours": 24, "flagged": "yes"},
        {"hours": 24, "offset": -1},
        {"hours": 24, "limit": 0},
        {"hours": 24, "limit": 201},
        {"hours": 24, "limit": False},
        {"hours": 24, "query": 4},
    ):
        response = service.request("snapshot", payload)
        assert response["ok"] is False, payload
        assert response["error"]


def test_settings_are_validated_atomically_and_persist(data_dir):
    first = WorkbenchService(data_dir)
    try:
        for payload in (
            {"theme": "unknown", "host": "127.0.0.1", "port": 15353},
            {"theme": "dark", "host": "localhost", "port": 15353},
            {"theme": "dark", "host": "127.0.0.1", "port": 0},
            {"theme": "dark", "host": "127.0.0.1", "port": True},
            {"theme": "dark", "host": "127.0.0.1", "port": "53"},
        ):
            assert first.request("save_settings", payload)["ok"] is False
        saved = _ok(
            first.request(
                "save_settings",
                {"theme": "light", "host": "127.0.0.2", "port": 15354},
            )
        )
        assert saved == {"theme": "light", "host": "127.0.0.2", "port": 15354}
    finally:
        first.close()

    second = WorkbenchService(data_dir)
    try:
        bootstrap = _ok(second.request("bootstrap"))
        assert bootstrap["settings"] == saved
    finally:
        second.close()


def test_snapshot_counts_anomalies_once_and_filters_before_pagination(
    service, data_dir
):
    now = utc_now_ms()
    rows = [
        {"qname": "a.example.com", "source": "10.0.0.1", "at": now - 300_000},
        {
            "qname": "b.example.com",
            "source": "10.0.0.1",
            "at": now - 240_000,
            "alerts": ("length", "entropy"),
        },
        {
            "qname": "c.example.com",
            "source": "10.0.0.2",
            "at": now - 180_000,
            "alerts": ("rate",),
        },
        {"qname": "d.example.com", "source": "10.0.0.2", "at": now - 120_000},
        {"qname": "e.example.com", "source": "10.0.0.1", "at": now - 60_000},
    ]
    session_id, _ = _seed(
        service.data_dir,
        rows,
        session={"at": now - 600_000, "host": "127.0.0.1", "port": 15353},
    )

    snapshot = _snapshot(service, hours=1)
    assert snapshot["total_queries"] == 5
    assert snapshot["matched"] == 5
    assert snapshot["anomalies"] == 2
    assert snapshot["detection_rate"] == pytest.approx(0.4)
    assert sum(point["count"] for point in snapshot["series"]) == 5
    assert snapshot["sources"] == [
        {"source": "10.0.0.1", "count": 3},
        {"source": "10.0.0.2", "count": 2},
    ]
    assert {
        entry["rule"]: entry["count"] for entry in snapshot["rule_counts"]
    } == {"length": 1, "entropy": 1, "rate": 1}
    assert [item["qname"] for item in snapshot["observations"]] == [
        "e.example.com",
        "d.example.com",
        "c.example.com",
        "b.example.com",
        "a.example.com",
    ]
    assert snapshot["sessions"] == [
        {
            "id": session_id,
            "started_at": snapshot["sessions"][0]["started_at"],
            "stopped_at": None,
            "host": "127.0.0.1",
            "port": 15353,
        }
    ]

    by_source = _snapshot(service, hours=1, source="10.0.0.1")
    assert by_source["total_queries"] == 3
    assert by_source["anomalies"] == 1
    assert sum(point["count"] for point in by_source["series"]) == 3
    assert {item["qname"] for item in by_source["observations"]} == {
        "a.example.com",
        "b.example.com",
        "e.example.com",
    }

    by_rule = _snapshot(service, hours=1, rule="length")
    assert by_rule["total_queries"] == 1
    assert by_rule["anomalies"] == 1
    assert [item["qname"] for item in by_rule["observations"]] == ["b.example.com"]
    assert {
        entry["rule"]: entry["count"] for entry in by_rule["rule_counts"]
    } == {"length": 1, "entropy": 0, "rate": 0}

    flagged = _snapshot(service, hours=1, flagged=True)
    assert flagged["total_queries"] == 2
    assert {item["qname"] for item in flagged["observations"]} == {
        "b.example.com",
        "c.example.com",
    }
    unflagged = _snapshot(service, hours=1, flagged=False)
    assert unflagged["total_queries"] == 3
    assert flagged["anomalies"] + unflagged["anomalies"] == 2

    searched = _snapshot(service, hours=1, query="B.ExAmPle")
    assert searched["total_queries"] == 1
    assert searched["observations"][0]["qname"] == "b.example.com"

    page = _snapshot(service, hours=1, offset=1, limit=2)
    assert page["total_queries"] == 5
    assert page["matched"] == 5
    assert [item["qname"] for item in page["observations"]] == [
        "d.example.com",
        "c.example.com",
    ]
    assert sum(point["count"] for point in page["series"]) == 5
    assert len(page["sources"]) == 2


def test_snapshot_time_range_excludes_older_observations(service):
    now = utc_now_ms()
    _seed(
        service.data_dir,
        [
            {"qname": "old.example.com", "at": now - 2 * 3_600_000 - 60_000},
            {"qname": "new.example.com", "at": now - 60_000},
        ],
    )
    one_hour = _snapshot(service, hours=1)
    assert one_hour["total_queries"] == 1
    assert [item["qname"] for item in one_hour["observations"]] == [
        "new.example.com"
    ]
    assert sum(point["count"] for point in one_hour["series"]) == 1

    day = _snapshot(service, hours=24)
    assert day["total_queries"] == 2
    assert len(day["series"]) == 24
    assert sum(point["count"] for point in day["series"]) == 2

    week = _snapshot(service, hours=168)
    assert week["total_queries"] == 2
    assert len(week["series"]) == 28


def test_detector_cooldown_is_persisted_without_double_counting(service):
    """The detector's real cooldown can leave a suspicious row unflagged."""
    qname = (
        "mfrggzdfmztwq2lknnwg23tpobyxe43u7fqxs3dpq.482534.dnstunnel.cc.cd"
    )
    engine = Detector()
    first = engine.observe(qname, "10.1.1.1", now=5000.0)
    second = engine.observe(qname, "10.1.1.1", now=5000.5)
    assert {alert["rule"] for alert in first["alerts"]} == {"length", "entropy"}
    assert second["alerts"] == []

    store = Store(database_path(service.data_dir))
    try:
        for index, result in enumerate((first, second)):
            store.add_observation(
                observed_ms=utc_now_ms() - 10_000 + index,
                qname=qname,
                source="10.1.1.1",
                entropy=name_entropy(qname),
                length=len(qname),
                alerts=result["alerts"],
                warning=bool(result["warning"]),
                session_id=None,
            )
    finally:
        store.close()

    snapshot = _snapshot(service, hours=1)
    assert snapshot["total_queries"] == 2
    assert snapshot["anomalies"] == 1
    assert snapshot["detection_rate"] == pytest.approx(0.5)
    alert_counts = sorted(
        len(item["alerts"]) for item in snapshot["observations"]
    )
    assert alert_counts[0] == 0
    assert alert_counts[1] >= 2
    assert _snapshot(service, hours=1, flagged=True)["total_queries"] == 1
    assert _snapshot(service, hours=1, flagged=False)["total_queries"] == 1


def test_real_udp_monitor_never_replies_and_records_only_queries(
    service, data_dir
):
    port = _free_udp_port()
    _ok(
        service.request(
            "save_settings",
            {"theme": "dark", "host": "127.0.0.1", "port": port},
        )
    )
    started = _ok(service.request("start_monitor"))
    assert started["running"] is True
    assert started["host"] == "127.0.0.1"
    assert started["port"] == port
    assert started["error"] is None

    tunnel = (
        "mfrggzdfmztwq2lknnwg23tpobyxe43u7fqxs3dpq.482534.dnstunnel.cc.cd"
    )
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.settimeout(0.5)
    try:
        sender.sendto(
            protocol.build_dns_query("www.example.com", 101),
            ("127.0.0.1", port),
        )
        # Observation only: no DNS response may come back.
        with pytest.raises(socket.timeout):
            sender.recvfrom(512)

        sender.sendto(
            protocol.build_dns_query(tunnel, 102), ("127.0.0.1", port)
        )
        sender.sendto(b"\x00\x01\x02", ("127.0.0.1", port))
        qid, _name, question = protocol.parse_dns_query(
            protocol.build_dns_query("reply.example.com", 103)
        )
        sender.sendto(
            protocol.build_dns_response(qid, question),
            ("127.0.0.1", port),
        )

        deadline = time.monotonic() + 5.0
        snapshot = _snapshot(service, hours=1)
        while (
            snapshot["total_queries"] < 2 and time.monotonic() < deadline
        ):
            time.sleep(0.02)
            snapshot = _snapshot(service, hours=1)
        assert snapshot["total_queries"] == 2, snapshot
        assert snapshot["anomalies"] == 1
        assert snapshot["detection_rate"] == pytest.approx(0.5)
        assert sum(point["count"] for point in snapshot["series"]) == 2
        assert snapshot["sources"] == [
            {"source": "127.0.0.1", "count": 2}
        ]
        assert {
            entry["rule"]: entry["count"]
            for entry in snapshot["rule_counts"]
        } == {"length": 1, "entropy": 1, "rate": 0}

        evidence = {
            item["qname"]: item for item in snapshot["observations"]
        }
        assert evidence[tunnel]["alerts"]
        assert {alert["rule"] for alert in evidence[tunnel]["alerts"]} == {
            "length",
            "entropy",
        }
        assert len(evidence[tunnel]["alerts"]) == 2
        assert evidence[tunnel]["warning"] is True
        assert evidence["www.example.com"]["alerts"] == []
        assert evidence["www.example.com"]["warning"] is False

        # Repeating start is idempotent and does not create another session.
        session_count = len(snapshot["sessions"])
        assert session_count == 1
        again = _ok(service.request("start_monitor"))
        assert again["running"] is True
        assert len(_snapshot(service, hours=1)["sessions"]) == session_count

        blocked = service.request(
            "save_settings",
            {"host": "127.0.0.2", "port": port, "theme": "dark"},
        )
        assert blocked["ok"] is False
        assert "stop monitoring" in blocked["error"]
        themed = _ok(
            service.request("save_settings", {"theme": "light"})
        )
        assert themed == {
            "theme": "light",
            "host": "127.0.0.1",
            "port": port,
        }

        stopped = _ok(service.request("stop_monitor"))
        assert stopped["running"] is False
        assert stopped["error"] is None
        after_stop = _snapshot(service, hours=1)
        assert after_stop["sessions"][0]["stopped_at"] is not None
        assert after_stop["monitor"]["running"] is False

        try:
            sender.sendto(
                protocol.build_dns_query("late.example.com", 104),
                ("127.0.0.1", port),
            )
        except OSError:
            pass
        time.sleep(0.2)
        assert _snapshot(service, hours=1)["total_queries"] == 2

        # Closing while running must join the worker and close its session.
        assert _ok(service.request("start_monitor"))["running"] is True
        service.close()
        reopened = WorkbenchService(data_dir)
        try:
            sessions = _snapshot(reopened, hours=1)["sessions"]
            assert len(sessions) == 2
            assert all(item["stopped_at"] is not None for item in sessions)
        finally:
            reopened.close()
    finally:
        sender.close()


def test_occupied_udp_port_is_reported_and_retry_can_succeed(service):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    try:
        _ok(
            service.request(
                "save_settings",
                {"theme": "dark", "host": "127.0.0.1", "port": port},
            )
        )
        failed = _ok(service.request("start_monitor"))
        assert failed["running"] is False
        assert failed["error"]
        assert "bind" in failed["error"].lower()
        bootstrap = _ok(service.request("bootstrap"))
        assert bootstrap["monitor"]["error"] == failed["error"]
        snapshot = _snapshot(service, hours=1)
        assert snapshot["monitor"]["error"] == failed["error"]
        assert snapshot["sessions"] == []
    finally:
        probe.close()

    recovered = _ok(service.request("start_monitor"))
    assert recovered["running"] is True
    assert recovered["error"] is None
    assert recovered["port"] == port
    assert _ok(service.request("stop_monitor"))["running"] is False


def test_txt_report_contains_scope_period_and_real_evidence(service, data_dir):
    now = utc_now_ms()
    _seed(
        service.data_dir,
        [
            {
                "qname": "flagged.example.com",
                "at": now - 10 * 60_000,
                "alerts": ("length", "entropy"),
            },
            {"qname": "quiet.example.com", "at": now - 20 * 60_000},
            {
                "qname": "older.example.com",
                "at": now - 3 * 3_600_000,
                "alerts": ("rate",),
            },
        ],
    )

    day = _ok(service.request("generate_report", {"hours": 24, "format": "txt"}))
    assert day["format"] == "txt"
    assert day["filename"].endswith(".txt")
    assert day["total_queries"] == 3
    assert day["anomalies"] == 2
    assert "24" in day["title"]

    listed = _ok(service.request("reports"))
    assert [entry["id"] for entry in listed] == [day["id"]]
    assert listed[0]["total_queries"] == 3
    assert listed[0]["anomalies"] == 2

    content = _ok(service.request("report_content", {"id": day["id"]}))
    assert content["filename"] == day["filename"]
    assert content["format"] == "txt"
    assert content["text"]
    assert Path(content["path"]).parent == (data_dir / "reports").resolve()
    for needle in (
        "Lab only",
        "No packet capture",
        "2-second per-rule",
        "not detection accuracy",
        "Observed queries: 3",
        "Anomalies (distinct queries with at least one rule alert): 2",
        "flagged.example.com",
        "quiet.example.com",
        "older.example.com",
        "alert length",
        "alert entropy",
        "alert rate",
        "Observation evidence",
    ):
        assert needle in content["text"], needle

    hour = _ok(service.request("generate_report", {"hours": 1, "format": "txt"}))
    assert hour["total_queries"] == 2
    assert hour["anomalies"] == 1
    hour_text = _ok(
        service.request("report_content", {"id": hour["id"]})
    )["text"]
    assert "flagged.example.com" in hour_text
    assert "quiet.example.com" in hour_text
    assert "older.example.com" not in hour_text

    assert service.request("report_content", {"id": 999})["ok"] is False
    assert service.request(
        "generate_report", {"hours": 24, "format": "docx"}
    )["ok"] is False
    assert service.request(
        "generate_report", {"hours": 2, "format": "txt"}
    )["ok"] is False


def test_pdf_is_real_or_explicitly_unavailable(service, data_dir):
    _seed(
        service.data_dir,
        [{"qname": "pdf.example.com", "at": utc_now_ms() - 60_000}],
    )
    before = _ok(service.request("reports"))
    response = service.request("generate_report", {"hours": 24, "format": "pdf"})
    if reportlab_available():
        report = _ok(response)
        assert report["format"] == "pdf"
        assert report["filename"].endswith(".pdf")
        content = _ok(service.request("report_content", {"id": report["id"]}))
        data = Path(content["path"]).read_bytes()
        assert data.startswith(b"%PDF")
        assert data.rstrip().endswith(b"%%EOF")
        assert content["text"] is None
        assert len(_ok(service.request("reports"))) == len(before) + 1
    else:
        assert response["ok"] is False
        assert "reportlab" in response["error"]
        assert _ok(service.request("reports")) == before
        assert list((data_dir / "reports").glob("*.pdf")) == []


def test_observations_settings_and_reports_survive_reopen(data_dir):
    first = WorkbenchService(data_dir)
    try:
        _ok(
            first.request(
                "save_settings",
                {"theme": "light", "host": "127.0.0.1", "port": 15355},
            )
        )
        _seed(
            data_dir,
            [
                {
                    "qname": "persisted.example.com",
                    "at": utc_now_ms() - 60_000,
                    "alerts": ("length",),
                }
            ],
        )
        report = _ok(
            first.request("generate_report", {"hours": 24, "format": "txt"})
        )
    finally:
        first.close()

    second = WorkbenchService(data_dir)
    try:
        bootstrap = _ok(second.request("bootstrap"))
        assert bootstrap["settings"] == {
            "theme": "light",
            "host": "127.0.0.1",
            "port": 15355,
        }
        snapshot = _snapshot(second, hours=24)
        assert snapshot["total_queries"] == 1
        assert snapshot["anomalies"] == 1
        assert snapshot["observations"][0]["qname"] == "persisted.example.com"
        listed = _ok(second.request("reports"))
        assert [entry["id"] for entry in listed] == [report["id"]]
        content = _ok(second.request("report_content", {"id": report["id"]}))
        assert "persisted.example.com" in (content["text"] or "")
    finally:
        second.close()


def test_legacy_settings_schema_accepts_system_and_preserves_values(data_dir):
    data_dir.mkdir(parents=True)
    with sqlite3.connect(database_path(data_dir)) as conn:
        conn.execute(
            "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
            "theme TEXT NOT NULL CHECK (theme IN ('dark', 'light')), "
            "host TEXT NOT NULL, port INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO settings VALUES (1, 'light', '127.0.0.2', 15354)")
    service = WorkbenchService(data_dir)
    try:
        assert _ok(service.request("bootstrap"))["settings"]["theme"] == "light"
        assert _ok(service.request("save_settings", {"theme": "system"})) == {
            "theme": "system", "host": "127.0.0.2", "port": 15354,
        }
    finally:
        service.close()
    service = WorkbenchService(data_dir)
    try:
        assert _ok(service.request("bootstrap"))["settings"]["theme"] == "system"
    finally:
        service.close()


def test_default_directory_migrates_legacy_database_and_reports(tmp_path, monkeypatch):
    legacy = tmp_path / "home" / "DNSMuggle" / "workbench"
    destination = tmp_path / "platform" / "workbench"
    old = WorkbenchService(legacy)
    try:
        _ok(old.request("save_settings", {"theme": "light"}))
        report = _ok(old.request("generate_report", {"hours": 24, "format": "txt"}))
    finally:
        old.close()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("app.workbench.service.default_data_dir", lambda: destination)
    migrated = WorkbenchService()
    try:
        assert _ok(migrated.request("bootstrap"))["settings"]["theme"] == "light"
        content = _ok(migrated.request("report_content", {"id": report["id"]}))
        assert Path(content["path"]).parent == (destination / "reports").resolve()
        assert content["text"]
        assert _ok(migrated.request("export_report", {"id": report["id"]}))["id"] == report["id"]
        assert not migrated.request("export_report", {"id": 999})["ok"]
    finally:
        migrated.close()
    assert database_path(legacy).is_file()
    assert (legacy / "reports" / report["filename"]).is_file()


def test_migration_does_not_overwrite_existing_destination(tmp_path, monkeypatch):
    legacy = tmp_path / "home" / "DNSMuggle" / "workbench"
    destination = tmp_path / "platform" / "workbench"
    old = WorkbenchService(legacy)
    old.request("save_settings", {"theme": "light"})
    old.close()
    existing = WorkbenchService(destination)
    existing.request("save_settings", {"theme": "system"})
    existing.close()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("app.workbench.service.default_data_dir", lambda: destination)
    service = WorkbenchService()
    try:
        assert _ok(service.request("bootstrap"))["settings"]["theme"] == "system"
    finally:
        service.close()


def test_migration_conflict_preserves_both_copies(tmp_path, monkeypatch):
    legacy = tmp_path / "home" / "DNSMuggle" / "workbench"
    destination = tmp_path / "platform" / "workbench"
    old = WorkbenchService(legacy)
    try:
        report = _ok(old.request("generate_report", {"hours": 24, "format": "txt"}))
    finally:
        old.close()
    target = destination / "reports" / report["filename"]
    target.parent.mkdir(parents=True)
    target.write_text("existing report", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr("app.workbench.service.default_data_dir", lambda: destination)
    with pytest.raises(FileExistsError, match="report migration conflict"):
        WorkbenchService()
    assert target.read_text(encoding="utf-8") == "existing report"
    assert (legacy / "reports" / report["filename"]).is_file()
    assert not database_path(destination).exists()