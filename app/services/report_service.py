"""Dashboard ve rapor sorguları."""
from __future__ import annotations

from datetime import date, timedelta

from app import config
from app.db import database as db

_ACTIVE_IN = ", ".join("?" for _ in config.ACTIVE_STATUSES)


def _date_filter(date_from: str | None, date_to: str | None, col: str = "created_at"):
    sql, params = "", []
    if date_from:
        sql += f" AND date(f.{col}) >= date(?)"
        params.append(date_from)
    if date_to:
        sql += f" AND date(f.{col}) <= date(?)"
        params.append(date_to)
    return sql, params


# --- Dashboard özeti ------------------------------------------------------
def summary() -> dict:
    today = date.today().isoformat()
    return {
        "open_total": db.scalar(
            f"SELECT COUNT(*) FROM faults f WHERE f.status IN ({_ACTIVE_IN})",
            tuple(config.ACTIVE_STATUSES),
        ),
        "urgent_open": db.scalar(
            f"""SELECT COUNT(*) FROM faults f
                 WHERE f.status IN ({_ACTIVE_IN}) AND f.priority = ?""",
            (*config.ACTIVE_STATUSES, config.PRIORITY_URGENT),
        ),
        "opened_today": db.scalar(
            "SELECT COUNT(*) FROM faults f WHERE date(f.created_at) = date(?)", (today,)
        ),
        "closed_today": db.scalar(
            """SELECT COUNT(*) FROM faults f
                WHERE date(COALESCE(f.closed_at, f.resolved_at)) = date(?)""",
            (today,),
        ),
        "unassigned": db.scalar(
            f"""SELECT COUNT(*) FROM faults f
                 WHERE f.status IN ({_ACTIVE_IN}) AND f.assignee_id IS NULL""",
            tuple(config.ACTIVE_STATUSES),
        ),
        "avg_resolution_hours": avg_resolution_hours(),
        "machine_count": db.scalar("SELECT COUNT(*) FROM machines WHERE is_active = 1"),
    }


def status_distribution(date_from: str | None = None, date_to: str | None = None) -> dict[str, int]:
    extra, params = _date_filter(date_from, date_to)
    rows = db.query(
        f"SELECT f.status, COUNT(*) AS n FROM faults f WHERE 1=1 {extra} GROUP BY f.status",
        tuple(params),
    )
    counts = {s: 0 for s in config.STATUSES}
    for r in rows:
        counts[r["status"]] = r["n"]
    return counts


def priority_distribution(
    date_from: str | None = None,
    date_to: str | None = None,
    only_active: bool = True,
) -> dict[str, int]:
    extra, params = _date_filter(date_from, date_to)
    sql = f"SELECT f.priority, COUNT(*) AS n FROM faults f WHERE 1=1 {extra}"
    if only_active:
        sql += f" AND f.status IN ({_ACTIVE_IN})"
        params += list(config.ACTIVE_STATUSES)
    sql += " GROUP BY f.priority"

    counts = {p: 0 for p in config.PRIORITIES}
    for r in db.query(sql, tuple(params)):
        counts[r["priority"]] = r["n"]
    return counts


# --- Makine bazlı raporlar ------------------------------------------------
def top_machines(
    limit: int = 10, date_from: str | None = None, date_to: str | None = None
) -> list[dict]:
    """En çok arıza kaydı açılan makineler."""
    extra, params = _date_filter(date_from, date_to)
    rows = db.query(
        f"""
        SELECT m.id, m.name, m.serial_no, m.location, m.category,
               COUNT(f.id) AS fault_count,
               SUM(CASE WHEN f.status IN ({_ACTIVE_IN}) THEN 1 ELSE 0 END) AS open_count,
               AVG(CASE WHEN f.resolved_at IS NOT NULL
                        THEN (julianday(f.resolved_at) - julianday(f.created_at)) * 24.0
                   END) AS avg_hours
          FROM machines m
          JOIN faults f ON f.machine_id = m.id
         WHERE 1=1 {extra}
         GROUP BY m.id
         ORDER BY fault_count DESC, m.name COLLATE NOCASE
         LIMIT ?
        """,
        (*config.ACTIVE_STATUSES, *params, limit),
    )
    return [dict(r) for r in rows]


def avg_resolution_hours(
    machine_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> float | None:
    """Genel veya makine bazında ortalama çözüm süresi (saat)."""
    extra, params = _date_filter(date_from, date_to)
    sql = f"""SELECT AVG((julianday(f.resolved_at) - julianday(f.created_at)) * 24.0)
                FROM faults f
               WHERE f.resolved_at IS NOT NULL {extra}"""
    if machine_id:
        sql += " AND f.machine_id = ?"
        params.append(machine_id)
    return db.scalar(sql, tuple(params), default=None)


def resolution_by_machine(
    date_from: str | None = None, date_to: str | None = None
) -> list[dict]:
    """Makine bazında ortalama çözüm süresi tablosu."""
    extra, params = _date_filter(date_from, date_to)
    rows = db.query(
        f"""
        SELECT m.id, m.name, m.serial_no, m.location,
               COUNT(f.id) AS total,
               SUM(CASE WHEN f.resolved_at IS NOT NULL THEN 1 ELSE 0 END) AS resolved,
               AVG(CASE WHEN f.resolved_at IS NOT NULL
                        THEN (julianday(f.resolved_at) - julianday(f.created_at)) * 24.0
                   END) AS avg_hours,
               MIN(CASE WHEN f.resolved_at IS NOT NULL
                        THEN (julianday(f.resolved_at) - julianday(f.created_at)) * 24.0
                   END) AS min_hours,
               MAX(CASE WHEN f.resolved_at IS NOT NULL
                        THEN (julianday(f.resolved_at) - julianday(f.created_at)) * 24.0
                   END) AS max_hours
          FROM machines m
          JOIN faults f ON f.machine_id = m.id
         WHERE 1=1 {extra}
         GROUP BY m.id
         ORDER BY avg_hours DESC NULLS LAST, m.name COLLATE NOCASE
        """,
        tuple(params),
    )
    return [dict(r) for r in rows]


# --- Trend ----------------------------------------------------------------
def trend(date_from: str, date_to: str, group: str = "gun") -> list[dict]:
    """Tarih aralığında açılan/kapanan arıza sayıları.

    group: 'gun' | 'hafta' | 'ay'
    """
    fmt = {"gun": "%Y-%m-%d", "hafta": "%Y-W%W", "ay": "%Y-%m"}.get(group, "%Y-%m-%d")

    opened = {
        r["bucket"]: r["n"]
        for r in db.query(
            """SELECT strftime(?, f.created_at) AS bucket, COUNT(*) AS n
                 FROM faults f
                WHERE date(f.created_at) BETWEEN date(?) AND date(?)
                GROUP BY bucket""",
            (fmt, date_from, date_to),
        )
    }
    closed = {
        r["bucket"]: r["n"]
        for r in db.query(
            """SELECT strftime(?, COALESCE(f.closed_at, f.resolved_at)) AS bucket,
                      COUNT(*) AS n
                 FROM faults f
                WHERE COALESCE(f.closed_at, f.resolved_at) IS NOT NULL
                  AND date(COALESCE(f.closed_at, f.resolved_at)) BETWEEN date(?) AND date(?)
                GROUP BY bucket""",
            (fmt, date_from, date_to),
        )
    }

    buckets = _bucket_range(date_from, date_to, group)
    return [
        {"bucket": b, "opened": opened.get(b, 0), "closed": closed.get(b, 0)}
        for b in buckets
    ]


def _bucket_range(date_from: str, date_to: str, group: str) -> list[str]:
    """Boş günleri de içeren sıralı bucket listesi üretir."""
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if end < start:
        start, end = end, start

    seen: list[str] = []
    cursor = start
    while cursor <= end:
        if group == "ay":
            key = cursor.strftime("%Y-%m")
        elif group == "hafta":
            key = cursor.strftime("%Y-W%W")
        else:
            key = cursor.isoformat()
        if not seen or seen[-1] != key:
            seen.append(key)
        cursor += timedelta(days=1)
    return seen


# --- Personel bazlı -------------------------------------------------------
def workload_by_technician() -> list[dict]:
    rows = db.query(
        f"""
        SELECT u.id, u.full_name, u.role,
               SUM(CASE WHEN f.status IN ({_ACTIVE_IN}) THEN 1 ELSE 0 END) AS open_count,
               COUNT(f.id) AS total_count,
               AVG(CASE WHEN f.resolved_at IS NOT NULL
                        THEN (julianday(f.resolved_at) - julianday(f.created_at)) * 24.0
                   END) AS avg_hours
          FROM users u
     LEFT JOIN faults f ON f.assignee_id = u.id
         WHERE u.role IN (?, ?) AND u.is_active = 1
         GROUP BY u.id
         ORDER BY open_count DESC, u.full_name COLLATE NOCASE
        """,
        (*config.ACTIVE_STATUSES, config.ROLE_TECHNICIAN, config.ROLE_MANAGER),
    )
    return [dict(r) for r in rows]
