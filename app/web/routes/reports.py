"""Raporlar: dönem filtresi, dört rapor tablosu ve Excel/CSV dışa aktarımı."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.services import report_service
from app.services.auth_service import CurrentUser
from app.utils import export
from app.utils.helpers import today_local
from app.web import deps

router = APIRouter()

# Hazır dönemler: etiket -> gün sayısı. 0, "özel aralık" demektir.
DONEMLER = (
    ("7", "Son 7 gün", 7),
    ("30", "Son 30 gün", 30),
    ("90", "Son 90 gün", 90),
    ("180", "Son 6 ay", 180),
    ("365", "Son 1 yıl", 365),
    ("ozel", "Özel aralık", 0),
)

GRUPLAR = (("gun", "Gün"), ("hafta", "Hafta"), ("ay", "Ay"))

VARSAYILAN_DONEM = "30"


def _rapor_kullanicisi(request: Request) -> CurrentUser:
    user = deps.zorunlu_kullanici(request)
    if not user.can_view_reports:
        raise deps.YetkiYok("Raporlar teknisyen ve yöneticilere açıktır.")
    return user


def _gun_sayisi(donem: str) -> int:
    for anahtar, _etiket, gun in DONEMLER:
        if anahtar == donem:
            return gun
    return 30


def _gecerli_tarih(deger: str | None) -> str | None:
    """`YYYY-MM-DD` biçiminde değilse yok sayılır (adres çubuğundan gelir)."""
    if not deger:
        return None
    try:
        return date.fromisoformat(deger).isoformat()
    except ValueError:
        return None


def _aralik(request: Request) -> tuple[str, str, str, str]:
    """Sorgu parametrelerinden (dönem, başlangıç, bitiş, gruplama) üretir."""
    q = request.query_params
    donem = q.get("donem") or VARSAYILAN_DONEM
    if donem not in {a for a, _e, _g in DONEMLER}:
        donem = VARSAYILAN_DONEM

    bugun = today_local()
    if donem == "ozel":
        baslangic = _gecerli_tarih(q.get("baslangic"))
        bitis = _gecerli_tarih(q.get("bitis"))
        # Eksik ya da bozuk tarihte son 30 güne düşülür; boş sayfa gösterip
        # kullanıcıyı tarih yazmaya zorlamak yerine anlamlı bir varsayılan.
        if not baslangic or not bitis:
            baslangic = (bugun - timedelta(days=29)).isoformat()
            bitis = bugun.isoformat()
        elif bitis < baslangic:
            baslangic, bitis = bitis, baslangic
        gun = (date.fromisoformat(bitis) - date.fromisoformat(baslangic)).days + 1
    else:
        gun = _gun_sayisi(donem)
        baslangic = (bugun - timedelta(days=gun - 1)).isoformat()
        bitis = bugun.isoformat()

    # Uzun dönemde günlük gruplama okunmaz olur; kullanıcı yine de elle
    # değiştirebilir.
    istenen = q.get("grup")
    if istenen in {a for a, _e in GRUPLAR}:
        grup = istenen
    elif gun >= 180:
        grup = "ay"
    elif gun >= 90:
        grup = "hafta"
    else:
        grup = "gun"

    return donem, baslangic, bitis, grup


@router.get("/raporlar")
def raporlar(request: Request):
    _rapor_kullanicisi(request)
    donem, baslangic, bitis, grup = _aralik(request)

    trend = report_service.trend(baslangic, bitis, grup)
    enbuyuk = max((max(t["opened"], t["closed"]) for t in trend), default=0)
    trend_cubuklari = [
        {
            "etiket": report_service.bucket_label(t["bucket"], grup),
            "acilan": t["opened"],
            "kapanan": t["closed"],
            # Sıfıra bölünmesin: hiç kayıt yoksa çubuklar boş çizilir.
            "acilan_oran": (t["opened"] / enbuyuk * 100) if enbuyuk else 0,
            "kapanan_oran": (t["closed"] / enbuyuk * 100) if enbuyuk else 0,
        }
        for t in trend
    ]

    tablolar = [
        {"anahtar": anahtar, "veri": report_service.dataset(
            anahtar, baslangic, bitis, grup
        )}
        for anahtar in ("makine", "cozum", "personel")
    ]

    return deps.sayfa(
        request,
        "raporlar.html",
        {
            "donemler": DONEMLER,
            "gruplar": GRUPLAR,
            "secili": {
                "donem": donem,
                "baslangic": baslangic,
                "bitis": bitis,
                "grup": grup,
            },
            "durumlar": report_service.status_distribution(baslangic, bitis),
            "ortalama_cozum": report_service.avg_resolution_hours(
                date_from=baslangic, date_to=bitis
            ),
            "trend_cubuklari": trend_cubuklari,
            "tablolar": tablolar,
        },
    )


@router.get("/raporlar/disa-aktar")
def disa_aktar(request: Request):
    _rapor_kullanicisi(request)
    _donem, baslangic, bitis, grup = _aralik(request)

    q = request.query_params
    rapor = q.get("rapor")
    if rapor not in report_service.REPORTS:
        raise HTTPException(status_code=404, detail="Bilinmeyen rapor türü.")
    bicim = "csv" if q.get("bicim") == "csv" else "xlsx"

    _baslik, sutunlar, satirlar = report_service.dataset(
        rapor, baslangic, bitis, grup
    )

    # Dosya diske yazılır ve yanıt gönderildikten sonra silinir: openpyxl ve
    # csv modülü bir yola yazar, bellekte akış üretmezler. Geçici ad benzersiz
    # olmalıdır; aynı raporu aynı anda indiren iki kullanıcı birbirinin
    # dosyasını silmemelidir. İndirilen dosyanın adı ayrıca verilir.
    tanitici, yol = tempfile.mkstemp(prefix="mat-rapor-", suffix="." + bicim)
    os.close(tanitici)
    gecici = Path(yol)
    indirme_adi = f"rapor-{rapor}-{baslangic}-{bitis}.{bicim}"
    try:
        export.export_auto(gecici, sutunlar, satirlar, sheet_title=rapor)
    except export.ExportError as exc:
        gecici.unlink(missing_ok=True)
        # Tek gerçekçi neden: sunucuda openpyxl kurulu değil. Yetki hatası
        # gibi gösterilmemeli, sebebi ekrana yazılmalı.
        return deps.sayfa(
            request,
            "hata.html",
            {"baslik": "Rapor oluşturulamadı", "mesaj": str(exc), "kod": 500},
            durum_kodu=500,
        )

    return FileResponse(
        gecici,
        filename=indirme_adi,
        background=BackgroundTask(gecici.unlink, missing_ok=True),
    )
