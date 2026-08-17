"""SQLite bağlantı yönetimi ve şema kurulumu."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app import config

_local = threading.local()
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """Thread başına tek bağlantı döner (Qt tek thread'de çalıştığı için pratikte bir tane)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.db_path()))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
    return conn


def close_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def query(sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
    return get_connection().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
    return get_connection().execute(sql, params).fetchone()


def execute(sql: str, params: tuple | dict = ()) -> int:
    """INSERT/UPDATE/DELETE çalıştırır, lastrowid döner."""
    conn = get_connection()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def scalar(sql: str, params: tuple | dict = (), default=0):
    row = query_one(sql, params)
    if row is None or row[0] is None:
        return default
    return row[0]


def init_db() -> None:
    """Şemayı kurar (idempotent) ve ilk çalıştırmada varsayılan yöneticiyi ekler."""
    conn = get_connection()
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    _ensure_default_admin()


def _ensure_default_admin() -> None:
    from app.utils import security

    if scalar("SELECT COUNT(*) FROM users") > 0:
        return
    salt, pwd_hash = security.new_credentials("admin")
    execute(
        """INSERT INTO users (username, password_hash, salt, full_name, role)
           VALUES (?, ?, ?, ?, ?)""",
        ("admin", pwd_hash, salt, "Sistem Yöneticisi", config.ROLE_MANAGER),
    )
    execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('default_admin', '1')",
    )


def default_admin_pending() -> bool:
    """Varsayılan admin şifresi hâlâ değiştirilmediyse True."""
    row = query_one("SELECT value FROM app_meta WHERE key = 'default_admin'")
    return bool(row and row["value"] == "1")


def clear_default_admin_flag() -> None:
    execute("UPDATE app_meta SET value = '0' WHERE key = 'default_admin'")
