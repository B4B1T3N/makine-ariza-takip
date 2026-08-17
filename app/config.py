"""Uygulama geneli sabitler ve dosya yolları."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Makine Arıza Takip"
APP_VERSION = "1.0.0"
ORG_NAME = "MakineArizaTakip"


def _base_dir() -> Path:
    """PyInstaller ile paketlendiğinde exe klasörü, aksi halde proje kökü."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()


def data_dir() -> Path:
    """Veritabanı ve eklerin tutulduğu klasör.

    Öncelik sırası:
      1. MAT_DATA_DIR ortam değişkeni (ağ klasörü paylaşımı için)
      2. Exe/proje klasöründe `portable.txt` varsa yanındaki `data` klasörü
      3. %APPDATA%\\MakineArizaTakip
    """
    env = os.environ.get("MAT_DATA_DIR")
    if env:
        path = Path(env)
    elif (BASE_DIR / "portable.txt").exists():
        path = BASE_DIR / "data"
    else:
        appdata = os.environ.get("APPDATA") or str(Path.home())
        path = Path(appdata) / ORG_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "ariza_takip.db"


def attachments_dir() -> Path:
    path = data_dir() / "ekler"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = data_dir() / "yedekler"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Roller ---------------------------------------------------------------
ROLE_OPERATOR = "operator"
ROLE_TECHNICIAN = "teknisyen"
ROLE_MANAGER = "yonetici"

ROLES = (ROLE_OPERATOR, ROLE_TECHNICIAN, ROLE_MANAGER)

ROLE_LABELS = {
    ROLE_OPERATOR: "Operatör",
    ROLE_TECHNICIAN: "Teknisyen",
    ROLE_MANAGER: "Yönetici",
}

# --- Arıza durumları ------------------------------------------------------
STATUS_OPEN = "acik"
STATUS_IN_PROGRESS = "inceleniyor"
STATUS_WAITING = "beklemede"
STATUS_RESOLVED = "cozuldu"
STATUS_CLOSED = "kapatildi"

STATUSES = (
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_WAITING,
    STATUS_RESOLVED,
    STATUS_CLOSED,
)

STATUS_LABELS = {
    STATUS_OPEN: "Açık",
    STATUS_IN_PROGRESS: "İnceleniyor",
    STATUS_WAITING: "Parça/Bekleme",
    STATUS_RESOLVED: "Çözüldü",
    STATUS_CLOSED: "Kapatıldı",
}

# Durum akışı: hangi durumdan hangilerine geçilebilir.
STATUS_TRANSITIONS = {
    STATUS_OPEN: (STATUS_IN_PROGRESS, STATUS_WAITING, STATUS_RESOLVED),
    STATUS_IN_PROGRESS: (STATUS_WAITING, STATUS_RESOLVED, STATUS_OPEN),
    STATUS_WAITING: (STATUS_IN_PROGRESS, STATUS_RESOLVED, STATUS_OPEN),
    STATUS_RESOLVED: (STATUS_CLOSED, STATUS_IN_PROGRESS),
    STATUS_CLOSED: (),
}

# Henüz kapanmamış sayılan durumlar (dashboard "açık arıza" sayımı).
ACTIVE_STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_WAITING)

# Rozet renkleri: her zaman metin etiketiyle birlikte gösterilir, renk tek
# başına anlam taşımaz.
STATUS_COLORS = {
    STATUS_OPEN: "#d03b3b",
    STATUS_IN_PROGRESS: "#c98500",
    STATUS_WAITING: "#4a3aa7",
    STATUS_RESOLVED: "#0ca30c",
    STATUS_CLOSED: "#6b6a66",
}

# --- Öncelikler -----------------------------------------------------------
PRIORITY_LOW = "dusuk"
PRIORITY_MEDIUM = "orta"
PRIORITY_HIGH = "yuksek"
PRIORITY_URGENT = "acil"

PRIORITIES = (PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_URGENT)

PRIORITY_LABELS = {
    PRIORITY_LOW: "Düşük",
    PRIORITY_MEDIUM: "Orta",
    PRIORITY_HIGH: "Yüksek",
    PRIORITY_URGENT: "Acil",
}

PRIORITY_ORDER = {
    PRIORITY_URGENT: 0,
    PRIORITY_HIGH: 1,
    PRIORITY_MEDIUM: 2,
    PRIORITY_LOW: 3,
}

PRIORITY_COLORS = {
    PRIORITY_LOW: "#2a78d6",
    PRIORITY_MEDIUM: "#c98500",
    PRIORITY_HIGH: "#eb6834",
    PRIORITY_URGENT: "#d03b3b",
}

# --- Log/geçmiş kayıt tipleri --------------------------------------------
LOG_CREATED = "olusturuldu"
LOG_STATUS = "durum"
LOG_NOTE = "not"
LOG_ASSIGN = "atama"
LOG_ATTACHMENT = "ek"
LOG_EDIT = "duzenleme"

LOG_LABELS = {
    LOG_CREATED: "Kayıt oluşturuldu",
    LOG_STATUS: "Durum değişikliği",
    LOG_NOTE: "Not eklendi",
    LOG_ASSIGN: "Atama",
    LOG_ATTACHMENT: "Dosya eklendi",
    LOG_EDIT: "Kayıt düzenlendi",
}

DATETIME_FMT = "%d.%m.%Y %H:%M"
DATE_FMT = "%d.%m.%Y"
