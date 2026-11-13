"""SQLite transfer history: every send and receive, one table."""

from __future__ import annotations

import csv
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    direction    TEXT NOT NULL,
    filename     TEXT NOT NULL,
    size         INTEGER NOT NULL DEFAULT 0,
    sha256       TEXT,
    session      TEXT,
    server       TEXT,
    port         INTEGER,
    mode         TEXT,
    chunks       INTEGER,
    result       TEXT,
    time_seconds REAL,
    size_match   INTEGER,
    sha256_match INTEGER,
    path         TEXT,
    log          TEXT
)
"""

COLUMNS = (
    "timestamp", "direction", "filename", "size", "sha256", "session",
    "server", "port", "mode", "chunks", "result", "time_seconds",
    "size_match", "sha256_match", "path", "log",
)

EXTRA_COLUMNS = {
    "size_match": "INTEGER",
    "sha256_match": "INTEGER",
    "path": "TEXT",
    "log": "TEXT",
}


class History:
    """One SQLite file, one table. Safe to call from the GUI thread."""

    def __init__(self, db_path: str | Path = "history.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, timeout=10
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(transfers)")
        }
        for column, kind in EXTRA_COLUMNS.items():
            if column not in existing:
                self._conn.execute(
                    f"ALTER TABLE transfers ADD COLUMN {column} {kind}"
                )

    # -- writes ------------------------------------------------------------

    def save_transfer(
        self,
        *,
        direction: str,
        filename: str,
        size: int = 0,
        sha256: str | None = None,
        session: str | None = None,
        server: str | None = None,
        port: int | None = None,
        mode: str | None = None,
        chunks: int | None = None,
        result: str | None = None,
        time_seconds: float | None = None,
        size_match: bool | None = None,
        sha256_match: bool | None = None,
        path: str | None = None,
        log: str | None = None,
        timestamp: str | None = None,
    ) -> int:
        row = (
            timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            direction,
            filename,
            int(size or 0),
            sha256,
            session,
            server,
            int(port) if port is not None else None,
            mode,
            int(chunks) if chunks is not None else None,
            result,
            float(time_seconds) if time_seconds is not None else None,
            None if size_match is None else int(bool(size_match)),
            None if sha256_match is None else int(bool(sha256_match)),
            path,
            log,
        )
        placeholders = ", ".join("?" * len(COLUMNS))
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"INSERT INTO transfers ({', '.join(COLUMNS)}) VALUES ({placeholders})",
                row,
            )
            return int(cursor.lastrowid)

    def clear(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM transfers")

    # -- reads -------------------------------------------------------------

    def list_transfers(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM transfers ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_transfer(self, transfer_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM transfers WHERE id = ?", (int(transfer_id),)
            ).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM transfers").fetchone()[0])

    # -- export ------------------------------------------------------------

    def export_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self.list_transfers(limit=10**9)
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("id",) + COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in ("id",) + COLUMNS})
        return target

    def close(self) -> None:
        with self._lock:
            self._conn.close()
