"""Veritabanı yedekleme ve geri yükleme (PostgreSQL).

Kullanıcının kararı: haftada bir dış yedek.

Önemli: bu, sağlayıcının otomatik yedeğinin **yerine değil üstünedir.**
Yönetilen PostgreSQL servisleri günlük otomatik yedek + zaman noktasına
dönüş sunar; onu kapatmayın. Buradaki haftalık dışa aktarım, sağlayıcıdan
bağımsız ikinci bir kopya sağlar.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from app import config

# Haftalık yedek periyodu (auto_backup bu süre dolmadan yeni yedek almaz).
BACKUP_INTERVAL_DAYS = 7
# Kaç haftalık yedek saklansın (yaklaşık 3 ay).
KEEP_BACKUPS = 12

_TOOL_SEARCH_PATHS = [
    Path(r"C:\Program Files\PostgreSQL"),
    Path(r"C:\Program Files (x86)\PostgreSQL"),
]


class BackupError(Exception):
    """Yedekleme hatası (kullanıcıya gösterilebilir mesaj)."""


def _find_tool(name: str) -> str:
    """pg_dump / pg_restore konumunu bulur (PATH veya standart kurulum yolu)."""
    found = shutil.which(name)
    if found:
        return found

    candidates: list[Path] = []
    for root in _TOOL_SEARCH_PATHS:
        if root.is_dir():
            # En yeni sürümü tercih et.
            for version_dir in sorted(root.iterdir(), reverse=True):
                candidate = version_dir / "bin" / f"{name}.exe"
                if candidate.is_file():
                    candidates.append(candidate)
    if candidates:
        return str(candidates[0])

    raise BackupError(
        f"'{name}' bulunamadı. PostgreSQL istemci araçlarının kurulu ve "
        "PATH'te olduğundan emin olun."
    )


def _run(tool: str, args: list[str]) -> None:
    """Aracı çalıştırır; şifre ortam değişkeniyle geçilir, komut satırında görünmez."""
    env = os.environ.copy()
    env["PGPASSWORD"] = _password_from_url()

    result = subprocess.run(
        [_find_tool(tool), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise BackupError(f"{tool} başarısız oldu:\n{detail[:800]}")


def _password_from_url() -> str:
    url = config.database_url()
    if "://" not in url or "@" not in url:
        return ""
    _, _, rest = url.partition("://")
    credentials, _, _ = rest.rpartition("@")
    _, _, password = credentials.partition(":")
    return password


def default_backup_name(as_zip: bool = False) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"ariza_takip_yedek_{stamp}" + (".zip" if as_zip else ".dump")


def backup_database(target_path: str | Path) -> Path:
    """Veritabanını sıkıştırılmış özel biçimde (custom format) dışa aktarır.

    Özel biçim seçildi çünkü pg_restore ile seçmeli geri yükleme yapılabilir
    ve düz SQL'e göre belirgin şekilde küçüktür.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    _run("pg_dump", [
        "--dbname", config.database_url(),
        "--format", "custom",
        "--compress", "9",
        "--no-owner",
        "--no-privileges",
        "--file", str(target),
    ])

    if not target.exists() or target.stat().st_size == 0:
        raise BackupError("Yedek dosyası oluşturulamadı veya boş.")
    verify_backup(target)
    return target


def verify_backup(path: str | Path) -> int:
    """Arşivin okunabilir olduğunu doğrular, içindeki nesne sayısını döner.

    Doğrulanmamış yedek yedek değildir — her yedekten sonra çalıştırılır.
    """
    source = Path(path)
    if not source.is_file():
        raise BackupError("Yedek dosyası bulunamadı.")

    result = subprocess.run(
        [_find_tool("pg_restore"), "--list", str(source)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise BackupError(
            "Yedek dosyası okunamadı, bozuk olabilir:\n"
            f"{(result.stderr or '').strip()[:400]}"
        )
    entries = [
        line for line in result.stdout.splitlines()
        if line.strip() and not line.startswith(";")
    ]
    if not entries:
        raise BackupError("Yedek dosyası boş görünüyor.")
    return len(entries)


def backup_full(target_zip: str | Path) -> Path:
    """Veritabanı dökümü + ek dosyalarını tek bir zip arşivine alır."""
    target = Path(target_zip)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_dump = config.backups_dir() / "_temp_backup.dump"
    backup_database(temp_dump)
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_dump, "ariza_takip.dump")
            att_dir = config.attachments_dir()
            for file in att_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, f"ekler/{file.relative_to(att_dir)}")
    except OSError as exc:
        raise BackupError(f"Yedek arşivi oluşturulamadı: {exc}") from exc
    finally:
        temp_dump.unlink(missing_ok=True)
    return target


def restore_database(source_path: str | Path) -> None:
    """Yedeği aktif veritabanına geri yükler.

    Mevcut veri önce otomatik olarak yedeklenir. Tablolar silinip yeniden
    oluşturulur, bu yüzden işlem geri alınamaz.
    """
    source = Path(source_path)
    verify_backup(source)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety = config.backups_dir() / f"geri_yukleme_oncesi_{stamp}.dump"
    try:
        backup_database(safety)
    except BackupError:
        # Veritabanı hiç kurulmamışsa güvenlik yedeği alınamayabilir.
        pass

    from app.db import database as db
    db.close_pool()

    _run("pg_restore", [
        "--dbname", config.database_url(),
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--single-transaction",
        str(source),
    ])


def list_backups() -> list[Path]:
    return sorted(
        config.backups_dir().glob("*.dump"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def last_backup_age_days() -> float | None:
    backups = list_backups()
    if not backups:
        return None
    newest = datetime.fromtimestamp(backups[0].stat().st_mtime)
    return (datetime.now() - newest).total_seconds() / 86400


def auto_backup(force: bool = False) -> Path | None:
    """Haftalık yedek. Süre dolmadıysa yeni yedek almaz ve None döner."""
    age = last_backup_age_days()
    if not force and age is not None and age < BACKUP_INTERVAL_DAYS:
        return None

    target = backup_database(config.backups_dir() / default_backup_name())
    _prune_old_backups()
    return target


def _prune_old_backups() -> None:
    """En yeni KEEP_BACKUPS yedeği tutar, gerisini siler."""
    for old in list_backups()[KEEP_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass
