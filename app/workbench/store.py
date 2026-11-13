"""SQLite-backed defensive telemetry storage.

Only observation metadata is persisted: timestamps, sources, query names,
measured length/entropy, detector evidence, monitoring sessions and report
metadata. Transferred file contents and passwords never enter this database.

A single connection is shared by the monitor thread and request handlers. Every
operation is serialized with a re-entrant lock, and writes use short SQLite
transactions in WAL mode. All reads are parameterized; no query name, source or
filter is interpolated into SQL.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_FILENAME = "workbench.db"
RULES = ("length", "entropy", "rate")
THEMES = ("dark", "light", "system")
DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark",
    "host": "127.0.0.1",
    "port": 15353,
}


class WorkbenchError(Exception):
    """An expected workbench failure safe to show to the local UI."""


class ValidationError(WorkbenchError, ValueError):
    """User-supplied data failed validation."""


class NotFoundError(WorkbenchError, LookupError):
    """A requested stored object does not exist."""


class StoreClosedError(WorkbenchError):
    """The telemetry store has already been closed."""


def utc_now_ms() -> int:
    """Current UTC time as Unix milliseconds."""
    return int(time.time() * 1000)


def utc_iso(timestamp_ms: int) -> str:
    """Render Unix milliseconds as an ISO-8601 UTC string."""
    moment = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def database_path(data_dir: str | Path) -> Path:
    """The database file inside a workbench data directory."""
    return Path(data_dir) / DB_FILENAME


@dataclass(frozen=True)
class ObservationFilter:
    """One selected time range and its optional observation filters."""

    start_ms: int
    end_ms: int
    query: str = ""
    source: str = ""
    rule: str = ""
    flagged: bool | None = None
    offset: int = 0
    limit: int = 50


def _where(filters: ObservationFilter) -> tuple[str, list[Any]]:
    clauses = ["o.observed_ms >= ?", "o.observed_ms <= ?"]
    params: list[Any] = [filters.start_ms, filters.end_ms]
    if filters.query:
        clauses.append("instr(lower(o.qname), lower(?)) > 0")
        params.append(filters.query)
    if filters.source:
        clauses.append("o.source = ?")
        params.append(filters.source)
    if filters.rule:
        clauses.append(
            "EXISTS (SELECT 1 FROM alerts f "
            "WHERE f.observation_id = o.id AND f.rule = ?)"
        )
        params.append(filters.rule)
    if filters.flagged is True:
        clauses.append("o.alert_count > 0")
    elif filters.flagged is False:
        clauses.append("o.alert_count = 0")
    return " WHERE " + " AND ".join(clauses), params


class Store:
    """Thread-safe telemetry store shared by the monitor and the bridge."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = sqlite3.connect(
            str(self.path), timeout=5.0, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._migrate_settings()
            self._create_schema()
        except Exception:
            self._conn.close()
            self._conn = None
            raise

    # -- lifecycle ---------------------------------------------------------

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StoreClosedError("telemetry store is closed")
        return self._conn

    def _migrate_settings(self) -> None:
        """Expand the legacy theme constraint without losing saved settings."""
        conn = self._connection()
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'settings'"
        ).fetchone()
        if row is None or "'system'" in row["sql"]:
            return
        with conn:
            conn.execute(
                "CREATE TABLE settings_new ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), "
                "theme TEXT NOT NULL CHECK (theme IN ('dark', 'light', 'system')), "
                "host TEXT NOT NULL, "
                "port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535))"
            )
            conn.execute(
                "INSERT INTO settings_new (id, theme, host, port) "
                "SELECT id, theme, host, port FROM settings"
            )
            conn.execute("DROP TABLE settings")
            conn.execute("ALTER TABLE settings_new RENAME TO settings")

    def _create_schema(self) -> None:
        conn = self._connection()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                theme TEXT NOT NULL CHECK (theme IN ('dark', 'light', 'system')),
                host TEXT NOT NULL,
                port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                started_ms INTEGER NOT NULL,
                stopped_at TEXT,
                stopped_ms INTEGER,
                host TEXT NOT NULL,
                port INTEGER NOT NULL CHECK (port BETWEEN 0 AND 65535),
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                observed_ms INTEGER NOT NULL,
                qname TEXT NOT NULL,
                source TEXT NOT NULL,
                entropy REAL NOT NULL,
                length INTEGER NOT NULL CHECK (length >= 0),
                warning INTEGER NOT NULL DEFAULT 0 CHECK (warning IN (0, 1)),
                alert_count INTEGER NOT NULL DEFAULT 0 CHECK (alert_count >= 0),
                session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER NOT NULL
                    REFERENCES observations(id) ON DELETE CASCADE,
                rule TEXT NOT NULL CHECK (rule IN ('length', 'entropy', 'rate')),
                reason TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                created_ms INTEGER NOT NULL,
                title TEXT NOT NULL,
                format TEXT NOT NULL CHECK (format IN ('txt', 'pdf')),
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                total_queries INTEGER NOT NULL,
                anomalies INTEGER NOT NULL,
                hours INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_observations_time
                ON observations(observed_ms);
            CREATE INDEX IF NOT EXISTS idx_observations_source_time
                ON observations(source, observed_ms);
            CREATE INDEX IF NOT EXISTS idx_observations_alert_time
                ON observations(alert_count, observed_ms);
            CREATE INDEX IF NOT EXISTS idx_observations_session
                ON observations(session_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_observation
                ON alerts(observation_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_rule
                ON alerts(rule);
            CREATE INDEX IF NOT EXISTS idx_sessions_started
                ON sessions(started_ms);
            CREATE INDEX IF NOT EXISTS idx_reports_created
                ON reports(created_ms);
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (id, theme, host, port) "
            "VALUES (1, ?, ?, ?)",
            (
                DEFAULT_SETTINGS["theme"],
                DEFAULT_SETTINGS["host"],
                DEFAULT_SETTINGS["port"],
            ),
        )
        conn.commit()

    def close(self) -> None:
        """Close the shared connection. Safe to call more than once."""
        with self._lock:
            conn = self._conn
            self._conn = None
            if conn is not None:
                conn.close()

    # -- settings ----------------------------------------------------------

    def load_settings(self) -> dict[str, Any]:
        with self._lock:
            row = self._connection().execute(
                "SELECT theme, host, port FROM settings WHERE id = 1"
            ).fetchone()
            if row is None:
                return dict(DEFAULT_SETTINGS)
            return {
                "theme": str(row["theme"]),
                "host": str(row["host"]),
                "port": int(row["port"]),
            }

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Atomically replace the persisted settings row."""
        with self._lock:
            conn = self._connection()
            with conn:
                conn.execute(
                    "UPDATE settings SET theme = ?, host = ?, port = ? WHERE id = 1",
                    (settings["theme"], settings["host"], int(settings["port"])),
                )
            return self.load_settings()

    # -- monitoring sessions ----------------------------------------------

    def start_session(
        self, host: str, port: int, now_ms: int | None = None
    ) -> int:
        moment = utc_now_ms() if now_ms is None else int(now_ms)
        with self._lock:
            conn = self._connection()
            with conn:
                cursor = conn.execute(
                    "INSERT INTO sessions "
                    "(started_at, started_ms, host, port) VALUES (?, ?, ?, ?)",
                    (utc_iso(moment), moment, host, int(port)),
                )
            return int(cursor.lastrowid)

    def stop_session(self, session_id: int, now_ms: int | None = None) -> None:
        moment = utc_now_ms() if now_ms is None else int(now_ms)
        with self._lock:
            conn = self._connection()
            with conn:
                conn.execute(
                    "UPDATE sessions SET stopped_at = ?, stopped_ms = ? "
                    "WHERE id = ? AND stopped_ms IS NULL",
                    (utc_iso(moment), moment, int(session_id)),
                )

    def sessions(
        self, start_ms: int, end_ms: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Sessions intersecting the selected range, newest first."""
        with self._lock:
            rows = self._connection().execute(
                """
                SELECT id, started_at, stopped_at, host, port
                FROM sessions
                WHERE started_ms <= ?
                  AND (stopped_ms IS NULL OR stopped_ms >= ?)
                ORDER BY started_ms DESC, id DESC
                LIMIT ?
                """,
                (int(end_ms), int(start_ms), int(limit)),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "started_at": str(row["started_at"]),
                "stopped_at": (
                    str(row["stopped_at"])
                    if row["stopped_at"] is not None
                    else None
                ),
                "host": str(row["host"]),
                "port": int(row["port"]),
            }
            for row in rows
        ]

    # -- observations ------------------------------------------------------

    def add_observation(
        self,
        *,
        observed_ms: int,
        qname: str,
        source: str,
        entropy: float,
        length: int,
        alerts: list[dict[str, Any]],
        warning: bool,
        session_id: int | None,
    ) -> int:
        """Persist one observation and its emitted detector evidence."""
        moment = int(observed_ms)
        clean_alerts = [
            {"rule": str(alert["rule"]), "reason": str(alert["reason"])}
            for alert in alerts
        ]
        with self._lock:
            conn = self._connection()
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO observations
                        (timestamp, observed_ms, qname, source, entropy,
                         length, warning, alert_count, session_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            utc_iso(moment),
                            moment,
                            qname,
                            source,
                            float(entropy),
                            int(length),
                            1 if warning else 0,
                            len(clean_alerts),
                            session_id,
                        ),
                    )
                    observation_id = int(cursor.lastrowid)
                    if clean_alerts:
                        conn.executemany(
                            "INSERT INTO alerts (observation_id, rule, reason) "
                            "VALUES (?, ?, ?)",
                            [
                                (observation_id, alert["rule"], alert["reason"])
                                for alert in clean_alerts
                            ],
                        )
            except Exception:
                raise
            return observation_id

    def counts(self, filters: ObservationFilter) -> tuple[int, int]:
        """Total observations and alert-bearing observations in the filter."""
        where, params = _where(filters)
        with self._lock:
            row = self._connection().execute(
                f"""
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN o.alert_count > 0 THEN 1 ELSE 0 END), 0)
                           AS anomalies
                FROM observations o
                {where}
                """,
                params,
            ).fetchone()
        return int(row["total"]), int(row["anomalies"])

    def source_counts(self, filters: ObservationFilter) -> list[dict[str, Any]]:
        where, params = _where(filters)
        with self._lock:
            rows = self._connection().execute(
                f"""
                SELECT o.source AS source, COUNT(*) AS count
                FROM observations o
                {where}
                GROUP BY o.source
                ORDER BY count DESC, o.source ASC
                """,
                params,
            ).fetchall()
        return [
            {"source": str(row["source"]), "count": int(row["count"])}
            for row in rows
        ]

    def rule_counts(self, filters: ObservationFilter) -> list[dict[str, Any]]:
        """Emitted evidence rows per rule for the filtered observations."""
        where, params = _where(filters)
        if filters.rule:
            where += " AND a.rule = ?"
            params.append(filters.rule)
        with self._lock:
            rows = self._connection().execute(
                f"""
                SELECT a.rule AS rule, COUNT(*) AS count
                FROM alerts a
                JOIN observations o ON o.id = a.observation_id
                {where}
                GROUP BY a.rule
                """,
                params,
            ).fetchall()
        return [
            {"rule": str(row["rule"]), "count": int(row["count"])}
            for row in rows
        ]

    def series(
        self,
        filters: ObservationFilter,
        width_ms: int,
        bucket_count: int,
    ) -> list[dict[str, Any]]:
        """Counts in real buckets, including empty buckets, for the filter."""
        width = max(1, int(width_ms))
        count = max(1, int(bucket_count))
        where, params = _where(filters)
        with self._lock:
            rows = self._connection().execute(
                f"""
                SELECT MIN(?, MAX(0, CAST((o.observed_ms - ?) / ? AS INTEGER)))
                           AS bucket,
                       COUNT(*) AS count
                FROM observations o
                {where}
                GROUP BY bucket
                """,
                [count - 1, int(filters.start_ms), width, *params],
            ).fetchall()
        buckets = {int(row["bucket"]): int(row["count"]) for row in rows}
        return [
            {
                "time": utc_iso(int(filters.start_ms) + index * width),
                "count": buckets.get(index, 0),
            }
            for index in range(count)
        ]

    def _fetch_observations(
        self,
        filters: ObservationFilter,
        *,
        limit: int | None,
        offset: int,
    ) -> list[dict[str, Any]]:
        where, params = _where(filters)
        sql = f"""
            SELECT o.id, o.timestamp, o.qname, o.source, o.entropy,
                   o.length, o.warning, o.session_id
            FROM observations o
            {where}
            ORDER BY o.observed_ms DESC, o.id DESC
        """
        query_params = list(params)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            query_params.extend([int(limit), int(offset)])
        with self._lock:
            conn = self._connection()
            rows = conn.execute(sql, query_params).fetchall()
            if not rows:
                return []
            ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in ids)
            alert_rows = conn.execute(
                f"SELECT observation_id, rule, reason FROM alerts "
                f"WHERE observation_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        evidence: dict[int, list[dict[str, str]]] = {identifier: [] for identifier in ids}
        for alert in alert_rows:
            evidence[int(alert["observation_id"])].append(
                {"rule": str(alert["rule"]), "reason": str(alert["reason"])}
            )
        return [
            {
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "qname": str(row["qname"]),
                "source": str(row["source"]),
                "entropy": float(row["entropy"]),
                "length": int(row["length"]),
                "alerts": evidence[int(row["id"])],
                "warning": bool(row["warning"]),
                "session_id": (
                    int(row["session_id"])
                    if row["session_id"] is not None
                    else None
                ),
            }
            for row in rows
        ]

    def observations(self, filters: ObservationFilter) -> list[dict[str, Any]]:
        """One page of observations for the filter."""
        return self._fetch_observations(
            filters, limit=filters.limit, offset=filters.offset
        )

    def all_observations(self, filters: ObservationFilter) -> list[dict[str, Any]]:
        """Every observation for a report, deliberately unpaginated."""
        return self._fetch_observations(filters, limit=None, offset=0)

    # -- reports -----------------------------------------------------------

    def add_report(
        self,
        *,
        created_ms: int,
        title: str,
        report_format: str,
        filename: str,
        path: str,
        total_queries: int,
        anomalies: int,
        hours: int,
    ) -> int:
        with self._lock:
            conn = self._connection()
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO reports
                    (created_at, created_ms, title, format, filename, path,
                     total_queries, anomalies, hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_iso(int(created_ms)),
                        int(created_ms),
                        title,
                        report_format,
                        filename,
                        path,
                        int(total_queries),
                        int(anomalies),
                        int(hours),
                    ),
                )
            return int(cursor.lastrowid)

    def list_reports(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection().execute(
                """
                SELECT id, created_at, title, format, filename,
                       total_queries, anomalies
                FROM reports
                ORDER BY created_ms DESC, id DESC
                """
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "created_at": str(row["created_at"]),
                "title": str(row["title"]),
                "format": str(row["format"]),
                "filename": str(row["filename"]),
                "total_queries": int(row["total_queries"]),
                "anomalies": int(row["anomalies"]),
            }
            for row in rows
        ]

    def get_report(self, report_id: int) -> dict[str, Any]:
        with self._lock:
            row = self._connection().execute(
                """
                SELECT id, created_at, created_ms, title, format, filename,
                       path, total_queries, anomalies, hours
                FROM reports WHERE id = ?
                """,
                (int(report_id),),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"report {report_id} does not exist")
        return {
            "id": int(row["id"]),
            "created_at": str(row["created_at"]),
            "created_ms": int(row["created_ms"]),
            "title": str(row["title"]),
            "format": str(row["format"]),
            "filename": str(row["filename"]),
            "path": str(row["path"]),
            "total_queries": int(row["total_queries"]),
            "anomalies": int(row["anomalies"]),
            "hours": int(row["hours"]),
        }