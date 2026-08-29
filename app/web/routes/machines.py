"""Makine envanteri: liste, künye, kayıt açma/düzenleme ve pasife alma.

Liste sayfası, tesisin ekipman listesi uygulamasının düzenini izler:
istatistik şeridi, sayaçlı filtre paneli, aktif filtre çipleri, sıralama ve
tablo/kart görünümü. Etkileşimin tamamı **bağlantılarla** yapılır — açılan
her sayfa adres çubuğundan paylaşılabilir ve JavaScript gerektirmez.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.services import fault_service, machine_service
from app.services.auth_service import CurrentUser
from app.web import deps

router = APIRouter()

# Makine detayında gösterilen son arıza sayısı. Tam geçmiş için arıza
# listesine makine filtresiyle bağlanılır.
SON_ARIZA_SAYISI = 20

# Listede gösterilen en fazla kayıt. Envanter birkaç yüz satırdır; sayfalama
# yerine tek tabloda tutmak, referans uygulamadaki gibi tarama ve tarayıcı
# içi aramayı kolaylaştırır.
LISTE_SINIRI = 1000

# Sorgu parametresi -> servis filtresi. Filtre paneli, çipler ve adres
# üretimi hep bu tablodan beslenir.
FILTRE_PARAMLARI = (
    ("bina", "building", "Bina"),
    ("bolum", "location", "Bölüm"),
    ("tip", "category", "Tip"),
    ("konum", "new_location", "Yeni konum"),
    ("uretici", "manufacturer", "Üretici firma"),
)

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


# --- Liste: sorgu durumu --------------------------------------------------
class ListeDurumu:
    """Adres çubuğundaki filtre/sıralama durumu ve ondan üretilen bağlantılar."""

    def __init__(self, request: Request) -> None:
        q = request.query_params
        self.yol = request.url.path

        self.arama = (q.get("ara") or "").strip()
        self.secimler = {
            param: [d for d in q.getlist(param) if d] for param, _s, _e in FILTRE_PARAMLARI
        }
        self.pasifler = q.get("pasifler") == "1"
        self.konumsuz = q.get("konumsuz") == "1"
        self.elektriksiz = q.get("elektriksiz") == "1"
        self.gorunum = "kart" if q.get("gorunum") == "kart" else "tablo"
        self.ters = q.get("yon") == "ters"

        istenen = q.get("sirala")
        self.sirala = (
            istenen if istenen in machine_service.SIRALAMALAR
            else machine_service.VARSAYILAN_SIRALAMA
        )

    # -- servis çağrısı için --
    def filtre(self) -> dict:
        """machine_service'in beklediği filtre sözlüğü."""
        veri = {
            "search": self.arama,
            "include_inactive": self.pasifler,
            "only_unassigned": self.konumsuz,
            "missing_power": self.elektriksiz,
        }
        for param, sutun, _etiket in FILTRE_PARAMLARI:
            secili = self.secimler[param]
            if secili:
                # "—" seçeneği servise olduğu gibi gider; oradaki BOS_DEGER
                # sabiti onu "alanı boş olanlar" koşuluna çevirir.
                veri[sutun] = secili
        return veri

    # -- bağlantı üretimi --
    def parametreler(self) -> list[tuple[str, str]]:
        cift: list[tuple[str, str]] = []
        if self.arama:
            cift.append(("ara", self.arama))
        for param, _s, _e in FILTRE_PARAMLARI:
            cift += [(param, d) for d in self.secimler[param]]
        for ad, acik in (("pasifler", self.pasifler), ("konumsuz", self.konumsuz),
                         ("elektriksiz", self.elektriksiz)):
            if acik:
                cift.append((ad, "1"))
        if self.sirala != machine_service.VARSAYILAN_SIRALAMA:
            cift.append(("sirala", self.sirala))
        if self.ters:
            cift.append(("yon", "ters"))
        if self.gorunum != "tablo":
            cift.append(("gorunum", self.gorunum))
        return cift

    def adres(self, **degisiklik) -> str:
        """Mevcut duruma göre, verilen değişikliklerle yeni adres üretir.

        `ekle=(param, deger)` / `cikar=(param, deger)` çoklu seçim içindir;
        diğer anahtarlar tek değerli durumu değiştirir.
        """
        cift = self.parametreler()

        ekle = degisiklik.get("ekle")
        cikar = degisiklik.get("cikar")
        if ekle:
            cift.append(ekle)
        if cikar:
            cift = [c for c in cift if c != cikar]

        for ad in ("sirala", "gorunum", "ara"):
            if ad in degisiklik:
                cift = [c for c in cift if c[0] != ad]
                if degisiklik[ad]:
                    cift.append((ad, degisiklik[ad]))

        for ad in ("yon", "pasifler", "konumsuz", "elektriksiz"):
            if ad in degisiklik:
                cift = [c for c in cift if c[0] != ad]
                if degisiklik[ad]:
                    cift.append((ad, degisiklik[ad]))

        if degisiklik.get("temizle"):
            cift = [c for c in cift if c[0] in ("gorunum", "sirala", "yon")]

        return self.yol + ("?" + urlencode(cift) if cift else "")


def _filtre_paneli(durum: ListeDurumu) -> list[dict]:
    """Sol paneldeki başlıklar: değerler, sayılar ve aç/kapa bağlantıları."""
    paneller = []
    for param, sutun, etiket in FILTRE_PARAMLARI:
        secili = durum.secimler[param]
        secenekler = []
        for satir in machine_service.facet_counts(sutun, **durum.filtre()):
            deger = satir["deger"]
            isaretli = deger in secili
            secenekler.append({
                "deger": deger,
                "adet": satir["adet"],
                "secili": isaretli,
                "adres": durum.adres(cikar=(param, deger)) if isaretli
                         else durum.adres(ekle=(param, deger)),
            })
        paneller.append({
            "param": param,
            "etiket": etiket,
            "secenekler": secenekler,
            "secili_sayisi": len(secili),
            "temizle_adresi": _panel_temizle(durum, param),
        })
    return paneller


def _panel_temizle(durum: ListeDurumu, param: str) -> str:
    """Bir başlıktaki tüm seçimleri kaldıran adres."""
    cift = [c for c in durum.parametreler() if c[0] != param]
    return durum.yol + ("?" + urlencode(cift) if cift else "")


def _cipler(durum: ListeDurumu) -> list[dict]:
    """Aktif filtreleri gösteren çipler ve kaldırma bağlantıları."""
    cipler = []
    if durum.arama:
        cipler.append({"etiket": "Arama", "deger": durum.arama,
                       "adres": durum.adres(ara="")})
    for param, _sutun, etiket in FILTRE_PARAMLARI:
        for deger in durum.secimler[param]:
            cipler.append({"etiket": etiket, "deger": deger,
                           "adres": durum.adres(cikar=(param, deger))})
    for ad, etiket in (("pasifler", "Pasifler dahil"),
                       ("konumsuz", "Konumu atanmamış"),
                       ("elektriksiz", "Elektrik verisi eksik")):
        if getattr(durum, ad):
            cipler.append({"etiket": "Süzgeç", "deger": etiket,
                           "adres": durum.adres(**{ad: ""})})
    return cipler


# --- Liste ----------------------------------------------------------------
@router.get("/makineler")
def liste(request: Request):
    user = _envanter_kullanicisi(request)
    durum = ListeDurumu(request)
    filtre = durum.filtre()

    makineler = machine_service.list_machines(
        **filtre, sort=durum.sirala, descending=durum.ters, limit=LISTE_SINIRI
    )

    return deps.sayfa(
        request,
        "makineler.html",
        {
            "makineler": makineler,
            "ozet": machine_service.inventory_summary(**filtre),
            "paneller": _filtre_paneli(durum),
            "cipler": _cipler(durum),
            "durum": durum,
            "siralamalar": machine_service.SIRALAMALAR,
            "yonetebilir": user.can_manage_machines,
            "ms": machine_service,
        },
    )


# --- Yeni makine ----------------------------------------------------------
@router.get("/makineler/yeni")
def yeni_form(request: Request):
    _yonetici(request)
    return deps.sayfa(request, "makine_form.html", _form_baglami(None, {}))


@router.post("/makineler/yeni")
async def yeni_kaydet(request: Request):
    _yonetici(request)
    form = await request.form()
    deps.csrf_dogrula(request, form.get("csrf"))

    girilen = _formdan_alanlar(form)
    try:
        machine_id = machine_service.create_machine(**girilen)
    except machine_service.MachineError as exc:
        return deps.sayfa(
            request, "makine_form.html",
            _form_baglami(None, girilen, hata=str(exc)),
            durum_kodu=400,
        )

    deps.bildir(request, girilen["name"].strip() + " envantere eklendi.", "basari")
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
            "kunye_gruplari": machine_service.KUNYE_GRUPLARI,
            "etiketler": machine_service.ALAN_ETIKETLERI,
            "yonetebilir": user.can_manage_machines,
            "ms": machine_service,
        },
    )


# --- Düzenleme ------------------------------------------------------------
@router.get("/makineler/{machine_id}/duzenle")
def duzenle_form(request: Request, machine_id: int):
    _yonetici(request)
    makine = _makine(machine_id)

    girilen = {alan: makine.get(alan) or "" for alan in _FORM_ALANLARI}
    girilen["commissioned_at"] = _tarih(makine["commissioned_at"])
    girilen["manufacture_date"] = _tarih(makine["manufacture_date"])
    return deps.sayfa(request, "makine_form.html", _form_baglami(makine, girilen))


@router.post("/makineler/{machine_id}/duzenle")
async def duzenle_kaydet(request: Request, machine_id: int):
    _yonetici(request)
    form = await request.form()
    deps.csrf_dogrula(request, form.get("csrf"))
    makine = _makine(machine_id)

    girilen = _formdan_alanlar(form)
    try:
        machine_service.update_machine(
            machine_id,
            # Aktiflik bu formdan değil ayrı bir işlemle değişir: pasife alma
            # kuralı (açık arıza varsa engelle) tek yerde kalsın.
            is_active=makine["is_active"],
            **girilen,
        )
    except machine_service.MachineError as exc:
        return deps.sayfa(
            request, "makine_form.html",
            _form_baglami(makine, girilen, hata=str(exc)),
            durum_kodu=400,
        )

    deps.bildir(request, "Makine künyesi güncellendi.", "basari")
    return RedirectResponse("/makineler/" + str(machine_id), status_code=303)


# --- Form yardımcıları ----------------------------------------------------
# Formdaki alanlar sütun adlarıyla aynıdır; böylece form -> servis geçişinde
# ikinci bir eşleme tablosu tutmak gerekmez.
_FORM_ALANLARI = (
    "name", "location", "building", "category", "new_location", "physical_area",
     "machine_code", "asset_no", "model", "definition", "manufacturer",
     "serial_no", "unit_no", "commissioned_at", "production_year",
     "manufacture_date", "voltage", "phase", "amperage", "power_kw",
     "fuse", "cable", "leakage_relay", "pressure_bar",
    "bu_code", "bu_name", "awc_code", "awc_name", "sub_account", "notes",
)


def _formdan_alanlar(form) -> dict:
    return {alan: (form.get(alan) or "").strip() for alan in _FORM_ALANLARI}


def _form_baglami(makine: dict | None, girilen: dict, hata: str | None = None) -> dict:
    return {
        "makine": makine,
        "girilen": girilen,
        "hata": hata,
        "gruplar": machine_service.KUNYE_GRUPLARI,
        "etiketler": machine_service.ALAN_ETIKETLERI,
        "kategoriler": machine_service.list_categories(),
        "konumlar": machine_service.list_locations(),
        "binalar": machine_service.list_buildings(),
    }


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
