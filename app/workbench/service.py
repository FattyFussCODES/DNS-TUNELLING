"""Allowlisted workbench service API used by the local desktop bridge.

The service is deliberately narrow: no shell execution or arbitrary filesystem
access is exposed, only defensive observation data, settings and reports.
Every action returns either ``{"ok": True, "data": ...}`` or
``{"ok": False, "error": "..."}``.
"""

from __future__ import annotations

import filecmp
import ipaddress
import os
import shutil
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from .. import __version__
from .monitor import COOLDOWN_NOTE, COVERAGE_NOTE, RULE_INFO, Monitor
from .reports import (
    REPORT_DIR_NAME,
    ReportUnavailable,
    create_report,
    report_content,
    reportlab_available,
)
from .store import (
    ObservationFilter,
    Store,
    StoreClosedError,
    THEMES,
    ValidationError,
    WorkbenchError,
    database_path,
    utc_now_ms,
)

VALID_HOURS = (1, 24, 168)
VALID_RULES = ("length", "entropy", "rate")
_BUCKET_MS = {1: 300_000, 24: 3_600_000, 168: 21_600_000}
_MAX_LIMIT = 200


def default_data_dir() -> Path:
    """Platform-specific per-user directory, separate from transfer settings."""
    return user_data_path("DNSMuggle", appauthor=False) / "workbench"


def _migrate_legacy_data(destination: Path) -> None:
    """Copy legacy data without replacing existing data or removing the source."""
    source = (Path.home() / "DNSMuggle" / "workbench").resolve()
    destination = destination.resolve()
    source_db = database_path(source)
    target_db = database_path(destination)
    if source == destination or target_db.exists() or not source_db.is_file():
        return

    destination.mkdir(parents=True, exist_ok=True)
    source_reports = source / REPORT_DIR_NAME
    target_reports = destination / REPORT_DIR_NAME
    target_reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".migration-", dir=destination) as temp:
        staging = Path(temp)
        staged_db = staging / source_db.name
        staged_reports = staging / "reports"
        staged_reports.mkdir()
        with closing(sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True)) as old:
            with closing(sqlite3.connect(staged_db)) as new, new:
                old.backup(new)
                rows = new.execute("SELECT id, path FROM reports").fetchall()
                for report_id, raw_path in rows:
                    path = Path(raw_path).resolve()
                    if path.parent == source_reports.resolve():
                        new.execute(
                            "UPDATE reports SET path = ? WHERE id = ?",
                            (str(target_reports / path.name), report_id),
                        )
        if source_reports.is_dir():
            for path in source_reports.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                target = target_reports / path.name
                if target.exists():
                    if not target.is_file() or not filecmp.cmp(path, target, shallow=False):
                        raise FileExistsError(f"report migration conflict: {target}")
                    continue
                staged_report = staged_reports / path.name
                shutil.copy2(path, staged_report)
                try:
                    os.link(staged_report, target)
                except FileExistsError:
                    if not target.is_file() or not filecmp.cmp(path, target, shallow=False):
                        raise FileExistsError(f"report migration conflict: {target}")
        try:
            os.link(staged_db, target_db)
        except FileExistsError:
            # Another instance already initialized the destination.
            pass


def _int_field(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer")
    if value < minimum:
        raise ValidationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{name} must be at most {maximum}")
    return value


class WorkbenchService:
    """Owns telemetry storage and the single observation listener."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (
            Path(data_dir).expanduser().resolve()
            if data_dir is not None
            else default_data_dir().expanduser().resolve()
        )
        if data_dir is None:
            _migrate_legacy_data(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / REPORT_DIR_NAME).mkdir(parents=True, exist_ok=True)
        self._store = Store(database_path(self.data_dir))
        self._monitor = Monitor(self._store)
        self._lock = threading.RLock()
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Stop owned workers and close storage. Safe to call twice."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._monitor.stop()
            finally:
                self._store.close()

    def request(
        self, action: str, payload: dict | None = None
    ) -> dict[str, Any]:
        """Dispatch one allowlisted action and return a structured result."""
        try:
            with self._lock:
                if self._closed:
                    raise StoreClosedError("workbench service is closed")
                if not isinstance(action, str) or not action:
                    raise ValidationError("action must be a non-empty string")
                if payload is None:
                    data: dict[str, Any] = {}
                elif isinstance(payload, dict):
                    data = payload
                else:
                    raise ValidationError("payload must be an object")
                result = self._dispatch(action, data)
            return {"ok": True, "data": result}
        except ReportUnavailable as exc:
            return {"ok": False, "error": str(exc)}
        except (WorkbenchError, ValueError, OSError, sqlite3.Error) as exc:
            message = str(exc) or exc.__class__.__name__
            return {"ok": False, "error": message}
        except Exception as exc:  # Never let a request take down the bridge.
            return {
                "ok": False,
                "error": f"unexpected error: {exc.__class__.__name__}: {exc}",
            }

    def _dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        if action == "bootstrap":
            return self._bootstrap()
        if action == "snapshot":
            return self._snapshot(payload)
        if action == "save_settings":
            return self._save_settings(payload)
        if action == "start_monitor":
            return self._start_monitor()
        if action == "stop_monitor":
            return self._stop_monitor()
        if action == "reports":
            return self._store.list_reports()
        if action == "generate_report":
            return self._generate_report(payload)
        if action == "export_report":
            report_id = _int_field(payload.get("id"), "id", minimum=1)
            info = report_content(self._store, self.data_dir, report_id)
            return {
                "id": report_id,
                "filename": info["filename"],
                "format": info["format"],
            }
        if action == "report_content":
            return self._report_content(payload)
        raise ValidationError(f"unknown action: {action}")

    # -- actions -----------------------------------------------------------

    def _bootstrap(self) -> dict[str, Any]:
        settings = self._store.load_settings()
        return {
            "version": __version__,
            "settings": settings,
            "data_dir": str(self.data_dir),
            "coverage": f"{COVERAGE_NOTE} {COOLDOWN_NOTE}",
            "rules": [dict(rule) for rule in RULE_INFO],
            "monitor": self._monitor.state(settings["host"], settings["port"]),
            "pdf_available": reportlab_available(),
        }

    def _save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self._store.load_settings()
        theme = payload.get("theme", current["theme"])
        if theme not in THEMES:
            raise ValidationError("theme must be 'dark', 'light' or 'system'")

        raw_host = payload.get("host", current["host"])
        if not isinstance(raw_host, str) or not raw_host.strip():
            raise ValidationError("host must be a numeric IPv4 or IPv6 address")
        try:
            host = str(ipaddress.ip_address(raw_host.strip()))
        except ValueError as exc:
            raise ValidationError(
                "host must be a numeric IPv4 or IPv6 address"
            ) from exc

        port = _int_field(
            payload.get("port", current["port"]),
            "port",
            minimum=1,
            maximum=65535,
        )

        state = self._monitor.state(current["host"], current["port"])
        if state["running"] and (
            host != state["host"] or int(port) != int(state["port"])
        ):
            raise ValidationError(
                "stop monitoring before changing the observation endpoint"
            )
        return self._store.save_settings(
            {"theme": theme, "host": host, "port": port}
        )

    def _start_monitor(self) -> dict[str, Any]:
        settings = self._store.load_settings()
        self._monitor.start(settings["host"], settings["port"])
        return self._monitor.state(settings["host"], settings["port"])

    def _stop_monitor(self) -> dict[str, Any]:
        self._monitor.stop()
        settings = self._store.load_settings()
        return self._monitor.state(settings["host"], settings["port"])

    def _snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        hours = self._hours(payload)
        endpoint_ms = utc_now_ms()
        start_ms = endpoint_ms - hours * 3_600_000

        query = payload.get("query", "")
        if query is None:
            query = ""
        if not isinstance(query, str):
            raise ValidationError("query filter must be a string")
        query = query.strip()
        if len(query) > 512:
            raise ValidationError("query filter is too long")

        source = payload.get("source", "")
        if source is None:
            source = ""
        if not isinstance(source, str):
            raise ValidationError("source filter must be a string")
        source = source.strip()
        if len(source) > 128:
            raise ValidationError("source filter is too long")

        rule = payload.get("rule", "")
        if rule is None:
            rule = ""
        if rule not in ("",) + VALID_RULES:
            raise ValidationError("rule filter must be length, entropy or rate")

        flagged = payload.get("flagged")
        if flagged is not None and not isinstance(flagged, bool):
            raise ValidationError("flagged filter must be true, false or null")

        offset = _int_field(
            payload.get("offset", 0), "offset", minimum=0
        )
        limit = _int_field(
            payload.get("limit", 50),
            "limit",
            minimum=1,
            maximum=_MAX_LIMIT,
        )
        filters = ObservationFilter(
            start_ms=start_ms,
            end_ms=endpoint_ms,
            query=query,
            source=source,
            rule=rule,
            flagged=flagged,
            offset=offset,
            limit=limit,
        )

        total, anomalies = self._store.counts(filters)
        rate = None if total == 0 else anomalies / total
        width = _BUCKET_MS[hours]
        bucket_count = hours * 3_600_000 // width

        emitted = {rule_id: 0 for rule_id in VALID_RULES}
        for row in self._store.rule_counts(filters):
            emitted[str(row["rule"])] = int(row["count"])
        settings = self._store.load_settings()

        return {
            "total_queries": total,
            "anomalies": anomalies,
            "detection_rate": rate,
            "series": self._store.series(filters, width, bucket_count),
            "observations": self._store.observations(filters),
            "matched": total,
            "offset": offset,
            "limit": limit,
            "sources": self._store.source_counts(filters),
            "rule_counts": [
                {"rule": rule_id, "count": emitted[rule_id]}
                for rule_id in VALID_RULES
            ],
            "sessions": self._store.sessions(start_ms, endpoint_ms),
            "monitor": self._monitor.state(settings["host"], settings["port"]),
        }

    def _hours(self, payload: dict[str, Any]) -> int:
        raw = payload.get("hours")
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValidationError("hours must be 1, 24 or 168")
        if raw not in VALID_HOURS:
            raise ValidationError("hours must be 1, 24 or 168")
        return raw

    def _generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        hours = self._hours(payload)
        report_format = payload.get("format")
        if report_format not in ("txt", "pdf"):
            raise ValidationError("format must be 'txt' or 'pdf'")
        return create_report(
            self._store, self.data_dir, hours, str(report_format)
        )

    def _report_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        report_id = _int_field(payload.get("id"), "id", minimum=1)
        return report_content(self._store, self.data_dir, report_id)