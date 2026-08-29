"""Yerel diskteki ek dosyalarını nesne depolamaya taşır (Faz 4).

Veritabanı tarafı değişmez: `attachments.stored_name` her iki arka uçta da
aynı anahtardır. Bu araç yalnızca baytları taşır.

Sıra önemlidir — önce dosyalar kopyalanır, sonra uygulama nesne depolamaya
çevrilir. Tersi yapılırsa, geçiş sırasında yüklenen ekler eski diskte kalır.

Kullanım:
    :: 1) Neyin taşınacağını gör (hiçbir şey yazılmaz)
    set MAT_S3_BUCKET=ariza-ekleri
    python tools/migrate_attachments.py --kuru-calistir

    :: 2) Taşı ve her dosyayı hedefte doğrula
    python tools/migrate_attachments.py

    :: 3) Uygulamayı çevir (.env içinde)
    ::    MAT_STORAGE=s3

Yerel dosyalar **silinmez**. Taşımanın doğruluğundan emin olduktan sonra
`ekler` klasörünü kendiniz arşivleyip kaldırın; araç bunu üstlenmez çünkü
geri dönüşü olmayan tek adım odur.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.db import database as db  # noqa: E402
from app.services import storage_service  # noqa: E402


def _hedef_depo():
    """Taşımanın hedefi her zaman nesne depolamadır.

    `MAT_STORAGE` henüz `yerel` olsa bile hedef S3'tür: taşıma, uygulama
    çevrilmeden önce yapılmalıdır.
    """
    ayarlar = config.s3_settings()
    if not ayarlar["bucket"]:
        raise SystemExit(
            "MAT_S3_BUCKET tanımlı değil. Hedef kovayı ortam değişkeniyle "
            "veya .env dosyasıyla verin."
        )
    return storage_service.S3Depo(ayarlar)


def main() -> int:
    ayristirici = argparse.ArgumentParser(
        description="Yerel ek dosyalarını nesne depolamaya taşır."
    )
    ayristirici.add_argument(
        "--kuru-calistir", action="store_true",
        help="Hiçbir şey yazmaz, ne yapılacağını listeler",
    )
    ayristirici.add_argument(
        "--yeniden", action="store_true",
        help="Hedefte zaten duran dosyaların üzerine yazar",
    )
    args = ayristirici.parse_args()

    db.init_db()
    hedef = _hedef_depo()
    kaynak_klasor = config.attachments_dir()

    kayitlar = db.query(
        "SELECT id, fault_id, file_name, stored_name FROM attachments ORDER BY id"
    )

    print(f"Kaynak klasör : {kaynak_klasor}")
    print(f"Hedef kova    : {hedef.ayarlar['bucket']}"
          f" (önek: {hedef.ayarlar['prefix'] or '—'})")
    print(f"Kayıt sayısı  : {len(kayitlar)}")
    if args.kuru_calistir:
        print("KURU ÇALIŞTIRMA — hiçbir dosya yazılmayacak")
    print("-" * 60)

    tasinan = atlanan = eksik = hatali = 0

    for kayit in kayitlar:
        anahtar = kayit["stored_name"]
        yerel = kaynak_klasor / anahtar

        if not yerel.is_file():
            # Kayıt var ama dosya yok: eski bir kurulumdan kalmış olabilir.
            # Sessizce geçilmez, çünkü kullanıcı ekin kaybolduğunu bilmelidir.
            print(f"EKSİK   #{kayit['id']:>5}  {anahtar}  (yerel dosya yok)")
            eksik += 1
            continue

        if not args.yeniden and hedef.var_mi(anahtar):
            atlanan += 1
            continue

        if args.kuru_calistir:
            print(f"TAŞINACAK #{kayit['id']:>5}  {anahtar}"
                  f"  ({yerel.stat().st_size} bayt)")
            tasinan += 1
            continue

        try:
            hedef.yaz(anahtar, yerel.read_bytes())
        except (storage_service.StorageError, OSError) as exc:
            print(f"HATA    #{kayit['id']:>5}  {anahtar}: {exc}")
            hatali += 1
            continue

        # Yazdıktan sonra doğrulanır: doğrulanmamış kopya, kopya sayılmaz.
        if not hedef.var_mi(anahtar):
            print(f"HATA    #{kayit['id']:>5}  {anahtar}: hedefte doğrulanamadı")
            hatali += 1
            continue

        print(f"TAŞINDI #{kayit['id']:>5}  {anahtar}")
        tasinan += 1

    print("-" * 60)
    print(f"Taşınan: {tasinan}   Zaten hedefte: {atlanan}   "
          f"Yerel dosyası yok: {eksik}   Hata: {hatali}")

    if hatali:
        print("\nHatalı dosyalar var — uygulamayı MAT_STORAGE=s3'e çevirmeden "
              "önce bunları çözün.")
        return 1
    if not args.kuru_calistir and eksik == 0:
        print("\nTaşıma tamam. Artık .env içinde MAT_STORAGE=s3 yapabilirsiniz.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
