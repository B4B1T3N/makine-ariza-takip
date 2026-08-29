"""Faz 5: yayın sertleştirmesi — hız sınırı, güvenlik başlıkları, kurulum kontrolü.

Buradaki testler "kod doğru mu"nun yanında "kurulum doğru mu"yu da sorgular:
çerezin güvenli bayrağı, tarayıcıya gönderilen politikalar ve yayın öncesi
kontrol listesi.
"""
from __future__ import annotations

import re

import pytest

from app import config
from app.services import auth_service, health_service


def _csrf(html: str) -> str:
    eslesme = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert eslesme, "Sayfada CSRF etiketi yok"
    return eslesme.group(1)


def _giris_dene(istemci, kullanici_adi: str, sifre: str):
    token = _csrf(istemci.get("/giris").text)
    return istemci.post(
        "/giris",
        data={"kullanici_adi": kullanici_adi, "sifre": sifre, "csrf": token},
        follow_redirects=False,
    )


def _uygulama():
    """O anki ortam değişkenleriyle yeni bir uygulama örneği kurar."""
    from fastapi.testclient import TestClient

    from app.web.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def istemci(app_db):
    return _uygulama()


# --- Giriş hız sınırı -----------------------------------------------------
def test_art_arda_hatali_deneme_girisi_kilitler(istemci, users):
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        yanit = _giris_dene(istemci, "op", "yanlis")
        assert yanit.status_code == 401

    kilitli = _giris_dene(istemci, "op", "yanlis")
    assert kilitli.status_code == 429
    assert "Çok fazla başarısız giriş denemesi" in kilitli.text


def test_kilitliyken_dogru_sifre_de_kabul_edilmez(istemci, users):
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        _giris_dene(istemci, "op", "yanlis")

    yanit = _giris_dene(istemci, "op", "1234")
    assert yanit.status_code == 429
    # Oturum açılmamış olmalı.
    assert istemci.get("/panel", follow_redirects=False).status_code == 303


def test_basarili_giris_sayaci_sifirlar(istemci, users):
    for _ in range(config.LOGIN_MAX_ATTEMPTS - 1):
        _giris_dene(istemci, "op", "yanlis")
    assert auth_service.failed_attempts("op") == config.LOGIN_MAX_ATTEMPTS - 1

    yanit = _giris_dene(istemci, "op", "1234")
    assert yanit.status_code == 303
    assert auth_service.failed_attempts("op") == 0


def test_kilit_olmayan_kullaniciyi_da_kapsar(istemci, app_db):
    """Kilit mesajı hesabın var olup olmadığını ele vermemeli."""
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        _giris_dene(istemci, "hicyok", "deneme")

    yanit = _giris_dene(istemci, "hicyok", "deneme")
    assert yanit.status_code == 429
    assert "Çok fazla başarısız giriş denemesi" in yanit.text


def test_bir_kullanicinin_kilidi_digerini_kilitlemez(istemci, users):
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        _giris_dene(istemci, "op", "yanlis")

    assert _giris_dene(istemci, "tk", "1234").status_code == 303


def test_yonetici_kilidi_elle_acabilir(app_db, users):
    for _ in range(config.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(auth_service.AuthError):
            auth_service.login("op", "yanlis")

    with pytest.raises(auth_service.LoginLocked):
        auth_service.login("op", "1234")

    auth_service.unlock("op")
    assert auth_service.login("op", "1234").username == "op"


def test_masaustu_girisi_adres_vermeden_calisir(app_db, users):
    """Masaüstü arayüz `address` geçmez; imza geriye uyumlu kalmalı."""
    assert auth_service.login("op", "1234").username == "op"


# --- Güvenlik başlıkları --------------------------------------------------
def test_guvenlik_basliklari_her_yanitta(istemci, users):
    yanit = istemci.get("/giris")

    assert "script-src 'self'" in yanit.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in yanit.headers["content-security-policy"]
    assert yanit.headers["x-content-type-options"] == "nosniff"
    assert yanit.headers["x-frame-options"] == "DENY"
    assert yanit.headers["referrer-policy"] == "same-origin"


def test_http_kurulumunda_hsts_gonderilmez(istemci):
    assert "strict-transport-security" not in istemci.get("/giris").headers


def test_https_acikken_hsts_ve_guvenli_cerez(app_db, users, monkeypatch):
    monkeypatch.setenv("MAT_HTTPS", "1")
    istemci = _uygulama()

    assert "strict-transport-security" in istemci.get("/giris").headers

    yanit = _giris_dene(istemci, "op", "1234")
    # Starlette bayrakları küçük harfle yazar; karşılaştırma harf duyarsız.
    cerez = yanit.headers["set-cookie"].lower()
    assert "mat_oturum" in cerez
    assert "secure" in cerez
    assert "httponly" in cerez


def test_sayfalarda_satir_ici_betik_kalmadi(istemci, users, machines):
    """CSP satır içi betiğe izin vermiyor; şablonlar da içermemeli."""
    _giris_dene(istemci, "tk", "1234")

    for yol in ("/panel", "/arizalar", "/makineler", "/bildirimler"):
        icerik = istemci.get(yol).text
        assert "onclick=" not in icerik, yol
        assert "onsubmit=" not in icerik, yol


def test_satir_tiklamasi_veri_ozniteligiyle_tasiniyor(istemci, users, machines):
    _giris_dene(istemci, "tk", "1234")
    assert 'data-adres="/makineler/' in istemci.get("/makineler").text
    assert "/static/etkilesim.js" in istemci.get("/panel").text


# --- Vekil başlıklarına güven --------------------------------------------
def test_vekil_guveni_kapaliyken_iletilen_adres_yok_sayilir(app_db, monkeypatch):
    from starlette.requests import Request

    monkeypatch.delenv("MAT_TRUST_PROXY", raising=False)
    from app.web import deps

    kapsam = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.2.3.4")],
        "client": ("10.0.0.9", 1234),
    }
    istek = Request(kapsam)
    assert deps.istemci_adresi(istek) == "10.0.0.9"

    monkeypatch.setenv("MAT_TRUST_PROXY", "1")
    assert deps.istemci_adresi(istek) == "1.2.3.4"


# --- Kurulum kontrolü -----------------------------------------------------
def test_eksik_oturum_anahtari_hata_olarak_raporlanir(app_db, monkeypatch):
    monkeypatch.delenv("MAT_SECRET_KEY", raising=False)
    bulgular = health_service.yayin_kontrolleri()
    basliklar = [b["baslik"] for b in bulgular if b["seviye"] == health_service.HATA]
    assert any("Oturum anahtarı" in b for b in basliklar)

    monkeypatch.setenv("MAT_SECRET_KEY", "x" * 40)
    bulgular = health_service.yayin_kontrolleri()
    assert not any("Oturum anahtarı" in b["baslik"] for b in bulgular)


def test_https_kapaliysa_hata_acikken_temiz(app_db, monkeypatch):
    monkeypatch.setenv("MAT_HTTPS", "0")
    assert any(
        "HTTPS kapalı" in b["baslik"] for b in health_service.yayin_kontrolleri()
    )

    monkeypatch.setenv("MAT_HTTPS", "1")
    assert not any(
        "HTTPS kapalı" in b["baslik"] for b in health_service.yayin_kontrolleri()
    )


def test_s3_secili_ama_kova_tanimsizsa_hata(app_db, monkeypatch):
    monkeypatch.setenv("MAT_STORAGE", "s3")
    monkeypatch.setenv("MAT_S3_BUCKET", "")

    bulgular = health_service.yayin_kontrolleri()
    assert any("MAT_S3_BUCKET" in b["baslik"] for b in bulgular)


def test_varsayilan_admin_sifresi_hata_uretir(app_db, monkeypatch):
    monkeypatch.setenv("MAT_SECRET_KEY", "x" * 40)
    bulgular = health_service.yayin_kontrolleri()
    assert any("Varsayılan yönetici" in b["baslik"] for b in bulgular)

    auth_service.change_password(
        auth_service.list_users(role=config.ROLE_MANAGER)[0]["id"], "yeni-sifre"
    )
    bulgular = health_service.yayin_kontrolleri()
    assert not any("Varsayılan yönetici" in b["baslik"] for b in bulgular)


def test_ozet_hata_ve_uyariyi_ayirir():
    bulgular = [
        {"seviye": health_service.HATA, "baslik": "a", "cozum": ""},
        {"seviye": health_service.UYARI, "baslik": "b", "cozum": ""},
        {"seviye": health_service.UYARI, "baslik": "c", "cozum": ""},
    ]
    assert health_service.ozet(bulgular) == (1, 2)


def test_kurulum_uyarilari_panelde_yalnizca_yoneticiye_gorunur(istemci, users):
    _giris_dene(istemci, "tk", "1234")
    assert "Kurulum kontrolü" not in istemci.get("/panel").text

    _giris_dene(istemci, "admin", "admin")
    assert "Kurulum kontrolü" in istemci.get("/panel").text
