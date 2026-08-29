"""Yayın öncesi ve yayın sırasındaki kurulum kontrolleri (Faz 5).

Bu kontroller kodun doğruluğunu değil **kurulumun** doğruluğunu sorgular:
anahtar tanımlı mı, bağlantı şifreli mi, yedek güncel mi. Aynı liste üç
yerde kullanılır — sunucu açılışında günlüğe, yöneticinin panelinde uyarı
kartına ve `tools/yayin_kontrol.py` çıktısına.

Seviyeler:
  hata  — üretimde bu haliyle yayına çıkılmamalı
  uyari — çalışır ama bilerek kabul edilmiş bir risktir
"""
from __future__ import annotations

import importlib.util
import os

from app import config
from app.db import database as db
from app.services import backup_service

HATA = "hata"
UYARI = "uyari"


def _bulgu(seviye: str, baslik: str, cozum: str) -> dict:
    return {"seviye": seviye, "baslik": baslik, "cozum": cozum}


def yayin_kontrolleri(veritabani_ile: bool = True) -> list[dict]:
    """Kurulumdaki eksikleri listeler. Boş liste: her şey yolunda."""
    bulgular: list[dict] = []

    if not os.environ.get("MAT_SECRET_KEY"):
        bulgular.append(_bulgu(
            HATA,
            "Oturum anahtarı ortam değişkeninde tanımlı değil",
            "MAT_SECRET_KEY tanımlayın. Aksi halde anahtar veritabanına "
            "yazılır ve yedeklerin içinde dolaşır.",
        ))

    if not config.https_only():
        bulgular.append(_bulgu(
            HATA,
            "HTTPS kapalı: oturum çerezi düz bağlantıda da gönderiliyor",
            "Uygulamayı TLS sonlandıran bir vekilin arkasına alıp "
            "MAT_HTTPS=1 tanımlayın.",
        ))

    if config.database_url() == config.DEFAULT_DATABASE_URL:
        bulgular.append(_bulgu(
            HATA,
            "Veritabanı adresi geliştirme varsayılanında",
            "DATABASE_URL'i üretim veritabanına çevirin.",
        ))
    elif "sslmode=" not in config.database_url() and "localhost" not in (
        config.database_url()
    ):
        bulgular.append(_bulgu(
            UYARI,
            "Veritabanı bağlantısında sslmode belirtilmemiş",
            "Uzak veritabanına bağlanırken DATABASE_URL sonuna "
            "?sslmode=require ekleyin.",
        ))

    if config.storage_backend() == config.STORAGE_S3:
        ayarlar = config.s3_settings()
        if not ayarlar["bucket"]:
            bulgular.append(_bulgu(
                HATA, "MAT_STORAGE=s3 ama MAT_S3_BUCKET tanımsız",
                "Kova adını tanımlayın; aksi halde ek dosyaları yüklenemez.",
            ))
        if importlib.util.find_spec("boto3") is None:
            bulgular.append(_bulgu(
                HATA, "Nesne depolama seçili ama boto3 kurulu değil",
                "pip install boto3",
            ))
    else:
        bulgular.append(_bulgu(
            UYARI,
            "Ek dosyaları sunucunun yerel diskinde",
            "Birden fazla uygulama örneği çalışacaksa MAT_STORAGE=s3 "
            "kullanın; yerel diski örnekler paylaşmaz.",
        ))

    bulgular.extend(_yedek_kontrolu())

    if veritabani_ile:
        bulgular.extend(_veritabani_kontrolleri())

    return bulgular


def _yedek_kontrolu() -> list[dict]:
    yas = backup_service.last_backup_age_days()
    if yas is None:
        return [_bulgu(
            UYARI, "Hiç yedek alınmamış",
            "python tools/backup_now.py --force ile ilk yedeği alın ve "
            "haftalık zamanlanmış görevi kurun.",
        )]
    if yas > config.BACKUP_WARN_DAYS:
        return [_bulgu(
            UYARI, f"Son yedek {yas:.0f} gün önce alınmış",
            "Zamanlanmış görev çalışmıyor olabilir; "
            "python tools/backup_now.py --durum ile bakın.",
        )]
    return []


def _veritabani_kontrolleri() -> list[dict]:
    """Veritabanına dokunan kontroller; şema kurulu değilse atlanır."""
    try:
        varsayilan_admin = db.default_admin_pending()
    except Exception:
        return []

    bulgular = []
    if varsayilan_admin:
        bulgular.append(_bulgu(
            HATA, "Varsayılan yönetici şifresi hâlâ 'admin'",
            "admin ile girip Şifre sayfasından değiştirin.",
        ))
    return bulgular


def ozet(bulgular: list[dict]) -> tuple[int, int]:
    """(hata sayısı, uyarı sayısı)"""
    hatalar = sum(1 for b in bulgular if b["seviye"] == HATA)
    return hatalar, len(bulgular) - hatalar
