"""Makine / ekipman envanteri işlemleri."""
from __future__ import annotations

import psycopg

from app import config
from app.db import database as db

TR_COLLATE = 'COLLATE "tr-TR-x-icu"'


class MachineError(Exception):
    """Makine işlemi hatası (kullanıcıya gösterilebilir mesaj)."""


def list_machines(
    search: str = "",
    include_inactive: bool = False,
    category: str | None = None,
) -> list[dict]:
    """Makineleri açık arıza sayısı ile birlikte listeler."""
    sql = """
        SELECT m.*,
               (SELECT COUNT(*) FROM faults f
                 WHERE f.machine_id = m.id
                   AND f.status = ANY(%s)) AS open_faults,
               (SELECT COUNT(*) FROM faults f WHERE f.machine_id = m.id) AS total_faults
          FROM machines m
         WHERE TRUE
    """
    params: list = [list(config.ACTIVE_STATUSES)]
    if not include_inactive:
        sql += " AND m.is_active"
    if search:
        sql += """ AND (m.name ILIKE %s OR m.serial_no ILIKE %s
                        OR m.location ILIKE %s)"""
        like = f"%{search}%"
        params += [like, like, like]
    if category:
        sql += " AND m.category = %s"
        params.append(category)
    sql += f" ORDER BY m.is_active DESC, m.name {TR_COLLATE}"
    return db.query(sql, tuple(params))


def get_machine(machine_id: int) -> dict | None:
    return db.query_one("SELECT * FROM machines WHERE id = %s", (machine_id,))


# Not: PostgreSQL'de SELECT DISTINCT ile birlikte COLLATE'li ORDER BY
# kullanılamaz ("ORDER BY expressions must appear in select list").
# Aynı sonucu veren GROUP BY bu kısıtlamaya tabi değildir.
def list_categories() -> list[str]:
    rows = db.query(
        f"""SELECT category FROM machines
             WHERE category IS NOT NULL AND btrim(category) <> ''
             GROUP BY category
             ORDER BY category {TR_COLLATE}"""
    )
    return [r["category"] for r in rows]


def list_locations() -> list[str]:
    rows = db.query(
        f"""SELECT location FROM machines
             WHERE location IS NOT NULL AND btrim(location) <> ''
             GROUP BY location
             ORDER BY location {TR_COLLATE}"""
    )
    return [r["location"] for r in rows]


def create_machine(
    name: str,
    serial_no: str = "",
    location: str = "",
    category: str = "",
    commissioned_at: str | None = None,
    notes: str = "",
) -> int:
    name = (name or "").strip()
    if not name:
        raise MachineError("Makine adı boş olamaz.")
    try:
        return db.insert(
            """INSERT INTO machines
                   (name, serial_no, location, category, commissioned_at, notes)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                name,
                (serial_no or "").strip() or None,
                (location or "").strip(),
                (category or "").strip(),
                commissioned_at or None,
                (notes or "").strip(),
            ),
        )
    except psycopg.errors.UniqueViolation as exc:
        raise MachineError(f"'{serial_no}' seri numarası zaten kayıtlı.") from exc


def update_machine(
    machine_id: int,
    name: str,
    serial_no: str = "",
    location: str = "",
    category: str = "",
    commissioned_at: str | None = None,
    notes: str = "",
    is_active: bool = True,
) -> None:
    name = (name or "").strip()
    if not name:
        raise MachineError("Makine adı boş olamaz.")

    if not is_active and open_fault_count(machine_id) > 0:
        raise MachineError(
            "Bu makinede kapanmamış arıza kaydı var. Önce kayıtları kapatın."
        )

    try:
        db.execute(
            """UPDATE machines
                  SET name = %s, serial_no = %s, location = %s, category = %s,
                      commissioned_at = %s, notes = %s, is_active = %s
                WHERE id = %s""",
            (
                name,
                (serial_no or "").strip() or None,
                (location or "").strip(),
                (category or "").strip(),
                commissioned_at or None,
                (notes or "").strip(),
                bool(is_active),
                machine_id,
            ),
        )
    except psycopg.errors.UniqueViolation as exc:
        raise MachineError(f"'{serial_no}' seri numarası zaten kayıtlı.") from exc


def set_active(machine_id: int, is_active: bool) -> None:
    if not is_active and open_fault_count(machine_id) > 0:
        raise MachineError(
            "Bu makinede kapanmamış arıza kaydı var. Önce kayıtları kapatın."
        )
    db.execute(
        "UPDATE machines SET is_active = %s WHERE id = %s", (bool(is_active), machine_id)
    )


def open_fault_count(machine_id: int) -> int:
    return db.scalar(
        """SELECT COUNT(*) FROM faults
            WHERE machine_id = %s AND status = ANY(%s)""",
        (machine_id, list(config.ACTIVE_STATUSES)),
    )


def machine_stats(machine_id: int) -> dict:
    """Makine detay ekranı için özet istatistikler."""
    total = db.scalar("SELECT COUNT(*) FROM faults WHERE machine_id = %s", (machine_id,))
    avg_hours = db.scalar(
        """SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - occurred_at)) / 3600.0)
             FROM faults
            WHERE machine_id = %s AND resolved_at IS NOT NULL""",
        (machine_id,),
        default=None,
    )
    last = db.query_one(
        """SELECT occurred_at FROM faults
            WHERE machine_id = %s ORDER BY occurred_at DESC LIMIT 1""",
        (machine_id,),
    )
    return {
        "total_faults": total,
        "open_faults": open_fault_count(machine_id),
        "avg_resolution_hours": float(avg_hours) if avg_hours is not None else None,
        "last_fault_at": last["occurred_at"] if last else None,
    }
