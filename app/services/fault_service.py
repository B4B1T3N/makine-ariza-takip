"""Arıza kayıtları: oluşturma, filtreleme, durum akışı, geçmiş ve ekler."""
from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path

from app import config
from app.db import database as db
from app.services import notification_service
from app.utils.helpers import now_sql


class FaultError(Exception):
    """Arıza işlemi hatası (kullanıcıya gösterilebilir mesaj)."""


_FAULT_SELECT = """
    SELECT f.*,
           m.name       AS machine_name,
           m.serial_no  AS machine_serial,
           m.location   AS machine_location,
           m.category   AS machine_category,
           r.full_name  AS reporter_name,
           a.full_name  AS assignee_name
      FROM faults f
      JOIN machines m ON m.id = f.machine_id
      JOIN users    r ON r.id = f.reporter_id
 LEFT JOIN users    a ON a.id = f.assignee_id
"""


# --- Sorgulama ------------------------------------------------------------
def list_faults(
    search: str = "",
    machine_id: int | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    reporter_id: int | None = None,
    assignee_id: int | None = None,
    only_active: bool = False,
) -> list[sqlite3.Row]:
    """Filtrelenmiş arıza listesi. Tarihler 'YYYY-MM-DD' formatında beklenir."""
    sql = _FAULT_SELECT + " WHERE 1=1"
    params: list = []

    if search:
        sql += " AND (f.title LIKE ? OR f.description LIKE ? OR m.name LIKE ? OR CAST(f.id AS TEXT) = ?)"
        like = f"%{search}%"
        params += [like, like, like, search]
    if machine_id:
        sql += " AND f.machine_id = ?"
        params.append(machine_id)
    if statuses:
        sql += f" AND f.status IN ({', '.join('?' for _ in statuses)})"
        params += statuses
    elif only_active:
        sql += f" AND f.status IN ({', '.join('?' for _ in config.ACTIVE_STATUSES)})"
        params += list(config.ACTIVE_STATUSES)
    if priorities:
        sql += f" AND f.priority IN ({', '.join('?' for _ in priorities)})"
        params += priorities
    if date_from:
        sql += " AND date(f.created_at) >= date(?)"
        params.append(date_from)
    if date_to:
        sql += " AND date(f.created_at) <= date(?)"
        params.append(date_to)
    if reporter_id:
        sql += " AND f.reporter_id = ?"
        params.append(reporter_id)
    if assignee_id:
        sql += " AND f.assignee_id = ?"
        params.append(assignee_id)

    sql += """ ORDER BY
        CASE f.status WHEN 'kapatildi' THEN 1 WHEN 'cozuldu' THEN 1 ELSE 0 END,
        CASE f.priority WHEN 'acil' THEN 0 WHEN 'yuksek' THEN 1 WHEN 'orta' THEN 2 ELSE 3 END,
        f.created_at DESC"""
    return db.query(sql, tuple(params))


def get_fault(fault_id: int) -> sqlite3.Row | None:
    return db.query_one(_FAULT_SELECT + " WHERE f.id = ?", (fault_id,))


def list_machine_faults(machine_id: int, limit: int | None = None) -> list[sqlite3.Row]:
    sql = _FAULT_SELECT + " WHERE f.machine_id = ? ORDER BY f.created_at DESC"
    params: list = [machine_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return db.query(sql, tuple(params))


def get_logs(fault_id: int) -> list[sqlite3.Row]:
    return db.query(
        """SELECT l.*, u.full_name AS user_name
             FROM fault_logs l
        LEFT JOIN users u ON u.id = l.user_id
            WHERE l.fault_id = ?
         ORDER BY l.created_at ASC, l.id ASC""",
        (fault_id,),
    )


# --- Oluşturma / düzenleme ------------------------------------------------
def create_fault(
    machine_id: int,
    title: str,
    description: str,
    priority: str,
    reporter_id: int,
    assignee_id: int | None = None,
) -> int:
    title = (title or "").strip()
    if not machine_id:
        raise FaultError("Makine seçiniz.")
    if not title:
        raise FaultError("Arıza başlığı boş olamaz.")
    if priority not in config.PRIORITIES:
        raise FaultError("Geçersiz öncelik.")

    machine = db.query_one("SELECT * FROM machines WHERE id = ?", (machine_id,))
    if machine is None:
        raise FaultError("Seçilen makine bulunamadı.")
    if not machine["is_active"]:
        raise FaultError("Pasif durumdaki bir makine için arıza kaydı açılamaz.")

    stamp = now_sql()
    fault_id = db.execute(
        """INSERT INTO faults
               (machine_id, title, description, priority, status,
                reporter_id, assignee_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            machine_id,
            title,
            (description or "").strip(),
            priority,
            config.STATUS_OPEN,
            reporter_id,
            assignee_id,
            stamp,
            stamp,
        ),
    )
    _add_log(fault_id, reporter_id, config.LOG_CREATED, new_value=config.STATUS_OPEN)
    if assignee_id:
        _add_log(fault_id, reporter_id, config.LOG_ASSIGN, new_value=str(assignee_id))

    notification_service.notify_new_fault(fault_id, machine["name"], title, priority,
                                          reporter_id, assignee_id)
    return fault_id


def update_fault(
    fault_id: int,
    user_id: int,
    machine_id: int,
    title: str,
    description: str,
    priority: str,
) -> None:
    """Kaydın içerik alanlarını günceller (durum değişikliği ayrı akıştadır)."""
    fault = get_fault(fault_id)
    if fault is None:
        raise FaultError("Arıza kaydı bulunamadı.")
    title = (title or "").strip()
    if not title:
        raise FaultError("Arıza başlığı boş olamaz.")
    if priority not in config.PRIORITIES:
        raise FaultError("Geçersiz öncelik.")

    db.execute(
        """UPDATE faults
              SET machine_id = ?, title = ?, description = ?, priority = ?, updated_at = ?
            WHERE id = ?""",
        (machine_id, title, (description or "").strip(), priority, now_sql(), fault_id),
    )

    changes = []
    if fault["priority"] != priority:
        changes.append(
            f"Öncelik: {config.PRIORITY_LABELS[fault['priority']]} → "
            f"{config.PRIORITY_LABELS[priority]}"
        )
        notification_service.notify_priority_change(fault_id, fault, priority, user_id)
    if fault["machine_id"] != machine_id:
        changes.append("Makine değiştirildi")
    if fault["title"] != title:
        changes.append("Başlık güncellendi")
    if (fault["description"] or "") != (description or "").strip():
        changes.append("Açıklama güncellendi")
    if changes:
        _add_log(fault_id, user_id, config.LOG_EDIT, note="; ".join(changes))


def change_status(fault_id: int, user_id: int, new_status: str, note: str = "") -> None:
    fault = get_fault(fault_id)
    if fault is None:
        raise FaultError("Arıza kaydı bulunamadı.")
    old_status = fault["status"]
    if new_status == old_status:
        raise FaultError("Kayıt zaten bu durumda.")
    if new_status not in config.STATUS_TRANSITIONS.get(old_status, ()):
        raise FaultError(
            f"'{config.STATUS_LABELS[old_status]}' durumundan "
            f"'{config.STATUS_LABELS[new_status]}' durumuna geçilemez."
        )
    if new_status in (config.STATUS_RESOLVED, config.STATUS_CLOSED) and not (note or "").strip():
        raise FaultError("Çözüm/kapatma işlemi için açıklama girilmesi zorunludur.")

    stamp = now_sql()
    sql = "UPDATE faults SET status = ?, updated_at = ?"
    params: list = [new_status, stamp]

    if new_status == config.STATUS_RESOLVED:
        sql += ", resolved_at = ?"
        params.append(stamp)
    elif new_status == config.STATUS_CLOSED:
        sql += ", closed_at = ?"
        params.append(stamp)
        if fault["resolved_at"] is None:
            sql += ", resolved_at = ?"
            params.append(stamp)
    elif old_status in (config.STATUS_RESOLVED, config.STATUS_CLOSED):
        # Yeniden açılan kayıtta çözüm zamanı sıfırlanır.
        sql += ", resolved_at = NULL, closed_at = NULL"

    sql += " WHERE id = ?"
    params.append(fault_id)
    db.execute(sql, tuple(params))

    _add_log(
        fault_id, user_id, config.LOG_STATUS,
        old_value=old_status, new_value=new_status, note=(note or "").strip() or None,
    )
    notification_service.notify_status_change(fault_id, fault, old_status, new_status, user_id)


def add_note(fault_id: int, user_id: int, note: str) -> None:
    note = (note or "").strip()
    if not note:
        raise FaultError("Not boş olamaz.")
    fault = get_fault(fault_id)
    if fault is None:
        raise FaultError("Arıza kaydı bulunamadı.")
    _add_log(fault_id, user_id, config.LOG_NOTE, note=note)
    db.execute("UPDATE faults SET updated_at = ? WHERE id = ?", (now_sql(), fault_id))
    notification_service.notify_note(fault_id, fault, note, user_id)


def assign(fault_id: int, user_id: int, assignee_id: int | None) -> None:
    fault = get_fault(fault_id)
    if fault is None:
        raise FaultError("Arıza kaydı bulunamadı.")
    if fault["assignee_id"] == assignee_id:
        return

    db.execute(
        "UPDATE faults SET assignee_id = ?, updated_at = ? WHERE id = ?",
        (assignee_id, now_sql(), fault_id),
    )
    old_name = fault["assignee_name"] or "Atanmamış"
    new_name = "Atanmamış"
    if assignee_id:
        row = db.query_one("SELECT full_name FROM users WHERE id = ?", (assignee_id,))
        new_name = row["full_name"] if row else "Bilinmiyor"
    _add_log(
        fault_id, user_id, config.LOG_ASSIGN,
        old_value=old_name, new_value=new_name,
        note=f"{old_name} → {new_name}",
    )
    if assignee_id and assignee_id != user_id:
        notification_service.notify_assignment(fault_id, fault, assignee_id)


# --- Ekler ----------------------------------------------------------------
def add_attachment(fault_id: int, user_id: int, source_path: str) -> int:
    src = Path(source_path)
    if not src.is_file():
        raise FaultError("Dosya bulunamadı.")
    if src.stat().st_size > 20 * 1024 * 1024:
        raise FaultError("Dosya boyutu 20 MB'ı aşamaz.")

    stored_name = f"{fault_id}_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
    shutil.copy2(src, config.attachments_dir() / stored_name)

    att_id = db.execute(
        """INSERT INTO attachments (fault_id, file_name, stored_name, uploaded_by)
           VALUES (?, ?, ?, ?)""",
        (fault_id, src.name, stored_name, user_id),
    )
    _add_log(fault_id, user_id, config.LOG_ATTACHMENT, new_value=src.name, note=src.name)
    return att_id


def list_attachments(fault_id: int) -> list[sqlite3.Row]:
    return db.query(
        """SELECT a.*, u.full_name AS uploader_name
             FROM attachments a
        LEFT JOIN users u ON u.id = a.uploaded_by
            WHERE a.fault_id = ?
         ORDER BY a.created_at DESC""",
        (fault_id,),
    )


def attachment_path(stored_name: str) -> Path:
    return config.attachments_dir() / stored_name


def delete_attachment(attachment_id: int) -> None:
    row = db.query_one("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
    if row is None:
        return
    path = attachment_path(row["stored_name"])
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass  # Dosya kilitliyse kayıt yine de silinsin.
    db.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))


# --- Yardımcı -------------------------------------------------------------
def _add_log(
    fault_id: int,
    user_id: int | None,
    action: str,
    old_value: str | None = None,
    new_value: str | None = None,
    note: str | None = None,
) -> None:
    db.execute(
        """INSERT INTO fault_logs (fault_id, user_id, action, old_value, new_value, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (fault_id, user_id, action, old_value, new_value, note, now_sql()),
    )


def available_transitions(status: str) -> tuple[str, ...]:
    return config.STATUS_TRANSITIONS.get(status, ())
