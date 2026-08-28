"""Makine envanteri: liste, künye, kayıt açma/düzenleme ve pasife alma."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.services import fault_service, machine_service
from app.services.auth_service import CurrentUser
from app.web import deps

router = APIRouter()

# Makine detayında gösterilen son arıza sayısı. Tam geçmiş için arıza
# listesine makine filtresiyle bağlanılır.
SON_ARIZA_SAYISI = 20


def _envanter_kullanicisi(request: Request) -> CurrentUser:
    """Envanteri görebilen kullanıcı: teknisyen ve yönetici.

    Operatörün ekranında envanter sekmesi hiç oluşturulmaz; burada da
    adres çubuğundan girilmesine karşı aynı kısıt uygulanır.
    """
    user = deps.zorunlu_kullanici(request)
    if user.is_operator:
        raise deps.YetkiYok("Makine envanteri teknisyen ve yöneticilere açıktır.")
    return user


def _yonetici(request: Request) -> CurrentUser:
    user = _envanter_kullanicisi(request)
    if not user.can_manage_machines:
        raise deps.YetkiYok("Makine envanterini yalnızca yöneticiler değiştirebilir.")
    return user


def _makine(machine_id: int) -> dict:
    makine = machine_service.get_machine(machine_id)
    if makine is None:
        raise deps.YetkiYok("Makine bulunamadı.")
    return makine


def _tarih(deger) -> str:
    """Tarih alanını `<input type=date>` biçimine getirir."""
    if not deger:
        return ""
    return deger.isoformat() if hasattr(deger, "isoformat") else str(deger)


def _form_verisi(
    ad: str, seri_no: str, konum: str, kategori: str, devreye: str, notlar: str
) -> dict:
    return {
        "name": ad,
        "serial_no": seri_no,
        "location": konum,
        "category": kategori,
        "commissioned_at": devreye,
        "notes": notlar,
    }


# --- Liste ----------------------------------------------------------------
@router.get("/makineler")
def liste(request: Request):
    user = _envanter_kullanicisi(request)
    q = request.query_params

    arama = (q.get("arama") or "").strip()
    kategori = (q.get("kategori") or "").strip() or None
    pasifler = q.get("pasifler") == "1"

    makineler = machine_service.list_machines(
        search=arama, include_inactive=pasifler, category=kategori
    )

    return deps.sayfa(
        request,
        "makineler.html",
        {
            "makineler": makineler,
            "kategoriler": machine_service.list_categories(),
            "yonetebilir": user.can_manage_machines,
            "secili": {
                "arama": arama,
                "kategori": kategori or "",
                "pasifler": pasifler,
            },
        },
    )


# --- Yeni makine ----------------------------------------------------------
@router.get("/makineler/yeni")
def yeni_form(request: Request):
    _yonetici(request)
    return deps.sayfa(
        request,
        "makine_form.html",
        {
            "makine": None,
            "girilen": {},
            "kategoriler": machine_service.list_categories(),
            "konumlar": machine_service.list_locations(),
        },
    )


@router.post("/makineler/yeni")
def yeni_kaydet(
    request: Request,
    ad: str = Form(""),
    seri_no: str = Form(""),
    konum: str = Form(""),
    kategori: str = Form(""),
    devreye_alma: str = Form(""),
    notlar: str = Form(""),
    csrf: str = Form(""),
):
    _yonetici(request)
    deps.csrf_dogrula(request, csrf)

    try:
        machine_id = machine_service.create_machine(
            name=ad,
            serial_no=seri_no,
            location=konum,
            category=kategori,
            commissioned_at=devreye_alma or None,
            notes=notlar,
        )
    except machine_service.MachineError as exc:
        return deps.sayfa(
            request,
            "makine_form.html",
            {
                "makine": None,
                "hata": str(exc),
                "girilen": _form_verisi(
                    ad, seri_no, konum, kategori, devreye_alma, notlar
                ),
                "kategoriler": machine_service.list_categories(),
                "konumlar": machine_service.list_locations(),
            },
            durum_kodu=400,
        )

    deps.bildir(request, ad.strip() + " envantere eklendi.", "basari")
    return RedirectResponse("/makineler/" + str(machine_id), status_code=303)


# --- Detay ----------------------------------------------------------------
@router.get("/makineler/{machine_id}")
def detay(request: Request, machine_id: int):
    user = _envanter_kullanicisi(request)
    makine = _makine(machine_id)

    return deps.sayfa(
        request,
        "makine_detay.html",
        {
            "makine": makine,
            "istatistik": machine_service.machine_stats(machine_id),
            "arizalar": fault_service.list_faults(
                machine_id=machine_id, limit=SON_ARIZA_SAYISI
            ),
            "yonetebilir": user.can_manage_machines,
        },
    )


# --- Düzenleme ------------------------------------------------------------
@router.get("/makineler/{machine_id}/duzenle")
def duzenle_form(request: Request, machine_id: int):
    _yonetici(request)
    makine = _makine(machine_id)

    return deps.sayfa(
        request,
        "makine_form.html",
        {
            "makine": makine,
            "girilen": {
                "name": makine["name"],
                "serial_no": makine["serial_no"] or "",
                "location": makine["location"] or "",
                "category": makine["category"] or "",
                "commissioned_at": _tarih(makine["commissioned_at"]),
                "notes": makine["notes"] or "",
            },
            "kategoriler": machine_service.list_categories(),
            "konumlar": machine_service.list_locations(),
        },
    )


@router.post("/makineler/{machine_id}/duzenle")
def duzenle_kaydet(
    request: Request,
    machine_id: int,
    ad: str = Form(""),
    seri_no: str = Form(""),
    konum: str = Form(""),
    kategori: str = Form(""),
    devreye_alma: str = Form(""),
    notlar: str = Form(""),
    csrf: str = Form(""),
):
    _yonetici(request)
    deps.csrf_dogrula(request, csrf)
    makine = _makine(machine_id)

    try:
        machine_service.update_machine(
            machine_id,
            name=ad,
            serial_no=seri_no,
            location=konum,
            category=kategori,
            commissioned_at=devreye_alma or None,
            notes=notlar,
            # Aktiflik bu formdan değil ayrı bir işlemle değişir: pasife alma
            # kuralı (açık arıza varsa engelle) tek yerde kalsın.
            is_active=makine["is_active"],
        )
    except machine_service.MachineError as exc:
        return deps.sayfa(
            request,
            "makine_form.html",
            {
                "makine": makine,
                "hata": str(exc),
                "girilen": _form_verisi(
                    ad, seri_no, konum, kategori, devreye_alma, notlar
                ),
                "kategoriler": machine_service.list_categories(),
                "konumlar": machine_service.list_locations(),
            },
            durum_kodu=400,
        )

    deps.bildir(request, "Makine künyesi güncellendi.", "basari")
    return RedirectResponse("/makineler/" + str(machine_id), status_code=303)


# --- Aktiflik -------------------------------------------------------------
# Makineler silinmez: üzerlerindeki arıza geçmişi korunmalıdır. Kullanımdan
# kalkan makine pasife alınır ve yeni arıza kaydında listelenmez.
@router.post("/makineler/{machine_id}/aktiflik")
def aktiflik_degistir(
    request: Request,
    machine_id: int,
    aktif: str = Form(""),
    csrf: str = Form(""),
):
    _yonetici(request)
    deps.csrf_dogrula(request, csrf)
    _makine(machine_id)

    hedef = aktif == "1"
    try:
        machine_service.set_active(machine_id, hedef)
        deps.bildir(
            request,
            "Makine yeniden kullanıma alındı." if hedef else "Makine pasife alındı.",
            "basari",
        )
    except machine_service.MachineError as exc:
        deps.bildir(request, str(exc), "hata")

    return RedirectResponse("/makineler/" + str(machine_id), status_code=303)
