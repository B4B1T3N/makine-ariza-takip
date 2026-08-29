"""Panel (dashboard): rolüne göre değişen durum özeti.

Grafikler sunucuda üretilir: her çubuk, en büyük değere oranlanmış bir
genişlik yüzdesidir. Grafik kütüphanesi eklenmedi — atölye tabletinde sayfanın
hızlı açılması, npm ve derleme adımı olmaması Faz 2'de verilmiş bir karardır.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app import config
from app.services import fault_service, health_service, report_service
from app.web import deps

router = APIRouter()

# Paneldeki kayıt listesinin uzunluğu. Tam liste arıza sayfasındadır.
LISTE_BOYU = 10


def _cubuklar(etiketler: dict[str, str], sayilar: dict[str, int],
              renkler: dict[str, str]) -> list[dict]:
    """Dağılım sözlüğünü, şablonun çizeceği çubuk listesine çevirir."""
    enbuyuk = max(sayilar.values()) if sayilar else 0
    return [
        {
            "etiket": etiketler[anahtar],
            "deger": deger,
            "renk": renkler[anahtar],
            # Sıfıra bölmeyi önler; tüm değerler sıfırken çubuklar boş çizilir.
            "oran": (deger / enbuyuk * 100) if enbuyuk else 0,
        }
        for anahtar, deger in sayilar.items()
    ]


@router.get("/panel")
def panel(request: Request):
    user = deps.zorunlu_kullanici(request)

    # Operatör tesis geneli sayıları görmez: yetkisi kendi kayıtlarıyla
    # sınırlıdır ve panel bu kısıtın etrafından dolaşan bir yol olmamalıdır.
    if user.is_operator:
        return deps.sayfa(
            request,
            "panel.html",
            {
                "kisisel": True,
                "ozet": {
                    "acik": fault_service.count_faults(
                        reporter_id=user.id, statuses=list(config.ACTIVE_STATUSES)
                    ),
                    "cozulen": fault_service.count_faults(
                        reporter_id=user.id,
                        statuses=[config.STATUS_RESOLVED, config.STATUS_CLOSED],
                    ),
                    "toplam": fault_service.count_faults(reporter_id=user.id),
                },
                "liste_basligi": "Açtığım son kayıtlar",
                "kayitlar": fault_service.list_faults(
                    reporter_id=user.id, limit=LISTE_BOYU
                ),
            },
        )

    # Teknisyene önce kendi üzerindeki işler gösterilir; üzerinde iş yoksa
    # boş bir tablo yerine tesisin öncelikli açık kayıtları listelenir.
    kayitlar = []
    liste_basligi = "Bana atanan açık kayıtlar"
    if user.is_technician:
        kayitlar = fault_service.list_faults(
            assignee_id=user.id, only_active=True, limit=LISTE_BOYU
        )
    if not kayitlar:
        liste_basligi = "Öncelikli açık kayıtlar"
        kayitlar = fault_service.list_faults(only_active=True, limit=LISTE_BOYU)

    return deps.sayfa(
        request,
        "panel.html",
        {
            "kisisel": False,
            "ozet": report_service.summary(),
            "durum_cubuklari": _cubuklar(
                config.STATUS_LABELS,
                report_service.status_distribution(),
                config.STATUS_COLORS,
            ),
            "oncelik_cubuklari": _cubuklar(
                config.PRIORITY_LABELS,
                report_service.priority_distribution(),
                config.PRIORITY_COLORS,
            ),
            "en_cok_arizalanan": report_service.top_machines(limit=5),
            "liste_basligi": liste_basligi,
            "kayitlar": kayitlar,
            # Kurulum uyarıları yalnızca yöneticiye gösterilir: düzeltecek
            # olan odur ve içerikleri kurulumun zayıf noktalarını anlatır.
            "yayin_bulgulari": (
                health_service.yayin_kontrolleri() if user.is_manager else []
            ),
        },
    )
