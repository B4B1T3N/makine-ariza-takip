"""Uygulama içi bildirimler.

MVP kapsamında yalnızca uygulama içi bildirim listesi vardır. E-posta/SMS
gönderimi internetsiz çalışma gereği nedeniyle kapsam dışıdır; ileride
`_deliver()` fonksiyonuna bir e-posta kanalı eklenerek genişletilebilir.
"""
from __future__ import annotations

import sqlite3

from app import config
from app.db import database as db
from app.utils.helpers import now_sql


def _deliver(user_id: int, fault_id: int | None, title: str, message: str) -> None:
    """Tek bir kullanıcıya bildirim yazar.

    İleride e-posta desteği eklenecekse genişletme noktası burasıdır.
    """
    db.execute(
        """INSERT INTO notifications (user_id, fault_id, title, message, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, fault_id, title, message, now_sql()),
    )


def _technician_ids(exclude: set[int] | None = None) -> list[int]:
    exclude = exclude or set()
    rows = db.query(
        "SELECT id FROM users WHERE is_active = 1 AND role IN (?, ?)",
        (config.ROLE_TECHNICIAN, config.ROLE_MANAGER),
    )
    return [r["id"] for r in rows if r["id"] not in exclude]


# --- Olaylar --------------------------------------------------------------
def notify_new_fault(
    fault_id: int,
    machine_name: str,
    title: str,
    priority: str,
    reporter_id: int,
    assignee_id: int | None,
) -> None:
    """Yeni arıza: atanan teknisyene, atama yoksa tüm teknisyenlere."""
    prio = config.PRIORITY_LABELS.get(priority, priority)
    head = f"Yeni arıza #{fault_id} ({prio})"
    body = f"{machine_name} — {title}"

    targets = [assignee_id] if assignee_id else _technician_ids(exclude={reporter_id})
    for uid in targets:
        if uid:
            _deliver(uid, fault_id, head, body)


def notify_status_change(
    fault_id: int,
    fault: sqlite3.Row,
    old_status: str,
    new_status: str,
    actor_id: int,
) -> None:
    """Durum değişikliği: kaydı açan operatöre ve varsa atanan teknisyene."""
    head = f"Arıza #{fault_id} durumu güncellendi"
    body = (
        f"{fault['machine_name']} — {fault['title']}\n"
        f"{config.STATUS_LABELS.get(old_status, old_status)} → "
        f"{config.STATUS_LABELS.get(new_status, new_status)}"
    )
    for uid in _recipients(fault, actor_id):
        _deliver(uid, fault_id, head, body)


def notify_assignment(fault_id: int, fault: sqlite3.Row, assignee_id: int) -> None:
    _deliver(
        assignee_id,
        fault_id,
        f"Arıza #{fault_id} size atandı",
        f"{fault['machine_name']} — {fault['title']}",
    )


def notify_note(fault_id: int, fault: sqlite3.Row, note: str, actor_id: int) -> None:
    short = note if len(note) <= 120 else note[:117] + "..."
    for uid in _recipients(fault, actor_id):
        _deliver(uid, fault_id, f"Arıza #{fault_id} için yeni not", short)


def notify_priority_change(
    fault_id: int, fault: sqlite3.Row, new_priority: str, actor_id: int
) -> None:
    head = f"Arıza #{fault_id} önceliği değişti"
    body = (
        f"{fault['machine_name']} — "
        f"{config.PRIORITY_LABELS.get(fault['priority'])} → "
        f"{config.PRIORITY_LABELS.get(new_priority)}"
    )
    for uid in _recipients(fault, actor_id):
        _deliver(uid, fault_id, head, body)


def _recipients(fault: sqlite3.Row, actor_id: int) -> set[int]:
    """İlgili taraflar: kaydı açan + atanan teknisyen (işlemi yapan hariç)."""
    people = {fault["reporter_id"], fault["assignee_id"]}
    people.discard(None)
    people.discard(actor_id)
    return people  # type: ignore[return-value]


# --- Okuma / yönetim ------------------------------------------------------
def list_for_user(user_id: int, unread_only: bool = False, limit: int = 100) -> list[sqlite3.Row]:
    sql = "SELECT * FROM notifications WHERE user_id = ?"
    params: list = [user_id]
    if unread_only:
        sql += " AND is_read = 0"
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return db.query(sql, tuple(params))


def unread_count(user_id: int) -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)
    )


def mark_read(notification_id: int) -> None:
    db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))


def mark_all_read(user_id: int) -> None:
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))


def delete_all(user_id: int) -> None:
    db.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
