"""Kullanıcı yönetimi (yönetici) ve herkesin kendi şifresini değiştirmesi."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import config
from app.services import auth_service
from app.services.auth_service import CurrentUser
from app.web import deps

router = APIRouter()

# Rol seçiminin yanında gösterilen açıklamalar. Yetki tablosunun kısa hâli:
# yönetici, kime hangi yetkiyi verdiğini formu terk etmeden görebilsin.
ROL_ACIKLAMALARI = {
    config.ROLE_OPERATOR: "Arıza kaydı açar, yalnızca kendi kayıtlarını görür.",
    config.ROLE_TECHNICIAN: "Tüm kayıtları görür, durum günceller ve not ekler.",
    config.ROLE_MANAGER: "Tüm yetkiler: makine envanteri, kullanıcılar ve raporlar.",
}


def _yonetici(request: Request) -> CurrentUser:
    user = deps.zorunlu_kullanici(request)
    if not user.can_manage_users:
        raise deps.YetkiYok("Kullanıcı yönetimi yalnızca yöneticilere açıktır.")
    return user


def _kullanici(user_id: int) -> dict:
    kayit = auth_service.get_user(user_id)
    if kayit is None:
        raise deps.YetkiYok("Kullanıcı bulunamadı.")
    return kayit


# --- Liste ----------------------------------------------------------------
@router.get("/kullanicilar")
def liste(request: Request):
    user = _yonetici(request)
    q = request.query_params

    rol = q.get("rol") if q.get("rol") in config.ROLES else None
    pasifler = q.get("pasifler") == "1"

    return deps.sayfa(
        request,
        "kullanicilar.html",
        {
            "kullanicilar": auth_service.list_users(include_inactive=pasifler, role=rol),
            "secili": {"rol": rol or "", "pasifler": pasifler},
            "ben": user.id,
        },
    )


# --- Yeni kullanıcı -------------------------------------------------------
@router.get("/kullanicilar/yeni")
def yeni_form(request: Request):
    _yonetici(request)
    return deps.sayfa(
        request,
        "kullanici_form.html",
        {"hedef": None, "girilen": {}, "rol_aciklamalari": ROL_ACIKLAMALARI},
    )


@router.post("/kullanicilar/yeni")
def yeni_kaydet(
    request: Request,
    kullanici_adi: str = Form(""),
    ad_soyad: str = Form(""),
    rol: str = Form(config.ROLE_OPERATOR),
    sifre: str = Form(""),
    csrf: str = Form(""),
):
    _yonetici(request)
    deps.csrf_dogrula(request, csrf)

    try:
        auth_service.create_user(
            username=kullanici_adi, password=sifre, full_name=ad_soyad, role=rol
        )
    except auth_service.AuthError as exc:
        return deps.sayfa(
            request,
            "kullanici_form.html",
            {
                "hedef": None,
                "hata": str(exc),
                # Şifre bilerek geri doldurulmaz: hata sayfası tarayıcı
                # geçmişinde kalabilir.
                "girilen": {
                    "username": kullanici_adi,
                    "full_name": ad_soyad,
                    "role": rol,
                },
                "rol_aciklamalari": ROL_ACIKLAMALARI,
            },
            durum_kodu=400,
        )

    deps.bildir(request, ad_soyad.strip() + " kullanıcısı oluşturuldu.", "basari")
    return RedirectResponse("/kullanicilar", status_code=303)


# --- Düzenleme ------------------------------------------------------------
@router.get("/kullanicilar/{user_id}/duzenle")
def duzenle_form(request: Request, user_id: int):
    ben = _yonetici(request)
    hedef = _kullanici(user_id)

    return deps.sayfa(
        request,
        "kullanici_form.html",
        {
            "hedef": hedef,
            "girilen": {
                "username": hedef["username"],
                "full_name": hedef["full_name"],
                "role": hedef["role"],
                "is_active": hedef["is_active"],
            },
            "kendisi": hedef["id"] == ben.id,
            "rol_aciklamalari": ROL_ACIKLAMALARI,
        },
    )


@router.post("/kullanicilar/{user_id}/duzenle")
def duzenle_kaydet(
    request: Request,
    user_id: int,
    ad_soyad: str = Form(""),
    rol: str = Form(config.ROLE_OPERATOR),
    aktif: str = Form(""),
    yeni_sifre: str = Form(""),
    csrf: str = Form(""),
):
    ben = _yonetici(request)
    deps.csrf_dogrula(request, csrf)
    hedef = _kullanici(user_id)

    aktif_mi = aktif == "1"
    hata: str | None = None

    # Kendi hesabını pasife alan yönetici, kaydettiği anda oturumundan düşer
    # ve geri açacak kimse olmayabilir.
    if hedef["id"] == ben.id and not aktif_mi:
        hata = "Kendi hesabınızı pasife alamazsınız."
    else:
        try:
            auth_service.update_user(
                user_id,
                full_name=ad_soyad,
                role=rol,
                is_active=aktif_mi,
                new_password=yeni_sifre or None,
            )
        except auth_service.AuthError as exc:
            hata = str(exc)

    if hata:
        return deps.sayfa(
            request,
            "kullanici_form.html",
            {
                "hedef": hedef,
                "hata": hata,
                "girilen": {
                    "username": hedef["username"],
                    "full_name": ad_soyad,
                    "role": rol,
                    "is_active": aktif_mi,
                },
                "kendisi": hedef["id"] == ben.id,
                "rol_aciklamalari": ROL_ACIKLAMALARI,
            },
            durum_kodu=400,
        )

    if yeni_sifre:
        deps.bildir(request, "Kullanıcı güncellendi ve şifresi sıfırlandı.", "basari")
    else:
        deps.bildir(request, "Kullanıcı güncellendi.", "basari")
    return RedirectResponse("/kullanicilar", status_code=303)


# --- Kendi şifresi --------------------------------------------------------
@router.get("/hesap/sifre")
def sifre_form(request: Request):
    deps.zorunlu_kullanici(request)
    return deps.sayfa(request, "sifre_degistir.html", {})


@router.post("/hesap/sifre")
def sifre_degistir(
    request: Request,
    mevcut_sifre: str = Form(""),
    yeni_sifre: str = Form(""),
    yeni_sifre_tekrar: str = Form(""),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)

    if yeni_sifre != yeni_sifre_tekrar:
        return deps.sayfa(
            request,
            "sifre_degistir.html",
            {"hata": "Yeni şifre iki alanda aynı yazılmadı."},
            durum_kodu=400,
        )

    try:
        auth_service.change_own_password(user.id, mevcut_sifre, yeni_sifre)
    except auth_service.AuthError as exc:
        return deps.sayfa(
            request, "sifre_degistir.html", {"hata": str(exc)}, durum_kodu=400
        )

    deps.bildir(request, "Şifreniz değiştirildi.", "basari")
    return RedirectResponse("/arizalar", status_code=303)
