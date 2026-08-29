"""Oturum, mevcut kullanıcı, yetki kontrolü ve şablon ortamı.

Oturum bilgisi imzalı bir çerezde taşınır ve **yalnızca kullanıcı kimliğini**
içerir. Rol ve aktiflik her istekte veritabanından okunur; aksi halde pasife
alınan bir kullanıcı, çerezi geçerli olduğu sürece çalışmaya devam ederdi.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import config
from app.db import database as db
from app.services import notification_service
from app.services.auth_service import CurrentUser
from app.utils import helpers

_SESSION_USER_KEY = "kullanici_id"
_SESSION_CSRF_KEY = "csrf"
_SESSION_FLASH_KEY = "bildirimler"

TEMPLATES_DIR = str(Path(__file__).resolve().parent / "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class GirisGerekli(Exception):
    """Oturum yok — tarayıcı giriş sayfasına yönlendirilir."""

    def __init__(self, next_url: str = "/panel") -> None:
        self.next_url = next_url


class YetkiYok(Exception):
    """Kullanıcı giriş yapmış ama bu işlem rolüne kapalı."""

    def __init__(self, mesaj: str = "Bu işlem için yetkiniz yok.") -> None:
        self.mesaj = mesaj


class CsrfHatasi(Exception):
    """Form başka bir siteden gönderilmiş olabilir."""


# --- Oturum ---------------------------------------------------------------
def oturum_ac(request: Request, user: CurrentUser) -> None:
    """Oturumu kullanıcıya bağlar.

    `clear()` önemlidir: giriş anında oturum kimliği tazelenir, böylece
    giriş öncesi ele geçirilmiş bir çerez giriş sonrası geçerli olmaz.
    """
    request.session.clear()
    request.session[_SESSION_USER_KEY] = user.id
    request.session[_SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def oturum_kapat(request: Request) -> None:
    request.session.clear()


def mevcut_kullanici(request: Request) -> CurrentUser | None:
    """Oturumdaki kullanıcıyı veritabanından tazeler; yoksa/pasifse None."""
    user_id = request.session.get(_SESSION_USER_KEY)
    if not user_id:
        return None

    row = db.query_one(
        "SELECT id, username, full_name, role, is_active FROM users WHERE id = %s",
        (user_id,),
    )
    if row is None or not row["is_active"]:
        request.session.clear()
        return None

    return CurrentUser(
        id=row["id"],
        username=row["username"],
        full_name=row["full_name"],
        role=row["role"],
    )


def zorunlu_kullanici(request: Request) -> CurrentUser:
    user = mevcut_kullanici(request)
    if user is None:
        raise GirisGerekli(request.url.path)
    return user


def zorunlu_yonetici(request: Request) -> CurrentUser:
    user = zorunlu_kullanici(request)
    if not user.is_manager:
        raise YetkiYok("Bu sayfa yalnızca yöneticilere açıktır.")
    return user


def istemci_adresi(request: Request) -> str | None:
    """İsteği yapan istemcinin adresi (giriş hız sınırı için).

    Ters vekil arkasında gerçek adres `X-Forwarded-For` başlığındadır; ama
    bu başlığı istemci de gönderebilir. Bu yüzden yalnızca `MAT_TRUST_PROXY`
    açıkken okunur — kapalıyken uydurulmuş bir başlıkla hız sınırı başka
    bir adresin üzerine yıkılabilirdi.
    """
    if config.trust_proxy():
        iletilen = request.headers.get("x-forwarded-for")
        if iletilen:
            return iletilen.split(",")[0].strip() or None
    return request.client.host if request.client else None


# --- CSRF -----------------------------------------------------------------
def csrf_token(request: Request) -> str:
    """Oturuma bağlı form imzası. Yoksa üretilir (giriş formu için gerekir)."""
    token = request.session.get(_SESSION_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_CSRF_KEY] = token
    return token


def csrf_dogrula(request: Request, gonderilen: str | None) -> None:
    beklenen = request.session.get(_SESSION_CSRF_KEY)
    if not beklenen or not gonderilen or not secrets.compare_digest(
        str(beklenen), str(gonderilen)
    ):
        raise CsrfHatasi


# --- Ekran bildirimleri (flash) -------------------------------------------
def bildir(request: Request, mesaj: str, tur: str = "bilgi") -> None:
    """Yönlendirmeden sonra bir kez gösterilecek mesaj bırakır.

    `tur`: bilgi | basari | uyari | hata
    """
    kuyruk = request.session.get(_SESSION_FLASH_KEY, [])
    kuyruk.append({"mesaj": mesaj, "tur": tur})
    request.session[_SESSION_FLASH_KEY] = kuyruk


def bildirimleri_al(request: Request) -> list[dict]:
    return request.session.pop(_SESSION_FLASH_KEY, [])


# --- Şablon oluşturma -----------------------------------------------------
def sayfa(
    request: Request,
    sablon: str,
    baglam: dict[str, Any] | None = None,
    durum_kodu: int = 200,
):
    """Şablonu ortak değişkenlerle birlikte oluşturur."""
    user = mevcut_kullanici(request)
    veri: dict[str, Any] = {
        "request": request,
        "kullanici": user,
        "csrf": csrf_token(request),
        # Yönlendirmeden sonra bir kez gösterilen ekran mesajları. Uygulama
        # içi bildirimlerle karıştırılmamalıdır; onlar `okunmamis` sayısıyla
        # üst menüde durur.
        "bildirimler": bildirimleri_al(request),
        "okunmamis": notification_service.unread_count(user.id) if user else 0,
        "cfg": config,
        "h": helpers,
    }
    veri.update(baglam or {})
    return templates.TemplateResponse(request, sablon, veri, status_code=durum_kodu)
