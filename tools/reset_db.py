"""Veritabanını tamamen sıfırlar (gerçek kullanıma geçmeden önce).

Demo verisini silip yalnızca varsayılan `admin` hesabıyla boş bir veritabanı
bırakır. Mevcut veritabanı önce yedekler klasörüne kopyalanır.

Kullanım:
    python tools/reset_db.py
    python tools/reset_db.py --force   # onay sormaz
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows konsolu varsayılan olarak cp1254 kullanır; Türkçe çıktı bozulmasın.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.db import database as db  # noqa: E402


def main() -> int:
    db_file = config.db_path()

    if db_file.exists():
        total = db.scalar("SELECT COUNT(*) FROM faults") if _has_tables() else 0
        print(f"Mevcut veritabanı: {db_file}")
        print(f"İçindeki arıza kaydı sayısı: {total}")

        if "--force" not in sys.argv:
            answer = input("\nTÜM VERİLER SİLİNECEK. Devam edilsin mi? (evet/hayir): ")
            if answer.strip().lower() not in ("evet", "e", "yes", "y"):
                print("İşlem iptal edildi.")
                return 1

        db.close_connection()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = config.backups_dir() / f"sifirlama_oncesi_{stamp}.db"
        shutil.copy2(db_file, backup)
        print(f"Güvenlik yedeği alındı: {backup}")

        for suffix in ("", "-wal", "-shm"):
            Path(str(db_file) + suffix).unlink(missing_ok=True)
    else:
        print("Mevcut bir veritabanı bulunamadı, yenisi oluşturulacak.")

    # Ek dosyaları da temizle.
    attachments = config.attachments_dir()
    removed = 0
    for file in attachments.glob("*"):
        if file.is_file():
            file.unlink()
            removed += 1
    if removed:
        print(f"{removed} ek dosyası silindi.")

    db.init_db()
    print("\nVeritabanı sıfırlandı.")
    print("Giriş bilgileri:  admin / admin")
    print("İlk girişten sonra Ayarlar > Şifremi Değiştir menüsünden şifreyi değiştirin.")
    return 0


def _has_tables() -> bool:
    row = db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='faults'"
    )
    return row is not None


if __name__ == "__main__":
    sys.exit(main())
