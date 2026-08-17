"""Kimlik doğrulama, roller ve kullanıcı yönetimi testleri."""
from __future__ import annotations

import pytest

from app import config
from app.services import auth_service
from app.services.auth_service import AuthError


def test_varsayilan_admin_olusur(app_db):
    assert app_db.default_admin_pending()
    user = auth_service.login("admin", "admin")
    assert user.role == config.ROLE_MANAGER


def test_hatali_giris_reddedilir(app_db):
    with pytest.raises(AuthError):
        auth_service.login("admin", "yanlis")
    with pytest.raises(AuthError):
        auth_service.login("olmayan", "admin")
    with pytest.raises(AuthError):
        auth_service.login("", "")


def test_pasif_kullanici_giris_yapamaz(users):
    operator = users["operator"]
    auth_service.update_user(operator.id, operator.full_name, operator.role, is_active=False)
    with pytest.raises(AuthError, match="pasif"):
        auth_service.login("op", "1234")


def test_tekrarli_kullanici_adi_reddedilir(users):
    with pytest.raises(AuthError, match="zaten kayıtlı"):
        auth_service.create_user("op", "1234", "Başkası", config.ROLE_OPERATOR)


def test_kisa_sifre_reddedilir(app_db):
    with pytest.raises(AuthError, match="en az 4"):
        auth_service.create_user("yeni", "12", "Ad Soyad", config.ROLE_OPERATOR)


def test_rol_yetkileri(users):
    operator, technician, manager = (
        users["operator"], users["technician"], users["admin"]
    )

    assert operator.is_operator
    assert not operator.can_change_status
    assert not operator.can_manage_machines
    assert not operator.can_view_all_faults

    assert technician.can_change_status
    assert technician.can_assign
    assert technician.can_view_reports
    assert not technician.can_manage_users

    assert manager.can_manage_users
    assert manager.can_manage_machines
    assert manager.can_view_reports


def test_son_yonetici_korunur(users):
    with pytest.raises(AuthError, match="en az bir aktif yönetici"):
        auth_service.update_user(
            users["admin"].id, "Sistem", config.ROLE_OPERATOR, is_active=True
        )


def test_ikinci_yonetici_varsa_rol_dusurulebilir(users):
    ikinci = auth_service.create_user("md2", "1234", "İkinci Müdür", config.ROLE_MANAGER)
    auth_service.update_user(ikinci, "İkinci Müdür", config.ROLE_TECHNICIAN, True)
    assert auth_service.get_user(ikinci)["role"] == config.ROLE_TECHNICIAN


def test_sifre_degistirme(users, app_db):
    operator = users["operator"]
    auth_service.change_own_password(operator.id, "1234", "yeni1234")

    auth_service.login("op", "yeni1234")
    with pytest.raises(AuthError):
        auth_service.login("op", "1234")
    with pytest.raises(AuthError, match="Mevcut şifre"):
        auth_service.change_own_password(operator.id, "yanlis", "baska123")


def test_admin_sifresi_degisince_uyari_kalkar(users, app_db):
    assert app_db.default_admin_pending()
    auth_service.change_password(users["admin"].id, "guclu-sifre")
    assert not app_db.default_admin_pending()


def test_sifre_hashlenerek_saklanir(users):
    row = auth_service.get_user(users["operator"].id)
    assert row["password_hash"] != "1234"
    assert len(row["salt"]) == 32
    assert len(row["password_hash"]) == 64
