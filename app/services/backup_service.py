"""Veritabanı yedekleme ve geri yükleme."""
from __future__ import annotations

import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from app import config
from app.db import database as db


class BackupError(Exception):
    """Yedekleme hatası (kullanıcıya gösterilebilir mesaj)."""


def default_backup_name(as_zip: bool = False) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"ariza_takip_yedek_{stamp}" + (".zip" if as_zip else ".db")


def backup_database(target_path: str | Path) -> Path:
    """Veritabanını hedef dosyaya kopyalar.

    sqlite3'ün backup API'si kullanılır; uygulama açıkken WAL modunda da
    tutarlı bir kopya üretir.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source = db.get_connection()
        dest = sqlite3.connect(str(target))
        with dest:
            source.backup(dest)
        dest.close()
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"Yedek alınamadı: {exc}") from exc
    return target


def backup_full(target_zip: str | Path) -> Path:
    """Veritabanı + ek dosyalarını tek bir zip arşivine alır."""
    target = Path(target_zip)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_db = config.backups_dir() / "_temp_backup.db"
    backup_database(temp_db)
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_db, "ariza_takip.db")
            att_dir = config.attachments_dir()
            for file in att_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, f"ekler/{file.relative_to(att_dir)}")
    except OSError as exc:
        raise BackupError(f"Yedek arşivi oluşturulamadı: {exc}") from exc
    finally:
        temp_db.unlink(missing_ok=True)
    return target


def auto_backup() -> Path:
    """Uygulama içi yedekler klasörüne otomatik bir kopya alır."""
    return backup_database(config.backups_dir() / default_backup_name())


def restore_database(source_path: str | Path) -> None:
    """Seçilen .db dosyasını aktif veritabanının yerine koyar.

    Mevcut veritabanı önce `.geri_yukleme_oncesi` ekiyle yedeklenir.
    Çağıran tarafın işlem sonrası uygulamayı yeniden başlatması gerekir.
    """
    source = Path(source_path)
    if not source.is_file():
        raise BackupError("Yedek dosyası bulunamadı.")

    try:
        probe = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        tables = {
            r[0]
            for r in probe.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        probe.close()
    except sqlite3.Error as exc:
        raise BackupError("Seçilen dosya geçerli bir SQLite yedeği değil.") from exc

    required = {"users", "machines", "faults", "fault_logs"}
    if not required.issubset(tables):
        raise BackupError(
            "Seçilen dosya bu uygulamaya ait bir yedek gibi görünmüyor."
        )

    current = config.db_path()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db.close_connection()

    try:
        if current.exists():
            shutil.copy2(current, config.backups_dir() / f"geri_yukleme_oncesi_{stamp}.db")
        # WAL/SHM artıkları eski veriyi geri getirmesin diye temizlenir.
        for suffix in ("-wal", "-shm"):
            Path(str(current) + suffix).unlink(missing_ok=True)
        shutil.copy2(source, current)
    except OSError as exc:
        raise BackupError(f"Geri yükleme başarısız: {exc}") from exc


def list_backups() -> list[Path]:
    return sorted(
        config.backups_dir().glob("*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
