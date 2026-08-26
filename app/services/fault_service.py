"""Arıza kayıtları: oluşturma, filtreleme, durum akışı, geçmiş ve ekler."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from app import config
from app.db import database as db
from app.services import notification_service
from app.utils.helpers import now_utc, to_utc


class FaultError(Exception):
    """Arıza işlemi hatası (kullanıcıya gösterilebilir mesaj)."""


class ConcurrentEditError(FaultError):
    """Kayıt başka biri tarafından değiştirilmiş (iyimser kilitleme)."""


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

# Rapor ve filtrelerdeki gün sınırları sunucunun değil, tesisin saatine göre
# hesaplanmalıdır.
_LOCAL_DAY = f"(f.occurred_at AT TIME ZONE '{config.APP_TIMEZONE}')::date"


# --- Sorgulama ------------------------------------------------------------
def _filtre(
    search: str = "",
    machine_id: int | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    reporter_id: int | None = None,
    assignee_id: int | None = None,
    only_active: bool = False,
) -> tuple[str, list]:
    """Ortak WHERE koşulu. Liste ve sayım aynı filtreyi kullanmalıdır."""
    sql = " WHERE TRUE"
    params: list = []

    if search:
        sql += """ AND (f.title ILIKE %s OR f.description ILIKE %s
                        OR m.name ILIKE %s OR f.id::text = %s)"""
        like = f"%{search}%"
        params += [like, like, like, search]
    if machine_id:
        sql += " AND f.machine_id = %s"
        params.append(machine_id)
    if statuses:
        sql += " AND f.status = ANY(%s)"
        params.append(list(statuses))
    elif only_active:
        sql += " AND f.status = ANY(%s)"
        params.append(list(config.ACTIVE_STATUSES))
    if priorities:
        sql += " AND f.priority = ANY(%s)"
        params.append(list(priorities))
    if date_from:
        sql += f" AND {_LOCAL_DAY} >= %s::date"
        params.append(date_from)
    if date_to:
        sql += f" AND {_LOCAL_DAY} <= %s::date"
        params.append(date_to)
    if reporter_id:
        sql += " AND f.reporter_id = %s"
        params.append(reporter_id)
    if assignee_id:
        sql += " AND f.assignee_id = %s"
        params.append(assignee_id)

    return sql, params


# Açık kayıtlar üstte, içlerinde en acil olan başta, eşitlikte en yeni önce.
_SIRALAMA = """ ORDER BY
        CASE WHEN f.status IN ('cozuldu', 'kapatildi') THEN 1 ELSE 0 END,
        CASE f.priority WHEN 'acil' THEN 0 WHEN 'yuksek' THEN 1
                        WHEN 'orta' THEN 2 ELSE 3 END,
        f.occurred_at DESC, f.id DESC"""


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
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Filtrelenmiş arıza listesi. Tarihler 'YYYY-MM-DD' formatında beklenir.

    `limit`/`offset` web arayüzünün sayfalaması içindir; verilmezse tüm sonuç
    döner (masaüstü arayüz böyle çağırır).
    """
    where, params = _filtre(
        search, machine_id, statuses, priorities, date_from, date_to,
        reporter_id, assignee_id, only_active,
    )
    sql = _FAULT_SELECT + where + _SIRALAMA
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params += [limit, max(0, offset)]
    return db.query(sql, tuple(params))


def count_faults(
    search: str = "",
    machine_id: int | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    reporter_id: int | None = None,
    assignee_id: int | None = None,
    only_active: bool = False,
) -> int:
    """Aynı filtreye uyan toplam kayıt sayısı (sayfalama için)."""
    where, params = _filtre(
        search, machine_id, statuses, priorities, date_from, date_to,
        reporter_id, assignee_id, only_active,
    )
    sql = """SELECT COUNT(*) FROM faults f
               JOIN machines m ON m.id = f.machine_id""" + where
    return db.scalar(sql, tuple(params))


def get_fault(fault_id: int) -> dict | None:
    return db.query_one(_FAULT_SELECT + " WHERE f.id = %s", (fault_id,))


def get_fault_by_client_uuid(client_uuid: str) -> dict | None:
    """Çevrimdışı kuyruktan gelen kaydın daha önce işlenip işlenmediğini kontrol eder."""
    return db.query_one(_FAULT_SELECT + " WHERE f.client_uuid = %s", (client_uuid,))


def list_machine_faults(machine_id: int, limit: int | None = None) -> list[dict]:
    sql = _FAULT_SELECT + " WHERE f.machine_id = %s ORDER BY f.occurred_at DESC"
    params: list = [machine_id]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return db.query(sql, tuple(params))


def get_logs(fault_id: int) -> list[dict]:
    return db.query(
        """SELECT l.*, u.full_name AS user_name
             FROM fault_logs l
        LEFT JOIN users u ON u.id = l.user_id
            WHERE l.fault_id = %s
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
    client_uuid: str | None = None,
    occurred_at: datetime | None = None,
) -> int:
    """Yeni arıza kaydı açar.

    `client_uuid` çevrimdışı kuyruktan gelen kayıtlar içindir: aynı uuid ile
    ikinci kez çağrılırsa yeni kayıt açılmaz, mevcut kaydın kimliği döner.
    `occurred_at` arızanın cihazda yazıldığı andır; verilmezse şimdi kabul edilir.
    """
    title = (title or "").strip()
    if not machine_id:
        raise FaultError("Makine seçiniz.")
    if not title:
        raise FaultError("Arıza başlığı boş olamaz.")
    if priority not in config.PRIORITIES:
        raise FaultError("Geçersiz öncelik.")

    # Aynı kaydın tekrar gönderilmesi yeni kayıt oluşturmamalı.
    if client_uuid:
        existing = get_fault_by_client_uuid(client_uuid)
        if existing is not None:
            return existing["id"]

    machine = db.query_one("SELECT * FROM machines WHERE id = %s", (machine_id,))
    if machine is None:
        raise FaultError("Seçilen makine bulunamadı.")
    if not machine["is_active"]:
        raise FaultError("Pasif durumdaki bir makine için arıza kaydı açılamaz.")

    now = now_utc()
    # Cihaz saati ileri gitmiş olabilir; gelecekteki bir an kabul edilmez.
    stamp = min(to_utc(occurred_at), now) if occurred_at else now

    with db.transaction():
        fault_id = db.insert(
            """INSERT INTO faults
                   (client_uuid, machine_id, title, description, priority, status,
                    reporter_id, assignee_id, occurred_at, created_at, updated_at)
               VALUES (COALESCE(%s, gen_random_uuid()), %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s)""",
            (
                client_uuid,
                machine_id,
                title,
                (description or "").strip(),
                priority,
                config.STATUS_OPEN,
                reporter_id,
                assignee_id,
                stamp,
                now,
                now,
            ),
        )
        # Oluşturma logu, kaydın sunucuya ulaştığı anı değil yazıldığı anı taşır.
        _add_log(fault_id, reporter_id, config.LOG_CREATED,
                 new_value=config.STATUS_OPEN, created_at=stamp)
        if assignee_id:
            _add_log(fault_id, reporter_id, config.LOG_ASSIGN, new_value=str(assignee_id))

        notification_service.notify_new_fault(
            fault_id, machine["name"], title, priority, reporter_id, assignee_id
        )
    return fault_id


def update_fault(
    fault_id: int,
    user_id: int,
    machine_id: int,
    title: str,
    description: str,
    priority: str,
    expected_version: int | None = None,
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

    with db.transaction():
        _bump_version(fault_id, expected_version)
        db.execute(
            """UPDATE faults
                  SET machine_id = %s, title = %s, description = %s,
                      priority = %s, updated_at = %s
                WHERE id = %s""",
            (machine_id, title, (description or "").strip(), priority,
             now_utc(), fault_id),
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


def change_status(
    fault_id: int,
    user_id: int,
    new_status: str,
    note: str = "",
    expected_version: int | None = None,
) -> None:
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

    now = now_utc()
    sql = "UPDATE faults SET status = %s, updated_at = %s"
    params: list = [new_status, now]

    if new_status == config.STATUS_RESOLVED:
        sql += ", resolved_at = %s"
        params.append(now)
    elif new_status == config.STATUS_CLOSED:
        sql += ", closed_at = %s"
        params.append(now)
        if fault["resolved_at"] is None:
            sql += ", resolved_at = %s"
            params.append(now)
    elif old_status in (config.STATUS_RESOLVED, config.STATUS_CLOSED):
        # Yeniden açılan kayıtta çözüm zamanı sıfırlanır.
        sql += ", resolved_at = NULL, closed_at = NULL"

    sql += " WHERE id = %s"
    params.append(fault_id)

    with db.transaction():
        _bump_version(fault_id, expected_version)
        db.execute(sql, tuple(params))
        _add_log(
            fault_id, user_id, config.LOG_STATUS,
            old_value=old_status, new_value=new_status,
            note=(note or "").strip() or None,
        )
        notification_service.notify_status_change(
            fault_id, fault, old_status, new_status, user_id
        )


def add_note(fault_id: int, user_id: int, note: str) -> None:
    note = (note or "").strip()
    if not note:
        raise FaultError("Not boş olamaz.")
    fault = get_fault(fault_id)
    if fault is None:
        raise FaultError("Arıza kaydı bulunamadı.")

    with db.transaction():
        _add_log(fault_id, user_id, config.LOG_NOTE, note=note)
        db.execute(
            "UPDATE faults SET updated_at = %s WHERE id = %s", (now_utc(), fault_id)
        )
        notification_service.notify_note(fault_id, fault, note, user_id)


def assign(fault_id: int, user_id: int, assignee_id: int | None) -> None:
    fault = get_fault(fault_id)
    if fault is None:
        raise FaultError("Arıza kaydı bulunamadı.")
    if fault["assignee_id"] == assignee_id:
        return

    old_name = fault["assignee_name"] or "Atanmamış"
    new_name = "Atanmamış"
    if assignee_id:
        row = db.query_one("SELECT full_name FROM users WHERE id = %s", (assignee_id,))
        new_name = row["full_name"] if row else "Bilinmiyor"

    with db.transaction():
        db.execute(
            "UPDATE faults SET assignee_id = %s, updated_at = %s WHERE id = %s",
            (assignee_id, now_utc(), fault_id),
        )
        _add_log(
            fault_id, user_id, config.LOG_ASSIGN,
            old_value=old_name, new_value=new_name,
            note=f"{old_name} → {new_name}",
        )
        if assignee_id and assignee_id != user_id:
            notification_service.notify_assignment(fault_id, fault, assignee_id)


# --- Ekler ----------------------------------------------------------------
def add_attachment(fault_id: int, user_id: int, source_path: str) -> int:
    """Dosyayı ek olarak kaydeder.

    Faz 1'de dosyalar hâlâ yerel klasörde tutulur; Faz 4'te nesne depolamaya
    (S3/Blob) taşınacak. Veritabanı tarafı o geçişte değişmeyecek.
    """
    src = Path(source_path)
    if not src.is_file():
        raise FaultError("Dosya bulunamadı.")
    if src.stat().st_size > 20 * 1024 * 1024:
        raise FaultError("Dosya boyutu 20 MB'ı aşamaz.")

    stored_name = f"{fault_id}_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
    shutil.copy2(src, config.attachments_dir() / stored_name)

    with db.transaction():
        att_id = db.insert(
            """INSERT INTO attachments (fault_id, file_name, stored_name, uploaded_by)
               VALUES (%s, %s, %s, %s)""",
            (fault_id, src.name, stored_name, user_id),
        )
        _add_log(fault_id, user_id, config.LOG_ATTACHMENT,
                 new_value=src.name, note=src.name)
    return att_id


def list_attachments(fault_id: int) -> list[dict]:
    return db.query(
        """SELECT a.*, u.full_name AS uploader_name
             FROM attachments a
        LEFT JOIN users u ON u.id = a.uploaded_by
            WHERE a.fault_id = %s
         ORDER BY a.created_at DESC""",
        (fault_id,),
    )


def attachment_path(stored_name: str) -> Path:
    return config.attachments_dir() / stored_name


def delete_attachment(attachment_id: int) -> None:
    row = db.query_one("SELECT * FROM attachments WHERE id = %s", (attachment_id,))
    if row is None:
        return
    path = attachment_path(row["stored_name"])
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass  # Dosya kilitliyse kayıt yine de silinsin.
    db.execute("DELETE FROM attachments WHERE id = %s", (attachment_id,))


# --- Yardımcı -------------------------------------------------------------
def _bump_version(fault_id: int, expected_version: int | None) -> None:
    """Sürüm numarasını artırır; beklenen sürüm verilmişse çakışmayı yakalar.

    `expected_version=None` geldiğinde kontrol yapılmaz — masaüstü arayüz
    tek kullanıcılı olduğu için sürüm göndermez. Web arayüzü gönderecek.
    """
    if expected_version is None:
        db.execute("UPDATE faults SET version = version + 1 WHERE id = %s", (fault_id,))
        return

    changed = db.execute(
        "UPDATE faults SET version = version + 1 WHERE id = %s AND version = %s",
        (fault_id, expected_version),
    )
    if not changed:
        raise ConcurrentEditError(
            "Bu kayıt siz görüntülerken başka biri tarafından değiştirildi. "
            "Sayfayı yenileyip tekrar deneyin."
        )


def _add_log(
    fault_id: int,
    user_id: int | None,
    action: str,
    old_value: str | None = None,
    new_value: str | None = None,
    note: str | None = None,
    created_at: datetime | None = None,
) -> None:
    db.insert(
        """INSERT INTO fault_logs
               (fault_id, user_id, action, old_value, new_value, note, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (fault_id, user_id, action, old_value, new_value, note,
         created_at or now_utc()),
    )


def available_transitions(status: str) -> tuple[str, ...]:
    return config.STATUS_TRANSITIONS.get(status, ())
