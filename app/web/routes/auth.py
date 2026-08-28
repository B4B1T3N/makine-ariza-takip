"""Giriş ve çıkış."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.db import database as db
from app.services.auth_service import AuthError, login
from app.web import deps

router = APIRouter()


def _guvenli_hedef(devam: str | None) -> str:
    """Açık yönlendirme açığını kapatır.

    `devam` parametresi adres çubuğundan gelir; yalnızca bu sitedeki mutlak
    yollara izin verilir. `//baska-site.com` tarayıcıda protokol-göreli bir
    adres olarak çözülür, bu yüzden ayrıca elenir.
    """
    if not devam or not devam.startswith("/") or devam.startswith("//"):
        return "/panel"
    return devam


@router.get("/giris")
def giris_formu(request: Request, devam: str | None = None):
    if deps.mevcut_kullanici(request) is not None:
        return RedirectResponse(_guvenli_hedef(devam), status_code=303)
    return deps.sayfa(
        request, "giris.html",
        {"devam": devam or "", "varsayilan_admin": db.default_admin_pending()},
    )


@router.post("/giris")
def giris_yap(
    request: Request,
    kullanici_adi: str = Form(""),
    sifre: str = Form(""),
    devam: str = Form(""),
    csrf: str = Form(""),
):
    deps.csrf_dogrula(request, csrf)
    try:
        user = login(kullanici_adi, sifre)
    except AuthError as exc:
        # Girilen kullanıcı adı formda kalsın, şifre kalmasın.
        return deps.sayfa(
            request, "giris.html",
            {
                "hata": str(exc),
                "kullanici_adi": kullanici_adi,
                "devam": devam,
                "varsayilan_admin": db.default_admin_pending(),
            },
            durum_kodu=401,
        )

    deps.oturum_ac(request, user)
    deps.bildir(request, f"Hoş geldiniz, {user.full_name}.", "basari")
    if user.username.lower() == "admin" and db.default_admin_pending():
        deps.bildir(
            request,
            "Varsayılan yönetici şifresi hâlâ 'admin'. Hemen değiştirin.",
            "uyari",
        )
    return RedirectResponse(_guvenli_hedef(devam), status_code=303)


@router.post("/cikis")
def cikis_yap(request: Request, csrf: str = Form("")):
    deps.csrf_dogrula(request, csrf)
    deps.oturum_kapat(request)
    return RedirectResponse("/giris", status_code=303)
