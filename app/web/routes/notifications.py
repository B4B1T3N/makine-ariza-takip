"""Uygulama içi bildirimler: liste, okundu işaretleme ve temizleme."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.services import notification_service
from app.web import deps

router = APIRouter()

# Bildirim listesinde gösterilen en fazla kayıt. Eskiler ekranda tutulmaz;
# arıza geçmişi zaten kaydın kendi sayfasındadır.
LISTE_SINIRI = 100


@router.get("/bildirimler")
def liste(request: Request):
    user = deps.zorunlu_kullanici(request)
    okunmamis = request.query_params.get("okunmamis") == "1"

    return deps.sayfa(
        request,
        "bildirimler.html",
        {
            "bildirim_kayitlari": notification_service.list_for_user(
                user.id, unread_only=okunmamis, limit=LISTE_SINIRI
            ),
            "okunmamis_sayisi": notification_service.unread_count(user.id),
            "secili": {"okunmamis": okunmamis},
        },
    )


@router.post("/bildirimler/{notification_id}/okundu")
def okundu(
    request: Request,
    notification_id: int,
    hedef: str = Form(""),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)

    # Sahiplik kontrolü servis katmanındadır: başkasının bildirimi güncellenmez.
    notification_service.mark_read(notification_id, user.id)

    # `hedef` yalnızca arıza numarasıdır; serbest bir adres kabul edilmez ki
    # buradan dış siteye yönlendirme yapılamasın.
    if hedef.isdigit():
        return RedirectResponse("/arizalar/" + hedef, status_code=303)
    return RedirectResponse("/bildirimler", status_code=303)


@router.post("/bildirimler/tumu-okundu")
def tumu_okundu(request: Request, csrf: str = Form("")):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)

    notification_service.mark_all_read(user.id)
    deps.bildir(request, "Tüm bildirimler okundu işaretlendi.", "basari")
    return RedirectResponse("/bildirimler", status_code=303)


@router.post("/bildirimler/temizle")
def temizle(request: Request, csrf: str = Form("")):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)

    notification_service.delete_all(user.id)
    deps.bildir(request, "Bildirimleriniz silindi.", "basari")
    return RedirectResponse("/bildirimler", status_code=303)
