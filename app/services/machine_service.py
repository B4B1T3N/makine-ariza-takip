"""Makine / ekipman envanteri işlemleri."""
from __future__ import annotations

import sqlite3

from app import config
from app.db import database as db


class MachineError(Exception):
    """Makine işlemi hatası (kullanıcıya gösterilebilir mesaj)."""


_ACTIVE_PLACEHOLDERS = ", ".join("?" for _ in config.ACTIVE_STATUSES)


def list_machines(
    search: str = "",
    include_inactive: bool = False,
    category: str | None = None,
) -> list[sqlite3.Row]:
    """Makineleri açık arıza sayısı ile birlikte listeler."""
    sql = f"""
        SELECT m.*,
               (SELECT COUNT(*) FROM faults f
                 WHERE f.machine_id = m.id
                   AND f.status IN ({_ACTIVE_PLACEHOLDERS})) AS open_faults,
               (SELECT COUNT(*) FROM faults f WHERE f.machine_id = m.id) AS total_faults
          FROM machines m
         WHERE 1=1
    """
    params: list = list(config.ACTIVE_STATUSES)
    if not include_inactive:
        sql += " AND m.is_active = 1"
    if search:
        sql += " AND (m.name LIKE ? OR m.serial_no LIKE ? OR m.location LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if category:
        sql += " AND m.category = ?"
        params.append(category)
    sql += " ORDER BY m.is_active DESC, m.name COLLATE NOCASE"
    return db.query(sql, tuple(params))


def get_machine(machine_id: int) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM machines WHERE id = ?", (machine_id,))


def list_categories() -> list[str]:
    rows = db.query(
        """SELECT DISTINCT category FROM machines
            WHERE category IS NOT NULL AND TRIM(category) <> ''
            ORDER BY category COLLATE NOCASE"""
    )
    return [r["category"] for r in rows]


def list_locations() -> list[str]:
    rows = db.query(
        """SELECT DISTINCT location FROM machines
            WHERE location IS NOT NULL AND TRIM(location) <> ''
            ORDER BY location COLLATE NOCASE"""
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
        return db.execute(
            """INSERT INTO machines (name, serial_no, location, category, commissioned_at, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                name,
                (serial_no or "").strip() or None,
                (location or "").strip(),
                (category or "").strip(),
                commissioned_at,
                (notes or "").strip(),
            ),
        )
    except sqlite3.IntegrityError as exc:
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
                  SET name = ?, serial_no = ?, location = ?, category = ?,
                      commissioned_at = ?, notes = ?, is_active = ?
                WHERE id = ?""",
            (
                name,
                (serial_no or "").strip() or None,
                (location or "").strip(),
                (category or "").strip(),
                commissioned_at,
                (notes or "").strip(),
                1 if is_active else 0,
                machine_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise MachineError(f"'{serial_no}' seri numarası zaten kayıtlı.") from exc


def set_active(machine_id: int, is_active: bool) -> None:
    if not is_active and open_fault_count(machine_id) > 0:
        raise MachineError(
            "Bu makinede kapanmamış arıza kaydı var. Önce kayıtları kapatın."
        )
    db.execute(
        "UPDATE machines SET is_active = ? WHERE id = ?",
        (1 if is_active else 0, machine_id),
    )


def open_fault_count(machine_id: int) -> int:
    return db.scalar(
        f"""SELECT COUNT(*) FROM faults
             WHERE machine_id = ? AND status IN ({_ACTIVE_PLACEHOLDERS})""",
        (machine_id, *config.ACTIVE_STATUSES),
    )


def machine_stats(machine_id: int) -> dict:
    """Makine detay ekranı için özet istatistikler."""
    total = db.scalar("SELECT COUNT(*) FROM faults WHERE machine_id = ?", (machine_id,))
    avg_hours = db.scalar(
        """SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24.0)
             FROM faults
            WHERE machine_id = ? AND resolved_at IS NOT NULL""",
        (machine_id,),
        default=None,
    )
    last = db.query_one(
        "SELECT created_at FROM faults WHERE machine_id = ? ORDER BY created_at DESC LIMIT 1",
        (machine_id,),
    )
    return {
        "total_faults": total,
        "open_faults": open_fault_count(machine_id),
        "avg_resolution_hours": avg_hours,
        "last_fault_at": last["created_at"] if last else None,
    }
