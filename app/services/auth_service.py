"""Kimlik doğrulama, kullanıcı yönetimi ve yetki kontrolleri."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app import config
from app.db import database as db
from app.utils import security


class AuthError(Exception):
    """Giriş veya kullanıcı işlemi hatası (kullanıcıya gösterilebilir mesaj)."""


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    full_name: str
    role: str

    @property
    def role_label(self) -> str:
        return config.ROLE_LABELS.get(self.role, self.role)

    @property
    def is_manager(self) -> bool:
        return self.role == config.ROLE_MANAGER

    @property
    def is_technician(self) -> bool:
        return self.role == config.ROLE_TECHNICIAN

    @property
    def is_operator(self) -> bool:
        return self.role == config.ROLE_OPERATOR

    # --- Yetkiler ---------------------------------------------------------
    @property
    def can_manage_machines(self) -> bool:
        return self.is_manager

    @property
    def can_manage_users(self) -> bool:
        return self.is_manager

    @property
    def can_change_status(self) -> bool:
        """Teknisyen ve yönetici arıza durumunu güncelleyebilir."""
        return self.is_manager or self.is_technician

    @property
    def can_assign(self) -> bool:
        return self.is_manager or self.is_technician

    @property
    def can_view_all_faults(self) -> bool:
        """Operatör yalnızca kendi açtığı kayıtları görür."""
        return not self.is_operator

    @property
    def can_view_reports(self) -> bool:
        return self.is_manager or self.is_technician


def login(username: str, password: str) -> CurrentUser:
    username = (username or "").strip()
    if not username or not password:
        raise AuthError("Kullanıcı adı ve şifre giriniz.")

    row = db.query_one(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    )
    if row is None or not security.verify_password(
        password, row["salt"], row["password_hash"]
    ):
        raise AuthError("Kullanıcı adı veya şifre hatalı.")
    if not row["is_active"]:
        raise AuthError("Bu kullanıcı pasif durumda. Yöneticinize başvurun.")

    return CurrentUser(
        id=row["id"],
        username=row["username"],
        full_name=row["full_name"],
        role=row["role"],
    )


# --- Kullanıcı yönetimi ---------------------------------------------------
def list_users(include_inactive: bool = True, role: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM users WHERE 1=1"
    params: list = []
    if not include_inactive:
        sql += " AND is_active = 1"
    if role:
        sql += " AND role = ?"
        params.append(role)
    sql += " ORDER BY is_active DESC, full_name COLLATE NOCASE"
    return db.query(sql, tuple(params))


def list_technicians() -> list[sqlite3.Row]:
    """Atama yapılabilecek aktif kullanıcılar (teknisyen + yönetici)."""
    return db.query(
        """SELECT * FROM users
           WHERE is_active = 1 AND role IN (?, ?)
           ORDER BY full_name COLLATE NOCASE""",
        (config.ROLE_TECHNICIAN, config.ROLE_MANAGER),
    )


def get_user(user_id: int) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def create_user(username: str, password: str, full_name: str, role: str) -> int:
    username = (username or "").strip()
    full_name = (full_name or "").strip()
    if not username:
        raise AuthError("Kullanıcı adı boş olamaz.")
    if not full_name:
        raise AuthError("Ad soyad boş olamaz.")
    if len(password or "") < 4:
        raise AuthError("Şifre en az 4 karakter olmalıdır.")
    if role not in config.ROLES:
        raise AuthError("Geçersiz rol.")

    salt, pwd_hash = security.new_credentials(password)
    try:
        return db.execute(
            """INSERT INTO users (username, password_hash, salt, full_name, role)
               VALUES (?, ?, ?, ?, ?)""",
            (username, pwd_hash, salt, full_name, role),
        )
    except sqlite3.IntegrityError as exc:
        raise AuthError(f"'{username}' kullanıcı adı zaten kayıtlı.") from exc


def update_user(
    user_id: int,
    full_name: str,
    role: str,
    is_active: bool,
    new_password: str | None = None,
) -> None:
    full_name = (full_name or "").strip()
    if not full_name:
        raise AuthError("Ad soyad boş olamaz.")
    if role not in config.ROLES:
        raise AuthError("Geçersiz rol.")

    current = get_user(user_id)
    if current is None:
        raise AuthError("Kullanıcı bulunamadı.")

    # Sistemde en az bir aktif yönetici kalmalı.
    losing_manager = current["role"] == config.ROLE_MANAGER and current["is_active"]
    still_manager = role == config.ROLE_MANAGER and is_active
    if losing_manager and not still_manager and _active_manager_count() <= 1:
        raise AuthError("Sistemde en az bir aktif yönetici bulunmalıdır.")

    db.execute(
        "UPDATE users SET full_name = ?, role = ?, is_active = ? WHERE id = ?",
        (full_name, role, 1 if is_active else 0, user_id),
    )
    if new_password:
        change_password(user_id, new_password)


def change_password(user_id: int, new_password: str) -> None:
    if len(new_password or "") < 4:
        raise AuthError("Şifre en az 4 karakter olmalıdır.")
    salt, pwd_hash = security.new_credentials(new_password)
    db.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
        (pwd_hash, salt, user_id),
    )
    row = get_user(user_id)
    if row is not None and row["username"].lower() == "admin":
        db.clear_default_admin_flag()


def change_own_password(user_id: int, old_password: str, new_password: str) -> None:
    row = get_user(user_id)
    if row is None:
        raise AuthError("Kullanıcı bulunamadı.")
    if not security.verify_password(old_password, row["salt"], row["password_hash"]):
        raise AuthError("Mevcut şifre hatalı.")
    change_password(user_id, new_password)


def _active_manager_count() -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM users WHERE role = ? AND is_active = 1",
        (config.ROLE_MANAGER,),
    )
