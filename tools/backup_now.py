"""Haftalık veritabanı yedeği alır ve doğrular.

Zamanlanmış görev / cron tarafından çağrılmak üzere tasarlandı. Yedek
periyodu dolmadıysa hiçbir şey yapmaz, bu yüzden günlük çalıştırmak da
güvenlidir.

Kullanım:
    python tools/backup_now.py           # periyot dolduysa yedek al
    python tools/backup_now.py --force   # periyoda bakma, hemen al
    python tools/backup_now.py --durum   # sadece son yedeğin yaşını yaz

Windows'ta haftalık zamanlanmış görev oluşturmak için:
    schtasks /create /tn "Ariza Takip Yedek" /sc weekly /d SUN /st 03:00 ^
             /tr "\"C:\\...\\.venv\\Scripts\\python.exe\" \"C:\\...\\tools\\backup_now.py\""

Sunucuda (Linux) crontab:
    0 3 * * 0  /opt/ariza-takip/.venv/bin/python /opt/ariza-takip/tools/backup_now.py

ÖNEMLİ: Bu yedek, bulut sağlayıcısının otomatik yedeğinin yerine değil
üstünedir. Sağlayıcı tarafındaki günlük yedek / zaman noktasına dönüş
özelliğini kapatmayın.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config  # noqa: E402
from app.services import backup_service  # noqa: E402
from app.utils.helpers import fmt_datetime, now_utc  # noqa: E402


def _print_status() -> None:
    backups = backup_service.list_backups()
    age = backup_service.last_backup_age_days()

    print(f"Veritabanı     : {config.database_url_safe()}")
    print(f"Yedek klasörü  : {config.backups_dir()}")
    print(f"Yedek sayısı   : {len(backups)}")

    if age is None:
        print("Son yedek      : hiç yedek alınmamış")
        return

    newest = backups[0]
    size_mb = newest.stat().st_size / (1024 * 1024)
    print(f"Son yedek      : {newest.name} ({size_mb:.1f} MB, {age:.1f} gün önce)")

    if age > backup_service.BACKUP_INTERVAL_DAYS:
        print(
            f"UYARI: son yedek {age:.0f} günlük, periyot "
            f"{backup_service.BACKUP_INTERVAL_DAYS} gün. Yedek alınmalı."
        )


def main() -> int:
    if "--durum" in sys.argv:
        _print_status()
        return 0

    force = "--force" in sys.argv
    print(f"[{fmt_datetime(now_utc())}] Yedekleme başlatıldı.")

    try:
        target = backup_service.auto_backup(force=force)
    except backup_service.BackupError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1

    if target is None:
        age = backup_service.last_backup_age_days()
        print(
            f"Son yedek {age:.1f} gün önce alınmış, periyot "
            f"({backup_service.BACKUP_INTERVAL_DAYS} gün) dolmadı. Atlandı."
        )
        return 0

    size_mb = target.stat().st_size / (1024 * 1024)
    # auto_backup zaten pg_restore ile doğrulama yapıyor; sayıyı raporlayalım.
    entries = backup_service.verify_backup(target)
    print(f"Yedek alındı  : {target}")
    print(f"Boyut         : {size_mb:.2f} MB")
    print(f"Doğrulandı    : arşivde {entries} nesne okunabilir")
    print(f"Saklanan yedek: {len(backup_service.list_backups())} adet "
          f"(en fazla {backup_service.KEEP_BACKUPS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
