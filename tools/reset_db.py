"""Veritabanını tamamen sıfırlar (gerçek kullanıma geçmeden önce).

Demo verisini silip yalnızca varsayılan `admin` hesabıyla boş bir şema
bırakır. Mevcut veriden önce pg_dump yedeği alınır.

Kullanım:
    python tools/reset_db.py
    python tools/reset_db.py --force   # onay sormaz
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows konsolu varsayılan olarak cp1254 kullanır; Türkçe çıktı bozulmasın.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.db import database as db  # noqa: E402
from app.services import backup_service  # noqa: E402


def main() -> int:
    print(f"Veritabanı: {config.database_url_safe()}")

    try:
        total = db.scalar("SELECT COUNT(*) FROM faults")
        users = db.scalar("SELECT COUNT(*) FROM users")
        print(f"İçindeki arıza kaydı: {total}, kullanıcı: {users}")
        kurulu = True
    except Exception:
        print("Şema henüz kurulmamış, yeni oluşturulacak.")
        kurulu = False

    if kurulu:
        if "--force" not in sys.argv:
            answer = input("\nTÜM VERİLER SİLİNECEK. Devam edilsin mi? (evet/hayir): ")
            if answer.strip().lower() not in ("evet", "e", "yes", "y"):
                print("İşlem iptal edildi.")
                return 1

        try:
            backup = backup_service.auto_backup(force=True)
            print(f"Güvenlik yedeği alındı: {backup}")
        except backup_service.BackupError as exc:
            print(f"UYARI: güvenlik yedeği alınamadı: {exc}")
            if "--force" not in sys.argv:
                answer = input("Yedeksiz devam edilsin mi? (evet/hayir): ")
                if answer.strip().lower() not in ("evet", "e", "yes", "y"):
                    return 1

        db.drop_all()
        print("Tablolar silindi.")

    # Ek dosyalarını da temizle.
    removed = 0
    for file in config.attachments_dir().glob("*"):
        if file.is_file():
            file.unlink()
            removed += 1
    if removed:
        print(f"{removed} ek dosyası silindi.")

    db.init_db()
    db.close_pool()

    print("\nVeritabanı sıfırlandı.")
    print("Giriş bilgileri:  admin / admin")
    print("İlk girişten sonra Ayarlar > Şifremi Değiştir menüsünden şifreyi değiştirin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
