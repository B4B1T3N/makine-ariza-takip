"""Ek dosyalarının saklandığı yer: yerel disk veya S3 uyumlu nesne depolama.

Neden bir katman: Faz 4'e kadar dosyalar sunucunun diskindeydi. Birden fazla
uygulama örneği çalıştığında ya da sunucu yeniden kurulduğunda o disk ortak
değildir — bir örneğin yazdığı dosyayı diğeri göremez. Nesne depolama bunu
çözer, ama tek sunucuda çalışan küçük bir kurulumu S3 zorunluluğuna
sokmak da gereksizdir. Bu yüzden iki arka uç vardır ve seçim
`MAT_STORAGE` ortam değişkeniyle yapılır (varsayılan: yerel).

Arka uçların sözleşmesi aynıdır: anahtar (`stored_name`) verilir, baytlar
yazılır/okunur/silinir. `fault_service` bunun ötesini bilmez.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from app import config


class StorageError(Exception):
    """Depolama hatası (kullanıcıya gösterilebilir mesaj)."""


# --- Yerel disk -----------------------------------------------------------
class YerelDepo:
    """Dosyaları `MAT_DATA_DIR/ekler` altında tutar."""

    ad = config.STORAGE_LOCAL

    def _yol(self, anahtar: str) -> Path:
        return config.attachments_dir() / anahtar

    def yaz(self, anahtar: str, veri: bytes) -> None:
        try:
            self._yol(anahtar).write_bytes(veri)
        except OSError as exc:
            raise StorageError(f"Dosya diske yazılamadı: {exc}") from exc

    def oku(self, anahtar: str) -> bytes:
        try:
            return self._yol(anahtar).read_bytes()
        except OSError as exc:
            raise StorageError("Dosya sunucuda bulunamadı.") from exc

    def akis(self, anahtar: str) -> BinaryIO:
        try:
            return open(self._yol(anahtar), "rb")
        except OSError as exc:
            raise StorageError("Dosya sunucuda bulunamadı.") from exc

    def sil(self, anahtar: str) -> None:
        try:
            self._yol(anahtar).unlink(missing_ok=True)
        except OSError:
            # Dosya kilitliyse veritabanı kaydı yine de silinsin; yetim
            # dosya, görünürde duran ama açılamayan ekten iyidir.
            pass

    def var_mi(self, anahtar: str) -> bool:
        return self._yol(anahtar).is_file()

    def yerel_yol(self, anahtar: str) -> Path | None:
        return self._yol(anahtar)


# --- S3 uyumlu nesne depolama --------------------------------------------
class S3Depo:
    """AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces — hepsi aynı API.

    `boto3` yalnızca bu arka uç seçildiğinde içe aktarılır; yerel kurulumda
    ek bir bağımlılık gerekmez.
    """

    ad = config.STORAGE_S3

    def __init__(self, ayarlar: dict | None = None, istemci=None) -> None:
        self.ayarlar = ayarlar or config.s3_settings()
        if not self.ayarlar.get("bucket"):
            raise StorageError(
                "MAT_STORAGE=s3 seçildi ama MAT_S3_BUCKET tanımlı değil."
            )
        self._istemci = istemci

    # Testler buraya sahte bir istemci geçirebilsin diye ayrı durur.
    def istemci(self):
        if self._istemci is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover
                raise StorageError(
                    "Nesne depolama için 'boto3' paketi gerekli.\n"
                    "Kurulum: pip install boto3"
                ) from exc

            self._istemci = boto3.client(
                "s3",
                endpoint_url=self.ayarlar["endpoint"],
                region_name=self.ayarlar["region"],
                aws_access_key_id=self.ayarlar["access_key"],
                aws_secret_access_key=self.ayarlar["secret_key"],
            )
        return self._istemci

    def _anahtar(self, anahtar: str) -> str:
        onek = self.ayarlar.get("prefix") or ""
        return f"{onek}/{anahtar}" if onek else anahtar

    def yaz(self, anahtar: str, veri: bytes) -> None:
        try:
            self.istemci().put_object(
                Bucket=self.ayarlar["bucket"], Key=self._anahtar(anahtar), Body=veri
            )
        except Exception as exc:  # boto3 istisnaları sağlayıcıya göre değişir
            raise StorageError(f"Dosya nesne depolamaya yazılamadı: {exc}") from exc

    def oku(self, anahtar: str) -> bytes:
        try:
            yanit = self.istemci().get_object(
                Bucket=self.ayarlar["bucket"], Key=self._anahtar(anahtar)
            )
            return yanit["Body"].read()
        except Exception as exc:
            raise StorageError("Dosya nesne depolamada bulunamadı.") from exc

    def akis(self, anahtar: str) -> BinaryIO:
        import io

        return io.BytesIO(self.oku(anahtar))

    def sil(self, anahtar: str) -> None:
        try:
            self.istemci().delete_object(
                Bucket=self.ayarlar["bucket"], Key=self._anahtar(anahtar)
            )
        except Exception:
            pass  # Yerel arka uçtaki gerekçenin aynısı.

    def var_mi(self, anahtar: str) -> bool:
        try:
            self.istemci().head_object(
                Bucket=self.ayarlar["bucket"], Key=self._anahtar(anahtar)
            )
            return True
        except Exception:
            return False

    def yerel_yol(self, anahtar: str) -> Path | None:
        """Nesne depolamadaki dosyanın yerel yolu yoktur."""
        return None


# --- Seçim ----------------------------------------------------------------
_depo = None
_depo_adi: str | None = None


def depo():
    """Yapılandırmaya uyan depo nesnesi (tekil).

    Ortam değişkeni değişirse yeni depo kurulur; testler arka uçları aynı
    süreç içinde değiştirebilsin diye seçim her çağrıda karşılaştırılır.
    """
    global _depo, _depo_adi

    istenen = config.storage_backend()
    if _depo is None or _depo_adi != istenen:
        _depo = S3Depo() if istenen == config.STORAGE_S3 else YerelDepo()
        _depo_adi = istenen
    return _depo


def depoyu_sifirla() -> None:
    """Önbelleklenen depoyu bırakır (testler ve taşıma aracı için)."""
    global _depo, _depo_adi
    _depo, _depo_adi = None, None


# --- Kısayollar -----------------------------------------------------------
def yaz(anahtar: str, veri: bytes) -> None:
    depo().yaz(anahtar, veri)


def oku(anahtar: str) -> bytes:
    return depo().oku(anahtar)


def akis(anahtar: str) -> BinaryIO:
    return depo().akis(anahtar)


def sil(anahtar: str) -> None:
    depo().sil(anahtar)


def var_mi(anahtar: str) -> bool:
    return depo().var_mi(anahtar)


def yerel_yol(anahtar: str) -> Path | None:
    return depo().yerel_yol(anahtar)


def arka_uc_adi() -> str:
    return depo().ad


def gecici_kopya(anahtar: str, dosya_adi: str) -> Path:
    """Dosyayı açılabilir bir yola indirir.

    Yerel arka uçta dosyanın kendi yolu döner (kopya çıkarılmaz). Nesne
    depolamada geçici klasöre indirilir — masaüstü arayüzün eki sistem
    programıyla açabilmesi için gereken tek şey budur.
    """
    mevcut = yerel_yol(anahtar)
    if mevcut is not None:
        if not mevcut.is_file():
            raise StorageError("Dosya sunucuda bulunamadı.")
        return mevcut

    import tempfile

    hedef = Path(tempfile.mkdtemp(prefix="mat-ek-")) / dosya_adi
    veri = oku(anahtar)
    hedef.write_bytes(veri)
    return hedef


def kopyala(kaynak: Path, anahtar: str) -> None:
    """Diskteki bir dosyayı depoya alır (taşıma aracı ve masaüstü için)."""
    hedef = yerel_yol(anahtar)
    if hedef is not None:
        # Yerel arka uçta baytları bellekten geçirmek yerine doğrudan
        # kopyalamak büyük dosyalarda daha ucuzdur.
        try:
            shutil.copyfile(kaynak, hedef)
        except OSError as exc:
            raise StorageError(f"Dosya kopyalanamadı: {exc}") from exc
        return

    try:
        veri = Path(kaynak).read_bytes()
    except OSError as exc:
        raise StorageError(f"Kaynak dosya okunamadı: {exc}") from exc
    yaz(anahtar, veri)
