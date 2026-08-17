"""Dashboard ve rapor sorguları.

Zaman kuralı: veritabanı UTC saklar, ama "bugün açılan" gibi gün bazlı
sayımlar tesisin yerel gününe göre hesaplanmalıdır. Bu yüzden tarih
karşılaştırmaları `AT TIME ZONE` ile yerel güne çevrilir.

Süre hesapları `occurred_at` (arızanın yazıldığı an) üzerinden yapılır,
`created_at` (sunucuya ulaştığı an) üzerinden değil — çevrimdışı girilen
kayıtlarda ikisi farklıdır.
"""
from __future__ import annotations

from datetime import date, timedelta

from app import config
from app.db import database as db
from app.utils.helpers import today_local

_TZ = config.APP_TIMEZONE
_LOCAL_DAY = f"(f.occurred_at AT TIME ZONE '{_TZ}')::date"
_LOCAL_CLOSE_DAY = (
    f"(COALESCE(f.closed_at, f.resolved_at) AT TIME ZONE '{_TZ}')::date"
)
# Çözüm süresi saat cinsinden.
_RESOLUTION_HOURS = "EXTRACT(EPOCH FROM (f.resolved_at - f.occurred_at)) / 3600.0"


def _date_filter(date_from: str | None, date_to: str | None):
    sql, params = "", []
    if date_from:
        sql += f" AND {_LOCAL_DAY} >= %s::date"
        params.append(date_from)
    if date_to:
        sql += f" AND {_LOCAL_DAY} <= %s::date"
        params.append(date_to)
    return sql, params


def _f(value) -> float | None:
    """Decimal -> float (psycopg AVG sonucunu Decimal döner)."""
    return float(value) if value is not None else None


# --- Dashboard özeti ------------------------------------------------------
def summary() -> dict:
    today = today_local().isoformat()
    active = list(config.ACTIVE_STATUSES)
    return {
        "open_total": db.scalar(
            "SELECT COUNT(*) FROM faults f WHERE f.status = ANY(%s)", (active,)
        ),
        "urgent_open": db.scalar(
            """SELECT COUNT(*) FROM faults f
                WHERE f.status = ANY(%s) AND f.priority = %s""",
            (active, config.PRIORITY_URGENT),
        ),
        "opened_today": db.scalar(
            f"SELECT COUNT(*) FROM faults f WHERE {_LOCAL_DAY} = %s::date", (today,)
        ),
        "closed_today": db.scalar(
            f"SELECT COUNT(*) FROM faults f WHERE {_LOCAL_CLOSE_DAY} = %s::date",
            (today,),
        ),
        "unassigned": db.scalar(
            """SELECT COUNT(*) FROM faults f
                WHERE f.status = ANY(%s) AND f.assignee_id IS NULL""",
            (active,),
        ),
        "avg_resolution_hours": avg_resolution_hours(),
        "machine_count": db.scalar("SELECT COUNT(*) FROM machines WHERE is_active"),
    }


def status_distribution(date_from: str | None = None, date_to: str | None = None) -> dict[str, int]:
    extra, params = _date_filter(date_from, date_to)
    rows = db.query(
        f"""SELECT f.status, COUNT(*) AS n FROM faults f
             WHERE TRUE {extra} GROUP BY f.status""",
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
    sql = f"SELECT f.priority, COUNT(*) AS n FROM faults f WHERE TRUE {extra}"
    if only_active:
        sql += " AND f.status = ANY(%s)"
        params.append(list(config.ACTIVE_STATUSES))
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
               COUNT(*) FILTER (WHERE f.status = ANY(%s)) AS open_count,
               AVG({_RESOLUTION_HOURS}) FILTER (WHERE f.resolved_at IS NOT NULL)
                   AS avg_hours
          FROM machines m
          JOIN faults f ON f.machine_id = m.id
         WHERE TRUE {extra}
         GROUP BY m.id
         ORDER BY fault_count DESC, m.name
         LIMIT %s
        """,
        (list(config.ACTIVE_STATUSES), *params, limit),
    )
    for row in rows:
        row["avg_hours"] = _f(row["avg_hours"])
    return rows


def avg_resolution_hours(
    machine_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> float | None:
    """Genel veya makine bazında ortalama çözüm süresi (saat)."""
    extra, params = _date_filter(date_from, date_to)
    sql = f"""SELECT AVG({_RESOLUTION_HOURS}) FROM faults f
               WHERE f.resolved_at IS NOT NULL {extra}"""
    if machine_id:
        sql += " AND f.machine_id = %s"
        params.append(machine_id)
    return _f(db.scalar(sql, tuple(params), default=None))


def resolution_by_machine(
    date_from: str | None = None, date_to: str | None = None
) -> list[dict]:
    """Makine bazında ortalama çözüm süresi tablosu."""
    extra, params = _date_filter(date_from, date_to)
    rows = db.query(
        f"""
        SELECT m.id, m.name, m.serial_no, m.location,
               COUNT(f.id) AS total,
               COUNT(*) FILTER (WHERE f.resolved_at IS NOT NULL) AS resolved,
               AVG({_RESOLUTION_HOURS}) FILTER (WHERE f.resolved_at IS NOT NULL) AS avg_hours,
               MIN({_RESOLUTION_HOURS}) FILTER (WHERE f.resolved_at IS NOT NULL) AS min_hours,
               MAX({_RESOLUTION_HOURS}) FILTER (WHERE f.resolved_at IS NOT NULL) AS max_hours
          FROM machines m
          JOIN faults f ON f.machine_id = m.id
         WHERE TRUE {extra}
         GROUP BY m.id
         ORDER BY avg_hours DESC NULLS LAST, m.name
        """,
        tuple(params),
    )
    for row in rows:
        for key in ("avg_hours", "min_hours", "max_hours"):
            row[key] = _f(row[key])
    return rows


# --- Trend ----------------------------------------------------------------
def trend(date_from: str, date_to: str, group: str = "gun") -> list[dict]:
    """Tarih aralığında açılan/kapanan arıza sayıları.

    group: 'gun' | 'hafta' | 'ay'
    """
    fmt = {"gun": "YYYY-MM-DD", "hafta": 'IYYY"-W"IW', "ay": "YYYY-MM"}.get(
        group, "YYYY-MM-DD"
    )

    opened = {
        r["bucket"]: r["n"]
        for r in db.query(
            f"""SELECT to_char(f.occurred_at AT TIME ZONE '{_TZ}', %s) AS bucket,
                       COUNT(*) AS n
                  FROM faults f
                 WHERE {_LOCAL_DAY} BETWEEN %s::date AND %s::date
                 GROUP BY bucket""",
            (fmt, date_from, date_to),
        )
    }
    closed = {
        r["bucket"]: r["n"]
        for r in db.query(
            f"""SELECT to_char(COALESCE(f.closed_at, f.resolved_at)
                               AT TIME ZONE '{_TZ}', %s) AS bucket,
                       COUNT(*) AS n
                  FROM faults f
                 WHERE COALESCE(f.closed_at, f.resolved_at) IS NOT NULL
                   AND {_LOCAL_CLOSE_DAY} BETWEEN %s::date AND %s::date
                 GROUP BY bucket""",
            (fmt, date_from, date_to),
        )
    }

    return [
        {"bucket": b, "opened": opened.get(b, 0), "closed": closed.get(b, 0)}
        for b in _bucket_range(date_from, date_to, group)
    ]


def _bucket_range(date_from: str, date_to: str, group: str) -> list[str]:
    """Boş günleri de içeren sıralı bucket listesi üretir.

    Etiketler PostgreSQL'in `to_char` çıktısıyla birebir aynı olmalıdır;
    hafta için ISO hafta numarası (IYYY-IW) kullanılır.
    """
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
            iso_year, iso_week, _ = cursor.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
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
               COUNT(*) FILTER (WHERE f.status = ANY(%s)) AS open_count,
               COUNT(f.id) AS total_count,
               AVG({_RESOLUTION_HOURS}) FILTER (WHERE f.resolved_at IS NOT NULL)
                   AS avg_hours
          FROM users u
     LEFT JOIN faults f ON f.assignee_id = u.id
         WHERE u.role = ANY(%s) AND u.is_active
         GROUP BY u.id
         ORDER BY open_count DESC, u.full_name
        """,
        (
            list(config.ACTIVE_STATUSES),
            [config.ROLE_TECHNICIAN, config.ROLE_MANAGER],
        ),
    )
    for row in rows:
        row["avg_hours"] = _f(row["avg_hours"])
    return rows
