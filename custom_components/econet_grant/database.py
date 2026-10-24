"""SQLite database for indefinite storage of all EcoNet readings and settings.

Stores time-series data from all three API endpoints (regParams, editParams,
sysParams) and maintains an audit log of detected parameter changes.
The database file lives in the HA config directory as econet_grant.db.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_CREATE_TABLES = """\
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    parameter TEXT NOT NULL,
    value REAL,
    unit TEXT
);

CREATE INDEX IF NOT EXISTS idx_readings_param_ts
    ON readings (parameter, timestamp);

CREATE TABLE IF NOT EXISTS settings_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    param_index TEXT NOT NULL,
    param_name TEXT NOT NULL,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_settings_param_ts
    ON settings_history (param_name, timestamp);

CREATE TABLE IF NOT EXISTS sys_params_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    param_name TEXT NOT NULL,
    param_index TEXT,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL DEFAULT 'external'
);

CREATE INDEX IF NOT EXISTS idx_change_log_ts
    ON change_log (timestamp);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


class EconetDatabase:
    """Manages the SQLite database for EcoNet readings and settings history."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection, committed on success and always closed."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _insert(self, what: str, sql: str, rows: list[tuple]) -> None:
        """Insert rows; database/file errors are logged, never raised to HA."""
        if not rows:
            return
        try:
            with self._connection() as conn:
                conn.executemany(sql, rows)
            _LOGGER.debug("Recorded %d %s", len(rows), what)
        except sqlite3.Error:
            _LOGGER.error("Failed to record %s", what, exc_info=True)
        except OSError:
            _LOGGER.error("Filesystem error recording %s", what, exc_info=True)

    def _setup_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(_CREATE_TABLES)
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )

    async def async_setup(self, hass: HomeAssistant) -> None:
        """Create tables and indexes if they don't already exist."""
        await hass.async_add_executor_job(self._setup_schema)
        _LOGGER.info("EcoNet database initialised at %s", self._db_path)

    # ------------------------------------------------------------------
    # Fast coordinator data (regParams) – every 5 minutes
    # ------------------------------------------------------------------

    def _record_readings(self, data: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows: list[tuple] = []

        curr_units = data.get("currUnits", {})
        for param, value in data.get("curr", {}).items():
            if value is None:
                continue
            try:
                rows.append((now, param, float(value), curr_units.get(param)))
            except (TypeError, ValueError):
                continue

        for idx, tile in enumerate(data.get("tilesParams", [])):
            try:
                rows.append((now, f"tile_{idx}", float(tile[0][0][0]), None))
            except (IndexError, TypeError, ValueError):
                continue

        for key, val in data.get("schemaParams", {}).items():
            try:
                rows.append((now, f"schema_{key}", float(val[0][0][0]), None))
            except (IndexError, TypeError, ValueError, KeyError):
                continue

        self._insert(
            "readings",
            "INSERT INTO readings (timestamp, parameter, value, unit) VALUES (?, ?, ?, ?)",
            rows,
        )

    async def async_record_readings(
        self, hass: HomeAssistant, data: dict[str, Any]
    ) -> None:
        """Record regParams data (temperatures, performance) to the database."""
        await hass.async_add_executor_job(self._record_readings, data)

    # ------------------------------------------------------------------
    # Slow coordinator data (editParams)
    # ------------------------------------------------------------------

    def _record_settings(self, edit_params: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (now, str(index), param["name"], str(param.get("value", "")))
            for index, param in edit_params.get("data", {}).items()
            if isinstance(param, dict) and "name" in param
        ]
        self._insert(
            "settings",
            "INSERT INTO settings_history "
            "(timestamp, param_index, param_name, value) VALUES (?, ?, ?, ?)",
            rows,
        )

    async def async_record_settings(
        self, hass: HomeAssistant, edit_params: dict[str, Any]
    ) -> None:
        """Record editParams data (all editable settings) to the database."""
        await hass.async_add_executor_job(self._record_settings, edit_params)

    # ------------------------------------------------------------------
    # Slow coordinator data (sysParams)
    # ------------------------------------------------------------------

    def _record_sys_params(self, sys_params: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._insert(
            "sysParams",
            "INSERT INTO sys_params_history (timestamp, data) VALUES (?, ?)",
            [(now, json.dumps(sys_params))],
        )

    async def async_record_sys_params(
        self, hass: HomeAssistant, sys_params: dict[str, Any]
    ) -> None:
        """Record sysParams data (system info) to the database."""
        await hass.async_add_executor_job(self._record_sys_params, sys_params)

    # ------------------------------------------------------------------
    # Change audit log
    # ------------------------------------------------------------------

    def _log_change(self, change: dict[str, Any], source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._insert(
            f"change for {change.get('name')}",
            "INSERT INTO change_log "
            "(timestamp, param_name, param_index, old_value, new_value, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(
                now,
                change.get("name", ""),
                change.get("index"),
                str(change.get("old_value", "")),
                str(change.get("new_value", "")),
                source,
            )],
        )

    async def async_log_change(
        self,
        hass: HomeAssistant,
        change: dict[str, Any],
        source: str = "external",
    ) -> None:
        """Record a detected parameter change to the audit log."""
        await hass.async_add_executor_job(self._log_change, change, source)

    # ------------------------------------------------------------------
    # Data retention
    # ------------------------------------------------------------------

    def _purge_old_data(self, days: int) -> None:
        """Delete readings and history older than the given number of days.

        The change_log audit trail is kept indefinitely.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connection() as conn:
            deleted = {
                table: conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,)
                ).rowcount
                for table in ("readings", "settings_history", "sys_params_history")
            }
        total = sum(deleted.values())
        if total > 0:
            _LOGGER.info(
                "Purged %d old records (readings=%d, settings=%d, sysParams=%d, cutoff=%s)",
                total, deleted["readings"], deleted["settings_history"],
                deleted["sys_params_history"], cutoff,
            )

    async def async_purge_old_data(self, hass: HomeAssistant, days: int = 3650) -> None:
        """Purge records older than the configured retention period."""
        try:
            await hass.async_add_executor_job(self._purge_old_data, days)
        except sqlite3.Error:
            _LOGGER.error("Failed to purge old data", exc_info=True)
        except OSError:
            _LOGGER.error("Filesystem error during data purge", exc_info=True)

    # ------------------------------------------------------------------
    # Database file size (for diagnostic sensor)
    # ------------------------------------------------------------------

    def get_db_size_mb(self) -> float:
        """Return the database file size in megabytes."""
        try:
            return self._db_path.stat().st_size / (1024 * 1024)
        except OSError:
            return 0.0

    def get_recent_change_count(self) -> int:
        """Return the number of change_log entries in the last 24 hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM change_log WHERE timestamp > ?", (cutoff,)
                ).fetchone()
        except (sqlite3.Error, OSError):
            return 0
        return row[0] if row else 0
