"""Yayın öncesi kurulum kontrolü (Faz 5).

Kodun değil kurulumun doğruluğunu sorgular: oturum anahtarı tanımlı mı,
HTTPS açık mı, veritabanı adresi üretimi mi gösteriyor, ekler nerede
duruyor, son yedek ne kadar eski.

Kullanım:
    python tools/yayin_kontrol.py

Çıkış kodu 1 ise en az bir **hata** vardır: bu haliyle yayına çıkılmamalıdır.
Dağıtım betiğinizde bu komutu çalıştırıp çıkış kodunu kontrol edebilirsiniz.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.services import health_service, storage_service  # noqa: E402


def main() -> int:
    print("Makine Arıza Takip — yayın kontrolü")
    print("=" * 60)
    print(f"Veritabanı   : {config.database_url_safe()}")
    print(f"Saat dilimi  : {config.APP_TIMEZONE}")
    print(f"Ek depolama  : {config.storage_backend()}", end="")
    if config.storage_backend() == config.STORAGE_S3:
        print(f"  (kova: {config.s3_settings()['bucket'] or '—'})")
    else:
        print(f"  ({config.attachments_dir()})")
    print(f"HTTPS        : {'açık' if config.https_only() else 'kapalı'}")
    print(f"Vekil güveni : {'açık' if config.trust_proxy() else 'kapalı'}")
    print("=" * 60)

    bulgular = health_service.yayin_kontrolleri()
    hatalar, uyarilar = health_service.ozet(bulgular)

    if not bulgular:
        print("Her şey yolunda: hata ve uyarı yok.")
        return 0

    for bulgu in bulgular:
        isaret = "HATA " if bulgu["seviye"] == health_service.HATA else "UYARI"
        print(f"[{isaret}] {bulgu['baslik']}")
        print(f"         → {bulgu['cozum']}")
        print()

    print("-" * 60)
    print(f"{hatalar} hata, {uyarilar} uyarı")

    if hatalar:
        print("\nHatalar giderilmeden yayına çıkmayın.")
        return 1
    print("\nHata yok. Uyarılar bilerek kabul edilmiş olabilir.")
    return 0


if __name__ == "__main__":
    # storage_service içe aktarımı, arka uç seçiminin ortam değişkeniyle
    # gerçekten çözüldüğünü de doğrular.
    storage_service.depoyu_sifirla()
    sys.exit(main())
