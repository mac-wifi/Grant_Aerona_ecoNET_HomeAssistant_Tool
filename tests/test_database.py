"""Real SQLite smoke test in pytest's temporary directory."""
import asyncio
import sqlite3
from types import SimpleNamespace

from custom_components.econet_grant.database import EconetDatabase


async def test_settings_persist_across_connections(tmp_path, edit_params):
    path = tmp_path / "test.db"
    hass = SimpleNamespace(async_add_executor_job=asyncio.to_thread)
    db = EconetDatabase(path)
    await db.async_setup(hass)
    await db.async_setup(hass)  # Schema creation is idempotent.
    await db.async_record_settings(hass, edit_params)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone() == (1,)
        assert conn.execute(
            "SELECT param_index, param_name, value FROM settings_history "
            "WHERE param_name = ?", ("Circuit1ComfortTemp",),
        ).fetchall() == [("100", "Circuit1ComfortTemp", "20")]
