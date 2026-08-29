"""Arıza listesi, kayıt açma, detay ve detay üzerindeki işlemler."""
from __future__ import annotations

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app import config
from app.services import (
    auth_service,
    fault_service,
    machine_service,
    storage_service,
)
from app.services.auth_service import CurrentUser
from app.web import deps

router = APIRouter()

SAYFA_BOYU = 25


# --- Ortak yardımcılar ----------------------------------------------------
def _coklu(request: Request, ad: str, gecerli: tuple[str, ...]) -> list[str]:
    """Aynı adla birden çok gelen onay kutusu değerlerini okur ve doğrular.

    Bilinmeyen değerler sessizce atılır; filtre parametresi adres çubuğundan
    geldiği için doğrudan sorguya taşınmamalıdır.
    """
    return [d for d in request.query_params.getlist(ad) if d in gecerli]


def _int_ya_da_none(deger: str | None) -> int | None:
    try:
        sayi = int(deger)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return sayi or None


def _gorulebilir_ariza(fault_id: int, user: CurrentUser) -> dict:
    """Kaydı getirir; operatör başkasının kaydını göremez.

    Var olmayan kayıt ile görme yetkisi olmayan kayıt aynı yanıtı verir;
    aksi halde operatör, kayıt numarası deneyerek hangi numaraların var
    olduğunu öğrenebilirdi.
    """
    fault = fault_service.get_fault(fault_id)
    if fault is None:
        raise deps.YetkiYok("Arıza kaydı bulunamadı.")
    if not user.can_view_all_faults and fault["reporter_id"] != user.id:
        raise deps.YetkiYok("Arıza kaydı bulunamadı.")
    return fault


def _duzenleyebilir(fault: dict, user: CurrentUser) -> bool:
    """Teknisyen/yönetici her zaman; kaydı açan yalnızca kayıt hâlâ açıkken."""
    if user.can_change_status:
        return True
    return fault["reporter_id"] == user.id and fault["status"] == config.STATUS_OPEN


def _beklenen_surum(deger: str | None) -> int | None:
    try:
        return int(deger)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- Liste ----------------------------------------------------------------
@router.get("/arizalar")
def liste(request: Request):
    user = deps.zorunlu_kullanici(request)
    q = request.query_params

    arama = (q.get("arama") or "").strip()
    makine_id = _int_ya_da_none(q.get("makine"))
    durumlar = _coklu(request, "durum", config.STATUSES)
    oncelikler = _coklu(request, "oncelik", config.PRIORITIES)
    baslangic = (q.get("baslangic") or "").strip() or None
    bitis = (q.get("bitis") or "").strip() or None
    bana_atanan = q.get("bana_atanan") == "1"
    sayfa_no = max(1, _int_ya_da_none(q.get("sayfa")) or 1)

    # Operatör yalnızca kendi açtığı kayıtları görür — bu kısıt formla değil,
    # sorgunun kendisiyle uygulanır ki adres çubuğundan aşılamasın.
    reporter_id = None if user.can_view_all_faults else user.id
    assignee_id = user.id if (bana_atanan and user.can_view_all_faults) else None

    filtre = dict(
        search=arama,
        machine_id=makine_id,
        statuses=durumlar,
        priorities=oncelikler,
        date_from=baslangic,
        date_to=bitis,
        reporter_id=reporter_id,
        assignee_id=assignee_id,
    )

    toplam = fault_service.count_faults(**filtre)
    son_sayfa = max(1, -(-toplam // SAYFA_BOYU))
    sayfa_no = min(sayfa_no, son_sayfa)
    kayitlar = fault_service.list_faults(
        **filtre, limit=SAYFA_BOYU, offset=(sayfa_no - 1) * SAYFA_BOYU
    )

    return deps.sayfa(
        request,
        "arizalar.html",
        {
            "kayitlar": kayitlar,
            "makineler": machine_service.list_machines(include_inactive=True),
            "toplam": toplam,
            "sayfa_no": sayfa_no,
            "son_sayfa": son_sayfa,
            "secili": {
                "arama": arama,
                "makine": makine_id,
                "durum": durumlar,
                "oncelik": oncelikler,
                "baslangic": baslangic or "",
                "bitis": bitis or "",
                "bana_atanan": bana_atanan,
            },
        },
    )


# --- Yeni kayıt -----------------------------------------------------------
@router.get("/arizalar/yeni")
def yeni_form(request: Request):
    deps.zorunlu_kullanici(request)
    return deps.sayfa(
        request,
        "ariza_yeni.html",
        {"makineler": machine_service.list_machines(), "girilen": {}},
    )


@router.post("/arizalar/yeni")
def yeni_kaydet(
    request: Request,
    makine_id: str = Form(""),
    baslik: str = Form(""),
    aciklama: str = Form(""),
    oncelik: str = Form(config.PRIORITY_MEDIUM),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)

    try:
        fault_id = fault_service.create_fault(
            machine_id=_int_ya_da_none(makine_id),
            title=baslik,
            description=aciklama,
            priority=oncelik,
            reporter_id=user.id,
        )
    except fault_service.FaultError as exc:
        return deps.sayfa(
            request,
            "ariza_yeni.html",
            {
                "hata": str(exc),
                "makineler": machine_service.list_machines(),
                "girilen": {
                    "makine_id": _int_ya_da_none(makine_id),
                    "baslik": baslik,
                    "aciklama": aciklama,
                    "oncelik": oncelik,
                },
            },
            durum_kodu=400,
        )

    deps.bildir(request, str(fault_id) + " numaralı arıza kaydı açıldı.", "basari")
    return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)


# --- Detay ----------------------------------------------------------------
@router.get("/arizalar/{fault_id}")
def detay(request: Request, fault_id: int):
    user = deps.zorunlu_kullanici(request)
    fault = _gorulebilir_ariza(fault_id, user)
    duzenlenebilir = _duzenleyebilir(fault, user)

    return deps.sayfa(
        request,
        "ariza_detay.html",
        {
            "ariza": fault,
            "gecmis": fault_service.get_logs(fault_id),
            "ekler": fault_service.list_attachments(fault_id),
            "gecisler": fault_service.available_transitions(fault["status"]),
            "teknisyenler": auth_service.list_technicians() if user.can_assign else [],
            "makineler": machine_service.list_machines() if duzenlenebilir else [],
            "duzenlenebilir": duzenlenebilir,
        },
    )


@router.post("/arizalar/{fault_id}/durum")
def durum_degistir(
    request: Request,
    fault_id: int,
    yeni_durum: str = Form(""),
    aciklama: str = Form(""),
    surum: str = Form(""),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)
    _gorulebilir_ariza(fault_id, user)
    if not user.can_change_status:
        raise deps.YetkiYok("Durum değiştirme yetkisi teknisyen ve yöneticilere aittir.")

    try:
        fault_service.change_status(
            fault_id,
            user.id,
            yeni_durum,
            aciklama,
            expected_version=_beklenen_surum(surum),
        )
        etiket = config.STATUS_LABELS.get(yeni_durum, yeni_durum)
        deps.bildir(request, "Durum '" + etiket + "' olarak güncellendi.", "basari")
    except fault_service.FaultError as exc:
        deps.bildir(request, str(exc), "hata")

    return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)


@router.post("/arizalar/{fault_id}/not")
def not_ekle(
    request: Request,
    fault_id: int,
    notu: str = Form(""),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)
    _gorulebilir_ariza(fault_id, user)

    try:
        fault_service.add_note(fault_id, user.id, notu)
        deps.bildir(request, "Not eklendi.", "basari")
    except fault_service.FaultError as exc:
        deps.bildir(request, str(exc), "hata")

    return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)


@router.post("/arizalar/{fault_id}/atama")
def atama_yap(
    request: Request,
    fault_id: int,
    teknisyen_id: str = Form(""),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)
    _gorulebilir_ariza(fault_id, user)
    if not user.can_assign:
        raise deps.YetkiYok("Atama yetkisi teknisyen ve yöneticilere aittir.")

    try:
        fault_service.assign(fault_id, user.id, _int_ya_da_none(teknisyen_id))
        deps.bildir(request, "Atama güncellendi.", "basari")
    except fault_service.FaultError as exc:
        deps.bildir(request, str(exc), "hata")

    return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)


@router.post("/arizalar/{fault_id}/duzenle")
def duzenle(
    request: Request,
    fault_id: int,
    makine_id: str = Form(""),
    baslik: str = Form(""),
    aciklama: str = Form(""),
    oncelik: str = Form(config.PRIORITY_MEDIUM),
    surum: str = Form(""),
    csrf: str = Form(""),
):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)
    fault = _gorulebilir_ariza(fault_id, user)
    if not _duzenleyebilir(fault, user):
        raise deps.YetkiYok(
            "Kayıt işleme alındıktan sonra yalnızca teknisyen ve yönetici düzenleyebilir."
        )

    try:
        fault_service.update_fault(
            fault_id,
            user.id,
            machine_id=_int_ya_da_none(makine_id) or fault["machine_id"],
            title=baslik,
            description=aciklama,
            priority=oncelik,
            expected_version=_beklenen_surum(surum),
        )
        deps.bildir(request, "Kayıt güncellendi.", "basari")
    except fault_service.FaultError as exc:
        deps.bildir(request, str(exc), "hata")

    return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)


# --- Ekler ----------------------------------------------------------------
# Dosyanın nerede durduğunu servis katmanı bilir (yerel disk ya da nesne
# depolama); buradaki kod yalnızca yetkiyi ve HTTP tarafını üstlenir.
@router.post("/arizalar/{fault_id}/ek")
async def ek_yukle(request: Request, fault_id: int):
    user = deps.zorunlu_kullanici(request)
    form = await request.form()
    deps.csrf_dogrula(request, form.get("csrf"))
    _gorulebilir_ariza(fault_id, user)

    dosyalar = [d for d in form.getlist("dosya") if hasattr(d, "filename") and d.filename]
    if not dosyalar:
        deps.bildir(request, "Dosya seçilmedi.", "uyari")
        return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)

    eklenen, hatalar = 0, []
    for dosya in dosyalar:
        # Boyut, baytlar okunduktan sonra servis katmanında da denetlenir;
        # burada okumayı sınırlamak, 20 MB'lık sınırın belleğe alınacak
        # veriyi de sınırlaması içindir.
        veri = await dosya.read(config.ATTACHMENT_MAX_BYTES + 1)
        try:
            fault_service.add_attachment_bytes(
                fault_id, user.id, dosya.filename, veri
            )
            eklenen += 1
        except fault_service.FaultError as exc:
            hatalar.append(f"{dosya.filename}: {exc}")

    if eklenen:
        deps.bildir(request, f"{eklenen} dosya eklendi.", "basari")
    for mesaj in hatalar:
        deps.bildir(request, mesaj, "hata")

    return RedirectResponse("/arizalar/" + str(fault_id), status_code=303)


@router.get("/ekler/{attachment_id}")
def ek_indir(request: Request, attachment_id: int):
    user = deps.zorunlu_kullanici(request)

    ek = fault_service.get_attachment(attachment_id)
    if ek is None:
        raise deps.YetkiYok("Dosya bulunamadı.")
    # Dosyaya erişim, bağlı olduğu arıza kaydının görünürlüğüne tabidir.
    _gorulebilir_ariza(ek["fault_id"], user)

    yerel = storage_service.yerel_yol(ek["stored_name"])
    if yerel is not None:
        if not yerel.is_file():
            raise deps.YetkiYok("Dosya sunucuda bulunamadı.")
        return FileResponse(yerel, filename=ek["file_name"])

    # Nesne depolamadaki dosya sunucudan geçirilerek verilir. İmzalı doğrudan
    # bağlantı daha ucuz olurdu ama o zaman yetki kontrolü depoya taşınırdı;
    # kaydı görme yetkisi burada, tek yerde kalsın.
    try:
        veri = fault_service.attachment_bytes(attachment_id)
    except fault_service.FaultError as exc:
        raise deps.YetkiYok(str(exc)) from exc

    return Response(
        veri,
        media_type=mimetypes.guess_type(ek["file_name"])[0]
        or "application/octet-stream",
        headers={
            "Content-Disposition":
                f'attachment; filename="{quote(ek["file_name"])}"'
        },
    )


@router.post("/ekler/{attachment_id}/sil")
def ek_sil(request: Request, attachment_id: int, csrf: str = Form("")):
    user = deps.zorunlu_kullanici(request)
    deps.csrf_dogrula(request, csrf)

    ek = fault_service.get_attachment(attachment_id)
    if ek is None:
        raise deps.YetkiYok("Dosya bulunamadı.")
    fault = _gorulebilir_ariza(ek["fault_id"], user)

    # Yükleyen kişi kendi dosyasını, teknisyen ve yönetici her dosyayı siler.
    if not user.can_change_status and ek["uploaded_by"] != user.id:
        raise deps.YetkiYok("Bu dosyayı yalnızca yükleyen kişi silebilir.")

    fault_service.delete_attachment(attachment_id)
    deps.bildir(request, "Dosya silindi.", "basari")
    return RedirectResponse("/arizalar/" + str(fault["id"]), status_code=303)
