"""PostgreSQL bağlantı havuzu ve şema kurulumu.

SQLite sürümünden farklar:
  * Bağlantı havuzu kullanılır (web sunucusunda birden çok istek eşzamanlı gelir).
  * Yer tutucu `%s`'tir, `?` değil.
  * INSERT sonrası üretilen kimlik için `insert()` kullanılır (`RETURNING id`).
  * Satırlar sözlük gibi davranır; `row["sutun"]` erişimi aynen çalışır.
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
_pool: ConnectionPool | None = None


# --- Havuz yönetimi -------------------------------------------------------
def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=config.database_url(),
            min_size=1,
            max_size=config.DB_POOL_MAX,
            kwargs={"row_factory": dict_row},
            open=True,
            timeout=15,
        )
        atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# Masaüstü sürümden gelen çağrılar için ad uyumluluğu.
close_connection = close_pool


# Açık bir transaction varsa, o blok içindeki tüm sorgular aynı bağlantıyı
# kullanmalıdır. Aksi halde her çağrı havuzdan ayrı bağlantı alır ve
# atomiklik kaybolur.
_ambient: ContextVar[psycopg.Connection | None] = ContextVar("ambient_conn", default=None)


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Havuzdan bir bağlantı ödünç alır; blok bitince otomatik commit/rollback.

    Çevreleyen bir `transaction()` varsa onun bağlantısına katılır.
    """
    existing = _ambient.get()
    if existing is not None:
        yield existing
        return
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Birden fazla yazmayı tek atomik işlemde toplar.

    Örnek: durum değişikliği + geçmiş kaydı ya birlikte yazılır ya hiç.
    İç içe kullanıldığında savepoint'e dönüşür.
    """
    existing = _ambient.get()
    if existing is not None:
        with existing.transaction():
            yield existing
        return

    with get_pool().connection() as conn:
        token = _ambient.set(conn)
        try:
            with conn.transaction():
                yield conn
        finally:
            _ambient.reset(token)


# --- Sorgular -------------------------------------------------------------
def query(sql: str, params: Sequence | dict = ()) -> list[dict]:
    with connection() as conn:
        return conn.execute(sql, params).fetchall()


def query_one(sql: str, params: Sequence | dict = ()) -> dict | None:
    with connection() as conn:
        return conn.execute(sql, params).fetchone()


def scalar(sql: str, params: Sequence | dict = (), default: Any = 0) -> Any:
    """Tek hücrelik sonuç döner; sonuç yoksa veya NULL ise `default`."""
    with connection() as conn:
        row = conn.execute(sql, params).fetchone()
    if not row:
        return default
    value = next(iter(row.values()))
    return default if value is None else value


def execute(sql: str, params: Sequence | dict = ()) -> int:
    """INSERT/UPDATE/DELETE çalıştırır, etkilenen satır sayısını döner."""
    with connection() as conn:
        return conn.execute(sql, params).rowcount


def insert(sql: str, params: Sequence | dict = ()) -> int:
    """INSERT çalıştırır ve üretilen kimliği döner.

    SQL'de `RETURNING` yoksa otomatik olarak `RETURNING id` eklenir.
    """
    if "returning" not in sql.lower():
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
    with connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return row["id"]


def executemany(sql: str, rows: Sequence[Sequence]) -> None:
    with connection() as conn:
        conn.cursor().executemany(sql, rows)


# --- Kurulum --------------------------------------------------------------
def init_db() -> None:
    """Şemayı kurar (idempotent) ve ilk çalıştırmada varsayılan yöneticiyi ekler."""
    with connection() as conn:
        conn.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
    _ensure_default_admin()


def _ensure_default_admin() -> None:
    from app.utils import security

    if scalar("SELECT COUNT(*) FROM users") > 0:
        return

    salt, pwd_hash = security.new_credentials("admin")
    insert(
        """INSERT INTO users (username, password_hash, salt, full_name, role)
           VALUES (%s, %s, %s, %s, %s)""",
        ("admin", pwd_hash, salt, "Sistem Yöneticisi", config.ROLE_MANAGER),
    )
    execute(
        """INSERT INTO app_meta (key, value) VALUES ('default_admin', '1')
           ON CONFLICT (key) DO UPDATE SET value = '1'"""
    )


def default_admin_pending() -> bool:
    """Varsayılan admin şifresi hâlâ değiştirilmediyse True."""
    row = query_one("SELECT value FROM app_meta WHERE key = 'default_admin'")
    return bool(row and row["value"] == "1")


def clear_default_admin_flag() -> None:
    execute("UPDATE app_meta SET value = '0' WHERE key = 'default_admin'")


def drop_all() -> None:
    """Tüm tabloları siler. Yalnızca testlerde ve reset betiğinde kullanılır."""
    with connection() as conn:
        conn.execute(
            """DROP TABLE IF EXISTS notifications, attachments, fault_logs,
                                    faults, machines, users, app_meta CASCADE"""
        )
